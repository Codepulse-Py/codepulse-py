"""Rebuild file contents from a ProgSnap2 edit log.

Each ``File.Edit`` row deletes ``DeleteText`` and then inserts ``InsertText`` at
``SourceLocation`` (a 0-based character offset). Files start empty, so applying
every edit in logged order reproduces the file at any point in the session.
This is the reconstruction used in the dataset authors' sample notebook.

The recorded ``DeleteText`` is also checked against the text actually present
at that offset. A mismatch is counted but the edit is still applied as logged:
on the 2021 cohort, re-ordering edits to remove mismatches made replayed code
*disagree* more often with the logged ``X-Compilable`` flag (see docs/replay.md).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Edit:
    event_id: int
    offset: int
    insert: str = ""
    delete: str = ""


def fits(text: str, edit: Edit) -> bool:
    """Whether ``edit`` applies to ``text`` exactly as recorded."""
    if edit.offset > len(text):
        return False
    return not edit.delete or text.startswith(edit.delete, edit.offset)


def splice(text: str, edit: Edit) -> str:
    """Apply ``edit``; an offset past the end is clamped to the end."""
    i = min(edit.offset, len(text))
    return text[:i] + edit.insert + text[i + len(edit.delete) :]


@dataclass
class FileState:
    text: str = ""
    edits: int = 0
    mismatches: int = 0
    first_mismatch_event: int | None = None

    @property
    def consistent(self) -> bool:
        """True while every recorded delete matched the replayed text."""
        return self.mismatches == 0

    def apply(self, edit: Edit) -> bool:
        """Apply one edit. Returns whether it matched the replayed text."""
        self.edits += 1
        ok = fits(self.text, edit)
        if not ok:
            self.mismatches += 1
            if self.first_mismatch_event is None:
                self.first_mismatch_event = edit.event_id
        self.text = splice(self.text, edit)
        return ok

    def checkpoint(self, text: str) -> None:
        """Replace the file with a logged full-file snapshot (2019 ``X-Checkpoint``)."""
        self.text = text
