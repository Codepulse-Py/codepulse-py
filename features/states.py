"""Algorithm 1: label every interval between events with one behavioural state.

Table 3.1 of the final proposal, made operational (issue #5):

| State          | Rule                                                              |
|----------------|-------------------------------------------------------------------|
| RUNNING        | from a run start until the run ends (logged end, else 10 s); the  |
|                | rest of a longer gap is labelled by its own length               |
| PASTING        | the interval ends at an insert of more than 50 characters          |
| FLAILING       | the interval ends at an edit inside a delete/retype cycle (below)  |
| BURST_TYPING   | under 100 ms between events                                       |
| TYPING         | 100 ms to 2 s (Table 3.1 gives 100-500 ms; 0.5-2 s is unassigned   |
|                | there and is treated as typing with short hesitations)            |
| PAUSE          | 2 to 10 s                                                         |
| DEEP_THINKING  | more than 10 s                                                    |

Rules are applied in that order. Only edit and run events count, from every
file of the session: they are what both cohorts and the live editor record
(2021-only rows such as arrow-key ``X-Keystroke`` events are ignored), so the
states mean the same thing everywhere.

**FLAILING.** An edit is part of a delete/retype cycle when, among the edits to
the same file in the last ``FLAIL_WINDOW_MS`` that are within
``FLAIL_REGION`` characters of it, the student switched from deleting to
inserting at least ``FLAIL_SWITCHES`` times. One typo fix (type, backspace,
retype) is a single switch and is not flailing; rewriting the same spot over
and over is.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from replay.progsnap import Event

STATES = (
    "BURST_TYPING",
    "TYPING",
    "PAUSE",
    "DEEP_THINKING",
    "FLAILING",
    "PASTING",
    "RUNNING",
)
BURST_MS = 100
TYPING_MS = 2_000
PAUSE_MS = 10_000
RUN_DEFAULT_MS = 10_000  # how long a run counts as RUNNING when its end is not logged
PASTE_CHARS = 50
FLAIL_WINDOW_MS = 10_000
FLAIL_REGION = 20
FLAIL_SWITCHES = 3


@dataclass(frozen=True, slots=True)
class Interval:
    start_ms: int
    end_ms: int
    state: str


def _kind(event: Event) -> str:
    """'I' insert, 'D' delete, 'R' replace (both)."""
    e = event.edit
    if e.insert and e.delete:
        return "R"
    return "I" if e.insert else "D"


def flailing_flags(events: list[Event]) -> list[bool]:
    """For each event, whether it is an edit inside a delete/retype cycle."""
    recent: dict[str, deque] = {}
    flags = []
    for e in events:
        if e.kind != "edit":
            flags.append(False)
            continue
        q = recent.setdefault(e.file, deque())
        while q and e.timestamp - q[0][0] > FLAIL_WINDOW_MS:
            q.popleft()
        q.append((e.timestamp, e.edit.offset, _kind(e)))
        near = [k for _, pos, k in q if abs(pos - e.edit.offset) <= FLAIL_REGION]
        switches = sum(
            1 for a, b in zip(near, near[1:], strict=False) if a in "DR" and b in "IR" and a != b
        )
        flags.append(switches >= FLAIL_SWITCHES)
    return flags


def activity(events: list[Event]) -> list[Event]:
    """The events behavioural states are computed from: edits and run starts."""
    return [e for e in events if e.kind in ("edit", "run")]


def _by_gap(gap: int) -> str:
    if gap < BURST_MS:
        return "BURST_TYPING"
    if gap < TYPING_MS:
        return "TYPING"
    if gap < PAUSE_MS:
        return "PAUSE"
    return "DEEP_THINKING"


def label(events: list[Event], run_end: dict[int, int] | None = None) -> list[Interval]:
    """States for the intervals between consecutive activity events of a session.

    ``run_end`` maps a run's start timestamp to when it ended, where logged.
    An interval that starts at a run is split: RUNNING while the program runs,
    then the remainder is labelled like any other gap.
    """
    run_end = run_end or {}
    acts = activity(events)
    flail = flailing_flags(acts)
    out = []
    for i in range(1, len(acts)):
        prev, cur = acts[i - 1], acts[i]
        start, end = prev.timestamp, cur.timestamp
        if prev.kind == "run":
            ran = run_end.get(start, start + RUN_DEFAULT_MS) - start
            stop = min(end, start + max(0, ran))
            if stop > start:
                out.append(Interval(start, stop, "RUNNING"))
            start = stop
            if start >= end:
                continue
        if cur.kind == "edit" and len(cur.edit.insert) > PASTE_CHARS:
            state = "PASTING"
        elif flail[i]:
            state = "FLAILING"
        else:
            state = _by_gap(end - start)
        out.append(Interval(start, end, state))
    return out
