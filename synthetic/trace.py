"""Simulated edit traces written as 2021-format ProgSnap2 rows.

A ``Trace`` holds the current text of one file and appends the rows an editor
session would log: each typed character is a ``File.Edit`` Insert followed by
an ``X-Keystroke`` row (as in the 2021 PyPhanon logs), deletions are
``Backspace`` actions, longer selections are one Delete, and a run is a
``Run.Program`` Start row followed by its exit-code row, with the exception
the code would raise recorded for a 2021-format ``runs.csv``. Timing is drawn from
the seed student's own inter-keystroke gaps and long pauses, so the trace
types at that student's speed.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

from replay.progsnap import parses

COLUMNS = [
    "EventID", "SubjectID", "AssignmentID", "CodeStateSection", "EventType", "SourceLocation",
    "EditType", "InsertText", "DeleteText", "X-Metadata", "ClientTimestamp", "ToolInstances",
    "CodeStateID", "X-Compilable",
]  # fmt: skip
TOOL = "synthetic"
# PyCharm (the 2021 editor) inserts the closing bracket or quote as you type the opener,
# then types over it; text stays parseable while a call is being written.
PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
CLOSERS = {")", "]", "}"}


def _balanced(text: str) -> bool:
    stack: list[str] = []
    for ch in text:
        if stack and ch == stack[-1]:
            stack.pop()
        elif ch in PAIRS:
            stack.append(PAIRS[ch])
        elif ch in CLOSERS:
            return False
    return not stack


KEYSTROKE_LAG_MS = 8  # X-Keystroke row follows its File.Edit by a few ms in the 2021 logs
SELECTION_DELETE = 4  # deletions longer than this are one selection delete, not backspaces


@dataclass
class Timing:
    """A student's typing rhythm: gaps between keystrokes and long pauses, in ms."""

    keystroke_gaps: list[int]
    long_pauses: list[int]
    typo_rate: float = 0.0  # chance per letter of a wrong key fixed with backspace

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
    # One entry per run: {"timestamp", "error_type", "exit_code"}; written as runs.csv.
    runs: list[dict] = field(default_factory=list)
    # The exception a run of ``text`` would raise ("" for none); syntax errors are automatic.
    error_for: Callable[[str], str] | None = None

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

    def _key(self, position: int, ch: str) -> None:
        self.t += KEYSTROKE_LAG_MS
        meta = {"\n": "Enter", "\t": "Tab"}.get(ch, ch)
        self._row("X-Keystroke", SourceLocation=f"{position + 1}.0", **{"X-Metadata": meta})

    def type(self, offset: int, text: str) -> None:
        """Type ``text`` at ``offset`` key by key, as the 2021 editor logs it.

        Brackets and quotes are auto-closed and then typed over (only when
        ``text`` is balanced, so the result is exactly ``text``), and letters
        are occasionally mistyped and fixed with backspace, at the student's own
        typo rate.
        """
        autopair = _balanced(text)
        expected: list[str] = []
        pos = offset
        for ch in text:
            self.wait(self.timing.gap(self.rng))
            if autopair and expected and ch == expected[-1]:
                expected.pop()  # type over the auto-inserted closer: no file edit
                self._key(pos, ch)
                pos += 1
                continue
            if ch.isalpha() and self.rng.random() < self.timing.typo_rate:
                wrong = self.rng.choice("asdfghjklqwertyuiopzxcvbnm".replace(ch.lower(), ""))
                self._edit(pos, wrong, "", "Insert")
                self._key(pos, wrong)
                self.wait(self.timing.gap(self.rng))
                self._edit(pos, "", wrong, "Delete")
                self._row("X-Action", **{"X-Metadata": "Backspace"})
                self.wait(self.timing.gap(self.rng))
            self._edit(pos, ch, "", "Insert")
            if autopair and ch in PAIRS:
                self._edit(pos + 1, PAIRS[ch], "", "Insert")  # same instant
                expected.append(PAIRS[ch])
            self._key(pos, ch)
            pos += 1

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
        """A run: Start row, then the exit-code row; the outcome is also kept for runs.csv."""
        self.wait(self.rng.randint(300, 1200))
        start = self.t
        self._row("Run.Program", **{"X-Metadata": "Start"})
        if not parses(self.text):
            error = "SyntaxError"
        else:
            error = self.error_for(self.text) if self.error_for else ""
        exit_code = "1" if error else "0"
        self.runs.append({"timestamp": start, "error_type": error, "exit_code": exit_code})
        self.wait(self.rng.randint(800, 3000))
        self._row("Run.Program", **{"X-Metadata": exit_code})
