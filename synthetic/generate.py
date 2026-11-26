"""Generate synthetic windows for misconceptions that are rare in the real data (#9).

Method (agreed alternative to LLM prompting; see docs/synthetic.md):

1. **Seed.** A real moment in the 2021 cohort where a student ran a file whose
   code does not show the misconception. 2019 is never used: it is the
   cross-cohort test cohort (Stage C).
2. **Real lead-in.** The session's real edits to that file in the 45 s before
   the run are copied as-is, starting from the file's replayed text, so the
   30 s *before* the flagged state is genuine student behaviour.
3. **Injection.** The misconception is typed into the student's own code with a
   minimal edit (``synthetic.inject``), at the student's own typing speed.
4. **Behaviour.** One to three cues from Table 3.3 / the Appendix A codebook
   follow (re-runs, long pauses, prints, switching ``is``/``==``, adding and
   removing ``self``), so each window meets the codebook's rule of structure
   *plus* a behavioural indicator.
5. **QC.** Every synthetic session is replayed and mined with the same code as
   the real data; it is kept only if replay is exact (no DeleteText
   mismatches) and a persistent episode of the intended misconception starts
   at the injection.

Every item records its seed student, so training code can drop items seeded by
any student in the current test fold (#74).
"""

from __future__ import annotations

import ast
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from detectors import analyse
from mining.episodes import mine_session
from replay.progsnap import iter_sessions, load_main_table, replay_session
from synthetic.inject import GROUNDED, MISCONCEPTIONS, Injection, inject
from synthetic.trace import COLUMNS, Timing, Trace

LEAD_IN_MS = 45_000
WINDOW_MS = 30_000
GENERATOR_VERSION = "inject-v1"
CUES = {
    "mutable_default": ["run_repeat", "long_pause", "print_inside"],
    "aliasing": ["pause_after", "print_both", "run_repeat"],
    "identity_literal": ["trial_switch", "run_repeat", "long_pause"],
    "self_confusion": ["toggle_self", "run_repeat", "long_pause"],
}


@dataclass
class Item:
    synthetic_id: str
    misconception: str
    rule: str
    method: str
    note: str
    seed_subject: str
    seed_assignment: str
    seed_file: str
    seed_event_id: int
    seed_ms: int  # the real run the lead-in ends with
    injected_at_ms: int
    cues: list[str]
    rows: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- real data


class RealData:
    """Raw 2021 rows, replayable sessions and per-student timing."""

    def __init__(self, raw_dir: Path):
        path = raw_dir / "2021" / "keystrokes.csv"
        raw = pd.read_csv(path, dtype=str, keep_default_na=False)
        raw["_ts"] = raw["ClientTimestamp"].astype("int64")
        raw["_id"] = raw["EventID"].astype("int64")
        self.raw = {
            key: g.sort_values(["_ts", "_id"])
            for key, g in raw.groupby(["SubjectID", "AssignmentID", "CodeStateSection"])
        }
        self.sessions = {(s, a): ev for s, a, ev in iter_sessions(load_main_table(path))}
        self.timing = self._timing(raw)

    @staticmethod
    def _timing(raw: pd.DataFrame) -> dict[str, Timing]:
        edits = raw[raw.EventType == "File.Edit"].sort_values(["_ts", "_id"])
        out = {}
        for subject, g in edits.groupby("SubjectID"):
            gaps = g.groupby(["AssignmentID", "CodeStateSection"])["_ts"].diff().dropna()
            out[subject] = Timing(
                keystroke_gaps=[int(x) for x in gaps[(gaps >= 30) & (gaps <= 2000)]],
                long_pauses=[int(x) for x in gaps[(gaps >= 10_000) & (gaps <= 60_000)]],
            )
        return out

    def text_before(self, subject, assignment, file, t: int) -> str:
        events = [e for e in self.sessions[(subject, assignment)] if e.timestamp < t]
        files = replay_session(subject, assignment, events).files
        return files[file].text if file in files else ""

    def lead_in(self, subject, assignment, file, lo: int, run_ms: int) -> pd.DataFrame:
        """The file's real rows from ``lo`` up to the run, plus that run's exit-code row."""
        g = self.raw.get((subject, assignment, file))
        if g is None:
            return pd.DataFrame(columns=COLUMNS)
        before = (g._ts >= lo) & (g._ts <= run_ms)
        exit_row = (g.EventType == "Run.Program") & (g._ts > run_ms) & (g._ts <= run_ms + 5000)
        return g[before | exit_row]


# ---------------------------------------------------------------- cues


def _cue(trace: Trace, cue: str, inj: Injection) -> None:
    rng = trace.rng
    if cue in ("pause_after", "long_pause"):
        trace.think()
    elif cue == "run_repeat":
        trace.run()
        trace.wait(rng.randint(2000, 6000))
        trace.run()
    elif cue == "trial_switch":
        m = re.search(r"\bis not\b|\bis\b", trace.text[max(0, inj.edits[0][0] - 2) :])
        if m:
            at = max(0, inj.edits[0][0] - 2) + m.start()
            word, other = m.group(), "!=" if m.group() == "is not" else "=="
            trace.run()
            trace.replace(at, word, other)
            trace.wait(rng.randint(1500, 5000))
            trace.replace(at, other, word)
    elif cue == "print_inside":
        tree = ast.parse(trace.text)
        (f,) = analyse(trace.text, only=["mutable_default"]).findings[:1] or (None,)
        fn = next(
            (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.lineno <= f.line
             and n.body[0].lineno > f.line),
            None,
        ) if f else None  # fmt: skip
        if fn is not None:
            pos = _line_offset(trace.text, fn.body[0].lineno)
            indent = " " * fn.body[0].col_offset
            name = (fn.args.args + fn.args.kwonlyargs)[-1].arg
            trace.type(pos, f"{indent}print({name})\n")
            trace.run()
    elif cue == "print_both":
        found = analyse(trace.text, only=["aliasing"]).findings
        m = re.search(r"'(\w+) = (\w+)'.*on line (\d+)", found[0].message) if found else None
        if m:
            alias, original, line = m.group(1), m.group(2), int(m.group(3))
            indent = re.match(r"\s*", trace.text.splitlines()[line - 1]).group()
            pos = _line_offset(trace.text, line + 1)
            trace.type(pos, f"{indent}print({original})\n{indent}print({alias})\n")
            trace.run()
    elif cue == "toggle_self" and inj.rule == "missing_self":
        offset = inj.edits[0][0]
        trace.run()
        trace.type(offset, inj.edits[0][1])
        trace.wait(rng.randint(2000, 8000))
        trace.erase(offset, inj.edits[0][1])
    elif cue == "toggle_self":
        trace.run()
        trace.think()


def _line_offset(text: str, line: int) -> int:
    lines = text.splitlines(keepends=True)
    return sum(len(x) for x in lines[: line - 1])


# ---------------------------------------------------------------- generation


def _seeds(snapshots: pd.DataFrame, rng: random.Random) -> list:
    """Every file of every run and end-of-session snapshot, deduplicated by code."""
    snaps = snapshots[snapshots.kind.isin(["run", "final"]) & (snapshots.code != "")]
    snaps = snaps.drop_duplicates(["subject", "assignment", "file", "code"])
    cols = ["subject", "assignment", "file", "event_id", "timestamp", "code"]
    seeds = list(snaps[cols].itertuples(index=False))
    rng.shuffle(seeds)
    return seeds


def build_item(real: RealData, seed, misconception: str, number: int, rng, methods=None):
    inj = inject(misconception, seed.code, rng, methods)
    if inj is None:
        return None
    t_seed = int(seed.timestamp)
    start = t_seed - LEAD_IN_MS
    text0 = real.text_before(seed.subject, seed.assignment, seed.file, start)
    lead_in = real.lead_in(seed.subject, seed.assignment, seed.file, start, t_seed)
    sid = f"SYN-{number:04d}"

    trace = Trace(sid, seed.assignment, seed.file, text0, start - 1, real.timing[seed.subject], rng)
    trace._row("File.Edit", SourceLocation="0.0", EditType="X-Checkpoint", InsertText=text0,
               **{"X-Compilable": "1"})  # fmt: skip
    for row in lead_in[COLUMNS].to_dict("records"):
        row["SubjectID"] = sid
        trace.rows.append(row)
        if row["EventType"] == "File.Edit" and row["SourceLocation"]:
            i = int(float(row["SourceLocation"]))
            trace.text = (
                trace.text[:i] + row["InsertText"] + trace.text[i + len(row["DeleteText"]) :]
            )
        trace.t = max(trace.t, int(row["ClientTimestamp"]))
    if trace.text != seed.code:
        return None  # the lead-in does not reproduce the seed (unlogged content)

    trace.t = max(trace.t, t_seed)  # resume after the real run, even if the file was idle
    trace.wait(rng.randint(2000, 8000))
    for offset, delete, insert in inj.edits:
        trace.replace(offset, delete, insert)
    injected_at = trace.t
    menu = CUES[misconception]
    cues = rng.sample(menu, rng.randint(1, len(menu)))
    if "pause_after" in cues:
        cues.remove("pause_after")
        cues.insert(0, "pause_after")
    for cue in cues:
        _cue(trace, cue, inj)
    trace.wait(max(0, injected_at + WINDOW_MS + 1000 - trace.t))
    trace.idle()  # closes the window with a logged event, as the real logs do

    return Item(
        sid, misconception, inj.rule, inj.method, inj.note, seed.subject, seed.assignment,
        seed.file, int(seed.event_id), t_seed, injected_at, cues, trace.rows,
    )  # fmt: skip


def quality_check(items: list[Item], rows_csv: Path) -> dict[str, str]:
    """Replay and mine every synthetic session; return synthetic_id -> failure reason."""
    df = load_main_table(rows_csv)
    by_id = {i.synthetic_id: i for i in items}
    failures = {}
    for subject, assignment, events in iter_sessions(df):
        item = by_id[subject]
        result = replay_session(subject, assignment, events)
        if not result.consistent:
            failures[subject] = "replay mismatch"
            continue
        episodes = [
            e for e in mine_session(subject, assignment, events)
            if e.detector == item.misconception and e.start_ms > item.seed_ms and e.persistent
        ]  # fmt: skip
        if not episodes:
            failures[subject] = "no persistent episode of the target misconception"
    return failures


def generate(raw_dir: Path, snapshots_path: Path, out_dir: Path, per_class: int, seed: int,
             misconceptions=MISCONCEPTIONS, cap_share: float = 0.1) -> dict:  # fmt: skip
    rng = random.Random(seed)
    real = RealData(raw_dir)
    seeds = _seeds(pd.read_parquet(snapshots_path), rng)
    items: list[Item] = []
    for misconception in misconceptions:
        per_student, per_file, made = Counter(), Counter(), 0
        cap = max(5, int(per_class * cap_share))
        # Grounded injections first (edit only what the student wrote); invented-line
        # methods fill the remainder only if real code cannot supply enough.
        for methods in (GROUNDED, None):
            for s in seeds:
                if made >= per_class:
                    break
                key = (s.subject, s.assignment, s.file)
                if per_student[s.subject] >= cap or per_file[key] >= 3:
                    continue
                item = build_item(real, s, misconception, len(items) + 1, rng, methods)
                if item is None:
                    continue
                items.append(item)
                per_student[s.subject] += 1
                per_file[key] += 1
                made += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    rows_csv = out_dir / "keystrokes.csv"
    _write(items, rows_csv)
    failures = quality_check(items, rows_csv)
    kept = [i for i in items if i.synthetic_id not in failures]
    _write(kept, rows_csv)

    manifest = pd.DataFrame(
        [
            {k: v for k, v in i.__dict__.items() if k != "rows"}
            | {
                "cues": "+".join(i.cues),
                "events": len(i.rows),
                "synthetic": True,
                "generator": GENERATOR_VERSION,
                "seed": seed,
            }
            for i in kept
        ]  # fmt: skip
    )
    manifest.to_csv(out_dir / "manifest.csv", index=False)
    return {
        "generator": GENERATOR_VERSION,
        "seed": seed,
        "requested_per_class": per_class,
        "generated": Counter(i.misconception for i in items),
        "kept": Counter(i.misconception for i in kept),
        "kept_by_method": Counter(f"{i.misconception}/{i.method}" for i in kept),
        "rejected": Counter(failures.values()),
        "seed_students": {
            m: manifest[manifest.misconception == m].seed_subject.nunique() for m in misconceptions
        }
        if len(manifest)
        else {},  # fmt: skip
    }


def _write(items: list[Item], path: Path) -> None:
    rows = [r for i in items for r in i.rows]
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["EventID"] = range(len(df))
    df.to_csv(path, index=False)


def usable_for_training(manifest: pd.DataFrame, test_subjects) -> pd.DataFrame:
    """Synthetic items allowed in a fold whose test students are ``test_subjects``.

    Items seeded by a test-fold student are dropped, so no test student's code
    reaches the training data.
    """
    return manifest[~manifest.seed_subject.isin(set(test_subjects))]
