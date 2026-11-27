"""Turn per-state detector findings into candidate episodes (RQ1, issue #8).

A pattern normally stays on screen across many code states while the student
edits around it, so counting states (or findings) would count one misconception
hundreds of times. An *episode* is one continuous stretch during which a
detector rule flags a file:

- it starts at the first state where the rule fires;
- it ends at the first state where the rule no longer fires, unless the rule
  fires again within ``GAP_MS`` (a line being retyped or briefly unparseable);
- several simultaneous instances of the same rule in one file count once, so
  episode counts err on the low side for the 50-case gate.

Unparseable states keep the file's last parseable findings (the detectors'
``StructuralAnalyzer`` fallback), so typing through a syntax error does not
split an episode.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from detectors import REGISTRY, StructuralAnalyzer
from detectors.base import Finding
from replay.progsnap import Event, replay_session

GAP_MS = 30_000  # one window length (§3.1.2)
PERSISTENT_MS = 10_000  # one window stride: present long enough to be seen in a window
PASTE_CHARS = 50  # PASTING state threshold (Table 3.1)
WINDOW_MS = 30_000  # behavioural context attached on each side of the episode start


@dataclass
class Episode:
    subject: str
    assignment: str
    file: str
    detector: str
    rule: str
    start_ms: int
    start_event: int
    origin: str  # "typed" | "paste" | "checkpoint": how the first flagged state arose
    line: int
    line_text: str
    message: str
    last_seen_ms: int = 0
    end_ms: int = 0
    states: int = 0
    absent_since: int | None = None
    runs_during: int = 0
    context: dict[str, float] = field(default_factory=dict)

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def persistent(self) -> bool:
        return self.duration_ms >= PERSISTENT_MS or self.runs_during > 0


def _origin(event: Event) -> str:
    if event.kind == "checkpoint":
        return "checkpoint"
    if event.edit is not None and len(event.edit.insert) > PASTE_CHARS:
        return "paste"
    return "typed"


def _line_text(source: str, line: int) -> str:
    lines = source.splitlines()
    return " ".join(lines[line - 1].split()) if 0 < line <= len(lines) else ""


class EpisodeTracker:
    """Follows one session's files state by state and records episodes."""

    def __init__(self, subject: str, assignment: str, gap_ms: int = GAP_MS):
        self.subject, self.assignment, self.gap_ms = subject, assignment, gap_ms
        self.open: dict[tuple[str, str, str], Episode] = {}
        self.closed: list[Episode] = []

    def observe(self, event: Event, file: str, text: str, findings: list[Finding]) -> None:
        ts = event.timestamp
        active: dict[tuple[str, str], Finding] = {}
        for f in findings:
            active.setdefault((f.detector, f.rule), f)

        for key, ep in list(self.open.items()):
            if key[0] != file:
                continue
            present = key[1:] in active
            if ep.absent_since is not None and ts - ep.absent_since > self.gap_ms:
                self._close(key, ep.absent_since)
            elif present:
                ep.absent_since, ep.last_seen_ms = None, ts
                ep.states += 1
            elif ep.absent_since is None:
                ep.absent_since = ts

        for (detector, rule), f in active.items():
            key = (file, detector, rule)
            if key not in self.open:
                self.open[key] = Episode(
                    self.subject, self.assignment, file, detector, rule,
                    start_ms=ts, start_event=event.event_id, origin=_origin(event),
                    line=f.line, line_text=_line_text(text, f.line), message=f.message,
                    last_seen_ms=ts, states=1,
                )  # fmt: skip

    def _close(self, key, end_ms: int) -> None:
        ep = self.open.pop(key)
        ep.end_ms = max(end_ms, ep.start_ms)
        self.closed.append(ep)

    def finish(self, session_end_ms: int) -> list[Episode]:
        for key, ep in list(self.open.items()):
            self._close(key, ep.absent_since if ep.absent_since is not None else session_end_ms)
        return self.closed


def behaviour_context(episode: Episode, times: list[int], events: list[Event]) -> dict:
    """Summary of the whole session's activity WINDOW_MS before and after the episode start.

    The full ~40-feature vectors come from Algorithm 2 (#7); this is enough to
    describe and sample candidates for annotation.
    """
    out = {}
    t0 = episode.start_ms
    # Half-open windows [t0 - W, t0) and [t0, t0 + W): the start event is in "post" only.
    for side, lo, hi in (("pre", t0 - WINDOW_MS, t0), ("post", t0, t0 + WINDOW_MS)):
        i, j = bisect.bisect_left(times, lo), bisect.bisect_left(times, hi)
        window = events[i:j]
        edits = [e for e in window if e.kind == "edit"]
        stamps = [e.timestamp for e in edits]
        out[f"{side}_edits"] = len(edits)
        out[f"{side}_chars_inserted"] = sum(len(e.edit.insert) for e in edits)
        out[f"{side}_chars_deleted"] = sum(len(e.edit.delete) for e in edits)
        out[f"{side}_runs"] = sum(e.kind == "run" for e in window)
        gaps = [b - a for a, b in zip([lo, *stamps], [*stamps, hi], strict=True)]
        out[f"{side}_longest_pause_s"] = round(max(gaps) / 1000, 1)
    return out


def mine_session(subject: str, assignment: str, events: list[Event]) -> list[Episode]:
    """Replay one session, run every detector on every state, return its episodes."""
    analyzer = StructuralAnalyzer()
    tracker = EpisodeTracker(subject, assignment)

    def on_state(event: Event, file: str, text: str) -> None:
        tracker.observe(event, file, text, analyzer.analyse(file, text).findings)

    replay_session(subject, assignment, events, on_state=on_state)
    episodes = tracker.finish(events[-1].timestamp if events else 0)

    times = [e.timestamp for e in events]
    runs = [e.timestamp for e in events if e.kind == "run"]
    for ep in episodes:
        lo, hi = bisect.bisect_left(runs, ep.start_ms), bisect.bisect_right(runs, ep.end_ms)
        ep.runs_during = hi - lo
        ep.context = behaviour_context(ep, times, events)
    return episodes


def phase_of(detector: str) -> str:
    return REGISTRY[detector].phase
