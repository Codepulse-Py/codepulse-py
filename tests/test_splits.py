import json
import re
from pathlib import Path

import pandas as pd
import pytest

from splits.manifest import (
    FRACTIONS,
    SPLITS,
    SPLITS_PATH,
    LeakageError,
    allocate,
    assert_no_leakage,
    build,
    build_from_raw,
    check_disjoint,
    load,
    split_of,
)

RAW_2021 = Path(__file__).resolve().parent.parent / "data" / "raw" / "2021"

# ---------------------------------------------------------------- frozen manifest (runs in CI)


@pytest.fixture(scope="module")
def manifest():
    return json.loads(SPLITS_PATH.read_text())


def test_no_student_in_more_than_one_split(manifest):
    check_disjoint({s: manifest[s] for s in SPLITS})
    for a in SPLITS:
        for b in SPLITS:
            if a < b:
                assert not set(manifest[a]) & set(manifest[b]), (a, b)


def test_every_2021_student_is_assigned_once(manifest):
    everyone = [sid for s in SPLITS for sid in manifest[s]]
    assert len(everyone) == len(set(everyone)) == 44
    assert all(re.fullmatch(r"Student\d+", sid) for sid in everyone)


def test_sizes_are_70_10_20(manifest):
    assert manifest["sizes"] == {s: len(manifest[s]) for s in SPLITS}
    assert manifest["sizes"] == {"train": 31, "validation": 4, "test": 9}


def test_strata_counts_add_up(manifest):
    for split in SPLITS:
        assert sum(t[split] for t in manifest["strata"].values()) == manifest["sizes"][split]
    for tier in ("low", "mid", "high"):
        assert manifest["strata"][tier]["test"] >= 1


def test_load_and_split_of(manifest):
    splits = load()
    assert splits["test"] == manifest["test"]
    assert split_of(manifest["validation"][0], splits) == "validation"
    with pytest.raises(KeyError):
        split_of("S001", splits)  # 2019 students are never in the 2021 split


@pytest.mark.skipif(not (RAW_2021 / "students.csv").exists(), reason="raw data not available")
def test_frozen_manifest_matches_a_fresh_build():
    fresh = build_from_raw(RAW_2021.parent)
    assert json.dumps(fresh, indent=2) + "\n" == SPLITS_PATH.read_text()


# ---------------------------------------------------------------- algorithm


def students(n_scored=30, n_missing=3):
    scores = [50 + i for i in range(n_scored)] + [None] * n_missing
    return pd.DataFrame(
        {"SubjectID": [f"Student{i + 1}" for i in range(len(scores))], "FinalScore": scores}
    )


def test_allocate_hits_global_targets_and_is_proportional():
    counts = allocate({"a": 14, "b": 13, "c": 14, "d": 3}, FRACTIONS)
    totals = {s: sum(c[s] for c in counts.values()) for s in SPLITS}
    assert totals == {"train": 31, "validation": 4, "test": 9}
    assert all(sum(c.values()) == n for c, n in zip(counts.values(), [14, 13, 14, 3], strict=True))


def test_allocate_rejects_impossible_fractions():
    with pytest.raises(ValueError):
        allocate({"a": 1, "b": 1}, {"train": 0.0, "validation": 0.5, "test": 1.0})


def test_build_is_deterministic_and_seed_dependent():
    df = students()
    assert build(df, seed=1) == build(df, seed=1)
    assert build(df, seed=1)["test"] != build(df, seed=2)["test"]


def test_build_ignores_input_row_order():
    df = students()
    assert build(df, seed=7) == build(df.sample(frac=1, random_state=3), seed=7)


def test_build_stratifies_each_tier():
    m = build(students(n_scored=60, n_missing=0), seed=5)
    for tier in ("low", "mid", "high"):
        counts = m["strata"][tier]
        assert counts["test"] == 4 and counts["validation"] == 2 and counts["train"] == 14


def test_leakage_guards():
    with pytest.raises(LeakageError, match="Student2 is in both train and test"):
        check_disjoint({"train": ["Student1", "Student2"], "test": ["Student2"]})
    assert_no_leakage(["Student1"], ["Student2"])
    with pytest.raises(LeakageError):
        assert_no_leakage(["Student1", "Student2"], ["Student2"])
