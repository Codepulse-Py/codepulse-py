"""Simulated edit traces written as 2021-format ProgSnap2 rows.

A ``Trace`` holds the current text of one file and appends the rows an editor
session would log: each typed character is a ``File.Edit`` Insert followed by
an ``X-Keystroke`` row (as in the 2021 PyPhanon logs), deletions are
``Backspace`` actions, longer selections are one Delete, and a run is a
``Run.Program`` Start row followed by its exit-code row. Timing is drawn from
the seed student's own inter-keystroke gaps and long pauses, so the trace
types at that student's speed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from replay.progsnap import parses

COLUMNS = [
    "EventID", "SubjectID", "AssignmentID", "CodeStateSection", "EventType", "SourceLocation",
    "EditType", "InsertText", "DeleteText", "X-Metadata", "ClientTimestamp", "ToolInstances",
    "CodeStateID", "X-Compilable",
]  # fmt: skip
TOOL = "synthetic"
KEYSTROKE_LAG_MS = 8  # X-Keystroke row follows its File.Edit by a few ms in the 2021 logs
SELECTION_DELETE = 4  # deletions longer than this are one selection delete, not backspaces


@dataclass
class Timing:
    """A student's typing rhythm: gaps between keystrokes and long pauses, in ms."""

    keystroke_gaps: list[int]
    long_pauses: list[int]

    def gap(self, rng: random.Random) -> int:
        return rng.choice(self.keystroke_gaps) if self.keystroke_gaps else rng.randint(80, 400)

    def pause(self, rng: random.Random) -> int:
        return rng.choice(self.long_pauses) if self.long_pauses else rng.randint(10_000, 40_000)


@dataclass
class Trace:
    subject: str
    assignment: str
    file: str
    text: str
    t: int
    timing: Timing
    rng: random.Random
    rows: list[dict] = field(default_factory=list)

    def _row(self, event_type: str, **values) -> None:
        row = dict.fromkeys(COLUMNS, "")
        row.update(
            SubjectID=self.subject,
            AssignmentID=self.assignment,
            CodeStateSection=self.file,
            EventType=event_type,
            ClientTimestamp=self.t,
            ToolInstances=TOOL,
            **values,
        )
        self.rows.append(row)

    def _edit(self, offset: int, insert: str, delete: str, edit_type: str) -> None:
        assert self.text[offset : offset + len(delete)] == delete
        self.text = self.text[:offset] + insert + self.text[offset + len(delete) :]
        self._row(
            "File.Edit",
            SourceLocation=f"{offset}.0",
            EditType=edit_type,
            InsertText=insert,
            DeleteText=delete,
            **{"X-Compilable": "1" if parses(self.text) else "0"},
        )

    def wait(self, ms: int) -> None:
        self.t += max(0, int(ms))

    def think(self) -> None:
        """A long pause (DEEP_THINKING, > 10 s)."""
        self.wait(self.timing.pause(self.rng))

    def type(self, offset: int, text: str) -> None:
        for i, ch in enumerate(text):
            self.wait(self.timing.gap(self.rng))
            self._edit(offset + i, ch, "", "Insert")
            self.t += KEYSTROKE_LAG_MS
            meta = {"\n": "Enter", "\t": "Tab"}.get(ch, ch)
            self._row("X-Keystroke", SourceLocation=f"{offset + i + 1}.0", **{"X-Metadata": meta})

    def erase(self, offset: int, text: str) -> None:
        if len(text) > SELECTION_DELETE:
            self.wait(self.timing.gap(self.rng) * 3)  # select, then delete
            self._edit(offset, "", text, "Delete")
            return
        for i in reversed(range(len(text))):
            self.wait(self.timing.gap(self.rng))
            self._edit(offset + i, "", text[i], "Delete")
            self._row("X-Action", **{"X-Metadata": "Backspace"})

    def replace(self, offset: int, old: str, new: str) -> None:
        if old:
            self.erase(offset, old)
        if new:
            self.type(offset, new)

    def idle(self) -> None:
        """A cursor move with no edit (a 2021 ``X-Action``)."""
        self.wait(self.timing.gap(self.rng))
        self._row("X-Action", **{"X-Metadata": "Move Cursor"})

    def run(self) -> None:
        self.wait(self.rng.randint(300, 1200))
        self._row("Run.Program", **{"X-Metadata": "Start"})
        self.wait(self.rng.randint(800, 3000))
        exit_code = "0" if parses(self.text) else "1"
        self._row("Run.Program", **{"X-Metadata": exit_code})
