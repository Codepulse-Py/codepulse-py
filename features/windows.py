"""Algorithm 2: sliding-window behavioural and structural features (issue #7).

Windows follow eq. 3.1 of the final proposal: ``W_k = (t_k - 30 s, t_k]`` with
``t_k = t_0 + 10 s * k``, where ``t_0`` is the session's first activity. Only
windows that contain at least one edit or run are kept; a session spread over
several days otherwise produces thousands of empty windows.

Every feature is computable from what both cohorts log *and* what the live
editor (#21) sends: edits (offset, inserted and deleted text), run starts with
their outcome, and the reconstructed code (Table 3.2). Nothing depends on raw
key codes, so features carry over from PyCharm to the browser editor.

The seven detector flags at the window end (``flag_*``) are the structural
vector ``a_k``; ``FEATURES`` lists the behavioural / structural vector ``b_k``.
"""

from __future__ import annotations

import bisect
import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass

from detectors import REGISTRY
from detectors.analyzer import parse, run_detectors
from features.states import PASTE_CHARS, STATES, activity, label
from replay.engine import FileState
from replay.progsnap import Event

WINDOW_MS = 30_000
STRIDE_MS = 10_000
JUMP_LARGE = 80  # characters; roughly a line or more away
REVERSAL_REGION = 10

ERROR_GROUPS = {
    "err_syntax": {"SyntaxError", "IndentationError", "TabError"},
    "err_name": {"NameError"},
    "err_unbound_local": {"UnboundLocalError"},
    "err_type": {"TypeError"},
    "err_attribute": {"AttributeError"},
    "err_index_key": {"IndexError", "KeyError"},
    "err_value": {"ValueError"},
}

FEATURE_GROUPS = {
    "timing": [
        "n_edits", "iei_mean_s", "iei_median_s", "iei_std_s", "longest_gap_s",
        "pauses_2_10s", "pauses_over_10s", "secs_since_last_edit",
    ],
    "editing": [
        "n_inserts", "n_deletes", "n_replaces", "chars_inserted", "chars_deleted",
        "deletion_ratio", "net_chars", "edit_churn", "paste_count", "paste_chars",
        "reversal_cycles",
    ],
    "locality": ["jump_mean", "jump_max", "large_jumps", "lines_touched", "files_touched"],
    "states": [f"state_{s.lower()}_s" for s in STATES],
    "structure": [
        "parses", "unparseable_share", "ast_nodes", "n_functions", "n_classes",
        "n_loops", "n_branches", "n_flags", "flags_changed",
    ],
    "execution": [
        "n_runs", "secs_since_last_run", "run_errors", "runs_terminated",
        *ERROR_GROUPS, "err_other",
    ],
}  # fmt: skip
FEATURES = [f for group in FEATURE_GROUPS.values() for f in group]
FLAGS = [f"flag_{name}" for name in sorted(REGISTRY, key=lambda n: REGISTRY[n].number)]


@dataclass(frozen=True, slots=True)
class RunOutcome:
    errored: bool
    terminated: bool
    error_type: str
    end_ms: int | None = None


def window_ends(acts: list[Event]) -> list[int]:
    """Ends of every 30 s / 10 s window that contains at least one activity."""
    if not acts:
        return []
    t0 = acts[0].timestamp
    ks: set[int] = set()
    for e in acts:
        first = max(1, math.ceil((e.timestamp - t0) / STRIDE_MS))
        last = (e.timestamp - t0 + WINDOW_MS - 1) // STRIDE_MS
        ks.update(range(first, last + 1))
    return [t0 + k * STRIDE_MS for k in sorted(ks)]


def _structure(tree) -> dict[str, int]:
    import ast

    counts = {"ast_nodes": 0, "n_functions": 0, "n_classes": 0, "n_loops": 0, "n_branches": 0}
    for node in ast.walk(tree):
        counts["ast_nodes"] += 1
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            counts["n_functions"] += 1
        elif isinstance(node, ast.ClassDef):
            counts["n_classes"] += 1
        elif isinstance(node, ast.For | ast.While | ast.AsyncFor):
            counts["n_loops"] += 1
        elif isinstance(node, ast.If | ast.IfExp):
            counts["n_branches"] += 1
    return counts


def _error_group(error_type: str) -> str | None:
    if not error_type:
        return None
    for group, names in ERROR_GROUPS.items():
        if error_type in names:
            return group
    return "err_other"


def session_windows(
    subject: str,
    assignment: str,
    events: list[Event],
    runs: dict[int, RunOutcome] | None = None,
) -> list[dict]:
    """One feature row per active window of a session (events in replay order)."""
    runs = runs or {}
    acts = activity(events)
    if not acts:
        return []
    intervals = label(events, {t: r.end_ms for t, r in runs.items() if r.end_ms is not None})
    i_start = [iv.start_ms for iv in intervals]
    i_end = [iv.end_ms for iv in intervals]
    ts = [e.timestamp for e in acts]

    # Line number of every edit, from the text just before it is applied.
    files: dict[str, FileState] = {}
    line_of: dict[int, int] = {}
    ends = window_ends(acts)
    snapshots: dict[int, tuple[str, str] | None] = {}  # window end -> (focus file, text)
    focus = None
    e_iter = iter(events)
    pending = next(e_iter, None)
    for end in ends:
        while pending is not None and pending.timestamp <= end:
            e = pending
            if e.kind == "edit":
                f = files.setdefault(e.file, FileState())
                off = min(e.edit.offset, len(f.text))
                line_of[id(e)] = f.text.count("\n", 0, off) + 1
                f.apply(e.edit)
                focus = e.file
            elif e.kind == "checkpoint":
                files.setdefault(e.file, FileState()).checkpoint(e.checkpoint)
            pending = next(e_iter, None)
        snapshots[end] = (focus, files[focus].text) if focus is not None else None

    rows = []
    last_good: dict[str, tuple[dict, set]] = {}
    cache: tuple[str, str, dict] | None = None
    prev_flags: set[str] = set()
    for end in ends:
        a, b = end - WINDOW_MS, end
        lo, hi = bisect.bisect_right(ts, a), bisect.bisect_right(ts, b)
        win = acts[lo:hi]
        edits = [e for e in win if e.kind == "edit"]
        run_events = [e for e in win if e.kind == "run"]
        row: dict = {"subject": subject, "assignment": assignment, "window_end_ms": end}

        # ---- timing
        et = [e.timestamp for e in edits]
        iei = [(y - x) / 1000 for x, y in zip(et, et[1:], strict=False)]
        stamps = [a, *[e.timestamp for e in win], b]
        prev_edit = next(
            (acts[j].timestamp for j in range(hi - 1, -1, -1) if acts[j].kind == "edit"), None
        )
        j0, j1 = bisect.bisect_right(i_end, a), bisect.bisect_left(i_start, b)
        ending_here = [iv for iv in intervals[j0:j1] if a < iv.end_ms <= b]
        gaps = [(iv.end_ms - iv.start_ms) for iv in ending_here]
        row.update(
            n_edits=len(edits),
            iei_mean_s=statistics.fmean(iei) if iei else math.nan,
            iei_median_s=statistics.median(iei) if iei else math.nan,
            iei_std_s=statistics.pstdev(iei) if len(iei) > 1 else math.nan,
            longest_gap_s=max(y - x for x, y in zip(stamps, stamps[1:], strict=False)) / 1000,
            pauses_2_10s=sum(2_000 <= g < 10_000 for g in gaps),
            pauses_over_10s=sum(g >= 10_000 for g in gaps),
            secs_since_last_edit=(b - prev_edit) / 1000 if prev_edit is not None else math.nan,
        )

        # ---- editing
        ins = [len(e.edit.insert) for e in edits]
        dels = [len(e.edit.delete) for e in edits]
        kinds = [
            "R" if e.edit.insert and e.edit.delete else "I" if e.edit.insert else "D" for e in edits
        ]
        ci, cd = sum(ins), sum(dels)
        reversals = sum(
            1
            for p, q, kp, kq in zip(edits, edits[1:], kinds, kinds[1:], strict=False)
            if p.file == q.file and {kp, kq} == {"I", "D"}
            and abs(p.edit.offset - q.edit.offset) <= REVERSAL_REGION
        )  # fmt: skip
        row.update(
            n_inserts=kinds.count("I"),
            n_deletes=kinds.count("D"),
            n_replaces=kinds.count("R"),
            chars_inserted=ci,
            chars_deleted=cd,
            deletion_ratio=cd / (ci + cd) if ci + cd else math.nan,
            net_chars=ci - cd,
            edit_churn=(ci + cd) / max(1, abs(ci - cd)),
            paste_count=sum(n > PASTE_CHARS for n in ins),
            paste_chars=sum(n for n in ins if n > PASTE_CHARS),
            reversal_cycles=reversals,
        )

        # ---- locality: distance between consecutive edit positions in one file
        jumps = [
            abs(q.edit.offset - p.edit.offset)
            for p, q in zip(edits, edits[1:], strict=False)
            if p.file == q.file
        ]
        row.update(
            jump_mean=statistics.fmean(jumps) if jumps else math.nan,
            jump_max=max(jumps) if jumps else math.nan,
            large_jumps=sum(j > JUMP_LARGE for j in jumps),
            lines_touched=len({(e.file, line_of[id(e)]) for e in edits}),
            files_touched=len({e.file for e in edits}),
        )

        # ---- time in each behavioural state (interval overlap with the window)
        durations = dict.fromkeys(STATES, 0)
        for iv in intervals[j0:j1]:
            overlap = min(iv.end_ms, b) - max(iv.start_ms, a)
            if overlap > 0:
                durations[iv.state] += overlap
        row.update({f"state_{s.lower()}_s": durations[s] / 1000 for s in STATES})

        # ---- structure of the focus file at the window end
        snap = snapshots[end]
        flags: set[str] = set()
        struct = dict.fromkeys(FEATURE_GROUPS["structure"][2:7], math.nan)
        parses = math.nan
        if snap is not None:
            file, text = snap
            if cache is not None and cache[0] == file and cache[1] is text:
                parses, struct, flags = cache[2]["parses"], cache[2]["struct"], cache[2]["flags"]
            else:
                tree, _ = parse(text)
                if tree is not None:
                    parses = 1
                    struct = _structure(tree)
                    flags = {f.detector for f in run_detectors(tree, text)}
                    last_good[file] = (struct, flags)
                else:
                    parses = 0
                    struct, flags = last_good.get(file, (struct, set()))
                cache = (file, text, {"parses": parses, "struct": struct, "flags": flags})
        known = [e.compilable for e in edits if e.compilable is not None]
        row.update(
            parses=parses,
            unparseable_share=(known.count(False) / len(known)) if known else math.nan,
        )
        row.update(struct)
        row.update(n_flags=len(flags), flags_changed=len(flags ^ prev_flags))
        row.update({f"flag_{name}": int(name in flags) for name in REGISTRY})
        prev_flags = flags
        row["focus_file"] = snap[0] if snap else ""

        # ---- execution
        last_run = next(
            (acts[j].timestamp for j in range(hi - 1, -1, -1) if acts[j].kind == "run"), None
        )
        outcomes = [runs.get(e.timestamp) for e in run_events]
        errs = dict.fromkeys([*ERROR_GROUPS, "err_other"], 0)
        for o in outcomes:
            group = _error_group(o.error_type) if o and o.errored else None
            if group:
                errs[group] += 1
        row.update(
            n_runs=len(run_events),
            secs_since_last_run=(b - last_run) / 1000 if last_run is not None else math.nan,
            run_errors=sum(1 for o in outcomes if o and o.errored),
            runs_terminated=sum(1 for o in outcomes if o and o.terminated),
            **errs,
        )
        rows.append(row)
    return rows


def columns() -> list[str]:
    return ["subject", "assignment", "window_end_ms", "focus_file", *FEATURES, *FLAGS]


def order(rows: Iterable[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (r["subject"], r["assignment"], r["window_end_ms"]))
