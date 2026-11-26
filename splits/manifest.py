"""Student-level train / validation / test split of the 2021 cohort (§7.1).

Students, not events or sessions, are split, so no student's keystrokes reach
more than one split. Students are stratified by grade tier (tertiles of
``FinalScore`` in students.csv, plus a tier for students with no final score)
so each split sees the same range of ability. Within each tier the order is
shuffled with a fixed seed and the split sizes are allocated proportionally,
rounded so the totals hit 70 / 10 / 20 as closely as whole students allow.

The result is frozen in data/splits.json. The 2019 cohort is not split: all of
it is held out for the cross-cohort test (Stage C).
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SPLITS_PATH = ROOT / "data" / "splits.json"

SPLITS = ("train", "validation", "test")
FRACTIONS = {"train": 0.7, "validation": 0.1, "test": 0.2}
SEED = 1400  # CS 1400, the course both cohorts come from
NO_SCORE = "no_final_score"


class LeakageError(AssertionError):
    pass


def grade_tiers(students: pd.DataFrame) -> tuple[dict[str, str], dict[str, list[float]]]:
    """Map SubjectID -> tier name, and tier name -> [min, max] FinalScore."""
    scored = students.dropna(subset=["FinalScore"])
    labels = ["low", "mid", "high"]
    tiers = pd.qcut(scored["FinalScore"], q=3, labels=labels)
    by_subject = dict(zip(scored["SubjectID"], tiers.astype(str), strict=True))
    for sid in students.loc[students["FinalScore"].isna(), "SubjectID"]:
        by_subject[sid] = NO_SCORE
    ranges = {
        label: [float(scored.loc[tiers == label, "FinalScore"].min()),
                float(scored.loc[tiers == label, "FinalScore"].max())]
        for label in labels
    }  # fmt: skip
    return by_subject, ranges


def allocate(sizes: dict[str, int], fractions: dict[str, float]) -> dict[str, dict[str, int]]:
    """Split each stratum's size across splits, proportional and summing to global targets.

    Global targets are ``round(n * fraction)`` for the non-train splits; train
    takes the rest. Each stratum gets the floor of its proportional share, and
    the leftover places go to the strata with the largest remainders (ties by
    name), so the result is deterministic.
    """
    n = sum(sizes.values())
    counts = {s: {k: 0 for k in fractions} for s in sizes}
    for split in [k for k in fractions if k != "train"]:
        target = round(n * fractions[split])
        ideal = {s: sizes[s] * fractions[split] for s in sizes}
        for s in sizes:
            counts[s][split] = math.floor(ideal[s])
        leftover = target - sum(counts[s][split] for s in sizes)
        for s in sorted(sizes, key=lambda s: (-(ideal[s] - math.floor(ideal[s])), s))[:leftover]:
            counts[s][split] += 1
    for s in sizes:
        counts[s]["train"] = sizes[s] - sum(v for k, v in counts[s].items() if k != "train")
        if counts[s]["train"] < 0:
            raise ValueError(f"stratum {s!r} too small for the requested fractions")
    return counts


def build(students: pd.DataFrame, seed: int = SEED, fractions=FRACTIONS) -> dict:
    """Assign every student to exactly one split. Pure function of its inputs."""
    tier_of, ranges = grade_tiers(students)
    strata: dict[str, list[str]] = {}
    for sid in sorted(tier_of):
        strata.setdefault(tier_of[sid], []).append(sid)

    counts = allocate({t: len(ids) for t, ids in strata.items()}, fractions)
    rng = random.Random(seed)
    assignment = {split: [] for split in SPLITS}
    for tier in sorted(strata):
        ids = strata[tier][:]
        rng.shuffle(ids)
        start = 0
        for split in SPLITS:
            take = counts[tier][split]
            assignment[split].extend(ids[start : start + take])
            start += take

    return {
        "cohort": "2021",
        "unit": "SubjectID",
        "seed": seed,
        "fractions": dict(fractions),
        "stratified_by": "FinalScore tertile (students.csv); missing score is its own tier",
        "strata": {
            tier: {
                **({"final_score_range": ranges[tier]} if tier in ranges else {}),
                **counts[tier],
            }
            for tier in sorted(strata)
        },
        "sizes": {split: len(assignment[split]) for split in SPLITS},
        **{split: sorted(assignment[split], key=_natural) for split in SPLITS},
        "held_out_cohorts": {"2019": "all students; cross-cohort test only (Stage C)"},
    }


def _natural(subject: str) -> tuple[str, int]:
    head = subject.rstrip("0123456789")
    tail = subject[len(head) :]
    return head, int(tail) if tail else -1


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_from_raw(raw_dir: Path, seed: int = SEED) -> dict:
    students_csv = raw_dir / "2021" / "students.csv"
    students = pd.read_csv(students_csv)
    keystroke_ids = set(
        pd.read_csv(raw_dir / "2021" / "keystrokes.csv", usecols=["SubjectID"])["SubjectID"]
    )
    if set(students["SubjectID"]) != keystroke_ids:
        raise ValueError("students.csv and keystrokes.csv list different students")
    manifest = build(students, seed)
    manifest["source"] = {"students.csv": {"sha256": sha256(students_csv)}}
    return manifest


# ---------------------------------------------------------------- consumers


def load(path: Path = SPLITS_PATH) -> dict[str, list[str]]:
    """The frozen split: {"train": [...], "validation": [...], "test": [...]}."""
    manifest = json.loads(path.read_text())
    return {split: manifest[split] for split in SPLITS}


def split_of(subject: str, splits: dict[str, list[str]] | None = None) -> str:
    splits = splits or load()
    for split, ids in splits.items():
        if subject in ids:
            return split
    raise KeyError(f"{subject!r} is not in the 2021 split")


def check_disjoint(splits: dict[str, Iterable[str]]) -> None:
    """Raise LeakageError if any student appears in more than one split."""
    seen: dict[str, str] = {}
    for split, ids in splits.items():
        for sid in ids:
            if sid in seen:
                raise LeakageError(f"{sid} is in both {seen[sid]} and {split}")
            seen[sid] = split


def assert_no_leakage(train_subjects: Iterable[str], eval_subjects: Iterable[str]) -> None:
    """Guard for training code: no evaluation student may appear in the training data."""
    overlap = set(train_subjects) & set(eval_subjects)
    if overlap:
        raise LeakageError(f"{len(overlap)} students in both: {sorted(overlap)[:5]}")
