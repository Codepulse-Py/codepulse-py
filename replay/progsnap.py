"""Replay ProgSnap2 sessions (one student x one assignment) from keystrokes.csv."""

from __future__ import annotations

import ast
import warnings
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from itertools import groupby
from pathlib import Path

import pandas as pd

from replay.engine import Edit, FileState

# ProgSnap2 column -> attribute name used during replay.
COLUMNS = {
    "EventID": "event_id",
    "SubjectID": "subject",
    "AssignmentID": "assignment",
    "CodeStateSection": "file",
    "EventType": "event_type",
    "EditType": "edit_type",
    "SourceLocation": "offset",
    "InsertText": "insert",
    "DeleteText": "delete",
    "ClientTimestamp": "timestamp",
    "X-Compilable": "compilable",
    "X-Metadata": "meta",  # 2021 only
}


@dataclass(frozen=True, slots=True)
class Event:
    event_id: int
    timestamp: int
    file: str
    kind: str  # "edit" | "checkpoint" | "run" | "submit" | "other"
    edit: Edit | None = None
    checkpoint: str = ""
    compilable: bool | None = None


@dataclass(frozen=True, slots=True)
class Snapshot:
    """All files of a session at one moment."""

    kind: str  # "run" | "submit" | "final"
    event_id: int
    timestamp: int
    file: str
    files: dict[str, str]


@dataclass
class SessionResult:
    subject: str
    assignment: str
    files: dict[str, FileState] = field(default_factory=dict)
    snapshots: list[Snapshot] = field(default_factory=list)
    # 2019 X-Checkpoint rows: on an empty file, or equal / unequal to the replay.
    checkpoints_on_empty: int = 0
    checkpoints_matched: int = 0
    checkpoints_differed: int = 0
    # Replayed text parses <=> logged X-Compilable, checked after each timestamp.
    compile_checks: int = 0
    compile_agreements: int = 0
    # Per file: does the replayed final text agree with the last X-Compilable?
    final_agrees: dict[str, bool] = field(default_factory=dict)

    @property
    def consistent(self) -> bool:
        return all(f.consistent for f in self.files.values())

    @property
    def matches_final(self) -> bool:
        return all(self.final_agrees.values())


def parses(source: str) -> bool:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            ast.parse(source)
        except (SyntaxError, ValueError):
            return False
    return True


# ---------------------------------------------------------------- loading


def load_main_table(path: Path) -> pd.DataFrame:
    """Read the columns replay needs, sorted into replay order."""
    df = pd.read_csv(path, usecols=lambda c: c in COLUMNS, dtype=str, keep_default_na=False)
    df = df.rename(columns=COLUMNS)
    if "meta" not in df:
        df["meta"] = ""
    df["event_id"] = df["event_id"].astype("int64")
    df["timestamp"] = df["timestamp"].astype("int64")
    # Within a file EventID is chronological; across files of a session only
    # the timestamp is. Sorting on both keeps per-file order and merges files.
    return df.sort_values(
        ["subject", "assignment", "timestamp", "event_id"], kind="stable"
    ).reset_index(drop=True)[list(COLUMNS.values())]


def to_event(row) -> Event:
    compilable = {"1": True, "0": False}.get(row.compilable)
    base = dict(event_id=row.event_id, timestamp=row.timestamp, file=row.file)
    if row.event_type == "File.Edit":
        if row.edit_type == "X-Checkpoint":
            return Event(**base, kind="checkpoint", checkpoint=row.insert, compilable=compilable)
        if row.offset == "" or not (row.insert or row.delete):
            return Event(**base, kind="other")
        edit = Edit(row.event_id, int(float(row.offset)), row.insert, row.delete)
        return Event(**base, kind="edit", edit=edit, compilable=compilable)
    if row.event_type == "Run.Program":
        # 2021 logs a "Start" row and then an exit-code row for every run.
        return Event(**base, kind="run" if row.meta in ("", "Start") else "other")
    if row.event_type == "Submit":
        return Event(**base, kind="submit")
    return Event(**base, kind="other")


def iter_sessions(df: pd.DataFrame) -> Iterator[tuple[str, str, list[Event]]]:
    """Yield (subject, assignment, events) from a frame made by load_main_table."""
    rows = df.itertuples(index=False, name="Row")
    for (subject, assignment), group in groupby(rows, key=lambda r: (r.subject, r.assignment)):
        yield subject, assignment, [to_event(r) for r in group]


# ---------------------------------------------------------------- replay


def replay_session(
    subject: str,
    assignment: str,
    events: list[Event],
    check_every_state: bool = False,
    on_state: Callable[[Event, str, str], None] | None = None,
) -> SessionResult:
    """Replay one session's events (already in replay order).

    ``on_state(event, file, text)`` is called after the last edit of each
    timestamp on a file, i.e. at every distinct code state. With
    ``check_every_state`` each of those states is also parsed and compared with
    the logged ``X-Compilable``; otherwise only the final state of each file is.
    """
    result = SessionResult(subject, assignment)
    logged: dict[str, bool] = {}

    def state(name: str) -> FileState:
        return result.files.setdefault(name, FileState())

    def snapshot(kind: str, event: Event) -> None:
        files = {name: f.text for name, f in result.files.items()}
        result.snapshots.append(Snapshot(kind, event.event_id, event.timestamp, event.file, files))

    def settled(event: Event) -> None:
        text = result.files[event.file].text
        if event.compilable is not None:
            logged[event.file] = event.compilable
            if check_every_state:
                result.compile_checks += 1
                result.compile_agreements += parses(text) == event.compilable
        if on_state is not None:
            on_state(event, event.file, text)

    for i, event in enumerate(events):
        if event.kind == "edit":
            state(event.file).apply(event.edit)
            nxt = events[i + 1] if i + 1 < len(events) else None
            if not (
                nxt is not None
                and nxt.kind == "edit"
                and nxt.file == event.file
                and nxt.timestamp == event.timestamp
            ):
                settled(event)
        elif event.kind == "checkpoint":
            f = state(event.file)
            if not f.text:
                result.checkpoints_on_empty += 1
            elif f.text == event.checkpoint:
                result.checkpoints_matched += 1
            else:
                result.checkpoints_differed += 1
            f.checkpoint(event.checkpoint)
            settled(event)
        elif event.kind in ("run", "submit"):
            snapshot(event.kind, event)

    if events:
        snapshot("final", events[-1])
    result.final_agrees = {
        name: parses(result.files[name].text) == flag for name, flag in logged.items()
    }
    return result
