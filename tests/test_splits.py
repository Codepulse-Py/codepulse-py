import json
import re
from pathlib import Path

import pandas as pd
import pytest

from splits.manifest import (
    EPISODES_PATH,
    FOLDS_PATH,
    K,
    LeakageError,
    all_splits,
    assert_no_leakage,
    build,
    build_from_raw,
    check_disjoint,
    fold_of,
    load_folds,
    split,
)

RAW_2021 = Path(__file__).resolve().parent.parent / "data" / "raw" / "2021"
MAIN_CLASSES = ["indentation_scope", "int_division", "global_local"]

# ---------------------------------------------------------------- frozen manifest (runs in CI)


@pytest.fixture(scope="module")
def manifest():
    return json.loads(FOLDS_PATH.read_text())


def test_five_disjoint_folds_cover_all_44_students(manifest):
    folds = manifest["folds"]
    assert len(folds) == K == 5
    check_disjoint({f"fold {i}": f for i, f in enumerate(folds)})
    everyone = [s for f in folds for s in f]
    assert len(everyone) == len(set(everyone)) == 44
    assert all(re.fullmatch(r"Student\d+", s) for s in everyone)
    assert manifest["sizes"] == [len(f) for f in folds] == [9, 9, 9, 9, 8]


def test_no_student_in_two_parts_of_any_round(manifest):
    for s in all_splits(manifest["folds"]):
        check_disjoint({"train": s.train, "tune": s.tune, "test": s.test})
        assert set(s.train) | set(s.tune) | set(s.test) == {x for f in manifest["folds"] for x in f}
        assert s.tune_fold == (s.test_fold + 1) % K


def test_every_student_is_tested_once_and_tuned_once(manifest):
    rounds = all_splits(manifest["folds"])
    tested = [x for r in rounds for x in r.test]
    tuned = [x for r in rounds for x in r.tune]
    assert sorted(tested) == sorted(set(tested)) and len(tested) == 44
    assert sorted(tuned) == sorted(set(tuned)) and len(tuned) == 44


def test_every_test_fold_has_candidates_of_each_main_class(manifest):
    per_fold = manifest["candidates_per_fold"]
    for c in MAIN_CLASSES + ["self_confusion"]:
        assert all(n > 0 for n in per_fold[c]["episodes"]), c
        assert all(n > 0 for n in per_fold[c]["students"]), c


def test_grade_tiers_are_spread(manifest):
    for tier in ("low", "mid", "high"):
        assert min(manifest["strata"][tier]["per_fold"]) >= 2


def test_split_and_fold_of(manifest):
    folds = load_folds()
    r = split(2, folds)
    assert (r.test_fold, r.tune_fold) == (2, 3) and r.test == manifest["folds"][2]
    assert len(r.train) == 44 - len(r.test) - len(r.tune)
    assert fold_of(r.test[0], folds) == 2
    with pytest.raises(KeyError):
        fold_of("S001", folds)  # 2019 students are never in the 2021 folds
    with pytest.raises(ValueError):
        split(5, folds)


@pytest.mark.skipif(
    not ((RAW_2021 / "students.csv").exists() and EPISODES_PATH.exists()),
    reason="raw data or RQ1 episodes not available",
)
def test_frozen_folds_match_a_fresh_build():
    fresh = build_from_raw(RAW_2021.parent, EPISODES_PATH)
    assert json.dumps(fresh, indent=2) + "\n" == FOLDS_PATH.read_text()


# ---------------------------------------------------------------- algorithm


def students(n_scored=30, n_missing=0):
    scores = [50 + i for i in range(n_scored)] + [None] * n_missing
    return pd.DataFrame(
        {"SubjectID": [f"Student{i + 1}" for i in range(len(scores))], "FinalScore": scores}
    )


def test_build_is_deterministic_seed_dependent_and_order_free():
    df = students()
    assert build(df, seed=1) == build(df, seed=1)
    assert build(df, seed=1)["folds"] != build(df, seed=2)["folds"]
    assert build(df, seed=7) == build(df.sample(frac=1, random_state=3), seed=7)


def test_build_fold_sizes_differ_by_at_most_one():
    assert build(students(n_scored=23, n_missing=3))["sizes"] == [6, 5, 5, 5, 5]


def test_build_spreads_grade_tiers_without_candidates():
    m = build(students(n_scored=30))
    for tier in ("low", "mid", "high"):
        assert m["strata"][tier]["per_fold"] == [2, 2, 2, 2, 2]


def test_rare_label_holders_land_in_different_folds():
    candidates = {f"Student{i}": {"rare": 1} for i in (3, 9, 14, 20, 27)}
    candidates["Student5"] = {"common": 10}
    m = build(students(n_scored=30), candidates)
    assert m["candidates_per_fold"]["rare"]["students"] == [1, 1, 1, 1, 1]


def test_skewed_counts_are_balanced_across_folds():
    # One student holds most episodes of a class; the rest are spread thinly.
    candidates = {"Student1": {"c": 20}} | {f"Student{i}": {"c": 2} for i in range(2, 12)}
    m = build(students(n_scored=30), candidates)
    episodes = m["candidates_per_fold"]["c"]["episodes"]
    assert sum(episodes) == 40 and sorted(episodes)[1] >= 4  # only the big holder's fold stands out


def test_leakage_guards():
    with pytest.raises(LeakageError, match="Student2 is in both train and test"):
        check_disjoint({"train": ["Student1", "Student2"], "test": ["Student2"]})
    assert_no_leakage(["Student1"], ["Student2"])
    with pytest.raises(LeakageError):
        assert_no_leakage(["Student1", "Student2"], ["Student2"])
