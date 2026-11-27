"""Student-grouped five-fold cross-validation of the 2021 cohort (final proposal §3.2.4).

With 44 students, a single train / validation / test split leaves too few test
students for stable per-class results, so every student is tested exactly
once instead:

- Students, not events or sessions, are assigned to folds, so no student's
  keystrokes reach both training and testing.
- Folds are stratified by grade tier (tertiles of ``FinalScore`` in
  students.csv, plus a tier for students with no final score) **and** by each
  student's candidate misconception episodes (RQ1, #8), so every test fold
  holds cases of every class that has them. Many episodes come from a handful
  of students, and grade-tier stratification alone left one fold with a single
  global-vs-local student. Students are placed one at a time, those holding
  the largest share of the rarest classes first, each into the fold that keeps
  the per-class and per-tier counts most even (iterative stratification,
  Sechidis et al., 2011). This uses candidate counts, not verified labels or
  any model output, and is fixed before any modelling.
- For test fold *k*, fold *k + 1* (mod 5) is held back for threshold tuning
  (#17) and the other three folds are the training set. Each student is
  therefore tested once and used for tuning once.

The result is frozen in data/folds.json. The 2019 cohort is not split: all of
it is held out for the cross-cohort test (Stage C).
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FOLDS_PATH = ROOT / "data" / "folds.json"
EPISODES_PATH = ROOT / "data" / "interim" / "rq1" / "2021" / "episodes.parquet"

K = 5
SEED = 1400  # CS 1400, the course both cohorts come from
NO_SCORE = "no_final_score"


class LeakageError(AssertionError):
    pass


@dataclass(frozen=True)
class Split:
    """The students of one cross-validation round."""

    test_fold: int
    tune_fold: int
    train: list[str]
    tune: list[str]
    test: list[str]


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


def _natural(subject: str) -> tuple[str, int]:
    head = subject.rstrip("0123456789")
    tail = subject[len(head) :]
    return head, int(tail) if tail else -1


def build(
    students: pd.DataFrame,
    candidates: dict[str, dict[str, int]] | None = None,
    k: int = K,
    seed: int = SEED,
) -> dict:
    """Assign every student to one of ``k`` folds. Pure function of its inputs.

    ``candidates`` maps SubjectID -> {misconception: persistent candidate
    episodes}. Fold sizes differ by at most one.
    """
    tier_of, ranges = grade_tiers(students)
    candidates = candidates or {}
    classes = sorted({c for counts in candidates.values() for c in counts})
    tiers = sorted(set(tier_of.values()), key=lambda t: (t == NO_SCORE, t))
    subjects = sorted(tier_of, key=_natural)

    # One row per student: candidate counts per class, then a one-hot grade tier.
    def vector(sid):
        counts = candidates.get(sid, {})
        return [counts.get(c, 0) for c in classes] + [int(tier_of[sid] == t) for t in tiers]

    vectors = {sid: vector(sid) for sid in subjects}
    totals = [sum(v[i] for v in vectors.values()) for i in range(len(classes) + len(tiers))]
    targets = [t / k for t in totals]
    weights = [1 / t**2 if t else 0.0 for t in totals]  # each dimension counts equally

    rng = random.Random(seed)
    order = subjects[:]
    rng.shuffle(order)  # random tie-break, then rarest-share students first
    share = {sid: sum(v / t for v, t in zip(vectors[sid], totals, strict=True) if t)
             for sid in subjects}  # fmt: skip
    order.sort(key=lambda sid: -share[sid])

    capacity = [len(subjects) // k + (i < len(subjects) % k) for i in range(k)]
    folds: list[list[str]] = [[] for _ in range(k)]
    sums = [[0] * len(totals) for _ in range(k)]
    for sid in order:
        best, best_cost = None, None
        for f in range(k):
            if len(folds[f]) >= capacity[f]:
                continue
            cost = sum(
                w
                * (
                    (sums[f][i] + vectors[sid][i] - targets[i]) ** 2
                    - (sums[f][i] - targets[i]) ** 2
                )
                for i, w in enumerate(weights)
            )
            if best_cost is None or cost < best_cost - 1e-12:
                best, best_cost = f, cost
        folds[best].append(sid)
        sums[best] = [a + b for a, b in zip(sums[best], vectors[sid], strict=True)]

    return {
        "cohort": "2021",
        "unit": "SubjectID",
        "k": k,
        "seed": seed,
        "stratified_by": [
            "FinalScore tertile (students.csv); missing score is its own tier",
            "persistent candidate episodes per misconception (data/interim/rq1, #8)",
        ],
        "rounds": "test fold k; tune fold (k + 1) mod K; train = the other K - 2 folds",
        "strata": {
            tier: {
                **({"final_score_range": ranges[tier]} if tier in ranges else {}),
                "per_fold": [sum(tier_of[s] == tier for s in f) for f in folds],
            }
            for tier in tiers
        },
        "candidates_per_fold": {
            c: {
                "episodes": [sum(candidates.get(s, {}).get(c, 0) for s in f) for f in folds],
                "students": [sum(candidates.get(s, {}).get(c, 0) > 0 for s in f) for f in folds],
            }
            for c in classes
        },
        "sizes": [len(f) for f in folds],
        "folds": [sorted(f, key=_natural) for f in folds],
        "held_out_cohorts": {"2019": "all students; cross-cohort test only (Stage C)"},
    }


def candidate_counts(episodes_path: Path) -> dict[str, dict[str, int]]:
    """SubjectID -> {misconception: persistent candidate episodes} from the RQ1 miner."""
    episodes = pd.read_parquet(episodes_path)
    persistent = episodes[episodes.persistent]
    counts: dict[str, dict[str, int]] = {}
    for (sid, detector), n in persistent.groupby(["subject", "detector"]).size().items():
        counts.setdefault(sid, {})[detector] = int(n)
    return counts


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_from_raw(raw_dir: Path, episodes_path: Path, k: int = K, seed: int = SEED) -> dict:
    students_csv = raw_dir / "2021" / "students.csv"
    students = pd.read_csv(students_csv)
    keystroke_ids = set(
        pd.read_csv(raw_dir / "2021" / "keystrokes.csv", usecols=["SubjectID"])["SubjectID"]
    )
    if set(students["SubjectID"]) != keystroke_ids:
        raise ValueError("students.csv and keystrokes.csv list different students")
    candidates = candidate_counts(episodes_path)
    manifest = build(students, candidates, k, seed)
    digest = hashlib.sha256(json.dumps(candidates, sort_keys=True).encode()).hexdigest()
    manifest["source"] = {
        "students.csv": {"sha256": sha256(students_csv)},
        "candidate counts": {"sha256": digest, "from": "data/interim/rq1/2021/episodes.parquet"},
    }
    return manifest


# ---------------------------------------------------------------- consumers


def load_folds(path: Path = FOLDS_PATH) -> list[list[str]]:
    """The frozen folds: a list of K student lists."""
    return json.loads(path.read_text())["folds"]


def split(test_fold: int, folds: list[list[str]] | None = None) -> Split:
    """Train / tune / test students for one cross-validation round."""
    folds = folds or load_folds()
    k = len(folds)
    if not 0 <= test_fold < k:
        raise ValueError(f"test_fold must be in 0..{k - 1}")
    tune_fold = (test_fold + 1) % k
    train = [s for i, f in enumerate(folds) if i not in (test_fold, tune_fold) for s in f]
    return Split(
        test_fold, tune_fold, sorted(train, key=_natural), folds[tune_fold], folds[test_fold]
    )


def all_splits(folds: list[list[str]] | None = None) -> list[Split]:
    folds = folds or load_folds()
    return [split(i, folds) for i in range(len(folds))]


def fold_of(subject: str, folds: list[list[str]] | None = None) -> int:
    folds = folds or load_folds()
    for i, f in enumerate(folds):
        if subject in f:
            return i
    raise KeyError(f"{subject!r} is not in the 2021 folds")


def check_disjoint(groups: dict[str, Iterable[str]]) -> None:
    """Raise LeakageError if any student appears in more than one group."""
    seen: dict[str, str] = {}
    for name, ids in groups.items():
        for sid in ids:
            if sid in seen:
                raise LeakageError(f"{sid} is in both {seen[sid]} and {name}")
            seen[sid] = name


def assert_no_leakage(train_subjects: Iterable[str], eval_subjects: Iterable[str]) -> None:
    """Guard for training code: no evaluation student may appear in the training data."""
    overlap = set(train_subjects) & set(eval_subjects)
    if overlap:
        raise LeakageError(f"{len(overlap)} students in both: {sorted(overlap)[:5]}")
