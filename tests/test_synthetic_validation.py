import numpy as np
import pandas as pd
import pytest

from synthetic.validate import (
    AUROC_LIMIT,
    BEHAVIOUR_FEATURES,
    VALIDATION_FEATURES,
    _bh,
    blind_sample,
    cohens_kappa,
    discriminate,
    distribution_check,
    js_divergence,
    real_candidate_windows,
    score_blind,
    synthetic_windows,
)


def frame(n, rng, shift=0.0, prefix="S", students=10):
    data = {f: rng.normal(shift, 1, n) for f in VALIDATION_FEATURES}
    df = pd.DataFrame(data)
    df["subject"] = [f"{prefix}{i % students}" for i in range(n)]
    df["seed_subject"] = df["subject"]
    return df


def test_feature_sets_exclude_flag_derived_and_structure():
    assert "n_flags" not in VALIDATION_FEATURES and "flags_changed" not in VALIDATION_FEATURES
    assert "ast_nodes" not in BEHAVIOUR_FEATURES and "n_edits" in BEHAVIOUR_FEATURES


def test_js_divergence_bounds():
    rng = np.random.default_rng(0)
    a = rng.normal(0, 1, 2000)
    assert js_divergence(a, a) < 1e-9
    assert js_divergence(a, rng.normal(5, 1, 2000)) > 0.8


def test_benjamini_hochberg():
    assert _bh([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.04, 0.04])


def test_distribution_check_flags_only_shifted_features():
    rng = np.random.default_rng(1)
    real = frame(400, rng, prefix="R")
    syn = frame(400, rng, prefix="S")
    syn["n_edits"] += 3
    table = distribution_check(syn, real).set_index("feature")
    assert table.loc["n_edits", "differs"]
    assert table.differs.sum() <= 3  # the rest are the same distribution


def test_discriminator_separates_shifted_data_but_not_identical_data():
    rng = np.random.default_rng(2)
    same = discriminate(frame(300, rng, prefix="S"), frame(300, rng, prefix="R"))
    assert same.passes and abs(same.auroc - 0.5) < 0.1
    shifted = discriminate(frame(300, rng, shift=2, prefix="S"), frame(300, rng, prefix="R"))
    assert not shifted.passes and shifted.auroc > AUROC_LIMIT
    assert shifted.top_features


def test_discriminator_needs_enough_data():
    rng = np.random.default_rng(3)
    assert discriminate(frame(10, rng), frame(300, rng, prefix="R")) is None


def test_comparison_windows_follow_the_flag():
    windows = pd.DataFrame(
        {
            "subject": ["S1"] * 4,
            "assignment": ["A1"] * 4,
            "window_end_ms": [10_000, 40_000, 70_000, 200_000],
        }  # fmt: skip
    )
    episodes = pd.DataFrame(
        {
            "subject": ["S1"],
            "assignment": ["A1"],
            "detector": ["int_division"],
            "start_ms": [5_000],
            "persistent": [True],
        }  # fmt: skip
    )
    real = real_candidate_windows(windows, episodes)
    assert real.window_end_ms.tolist() == [10_000, 40_000]  # within 60 s after the start
    assert real.post.tolist() == [False, True]  # 40 s window starts at 10 s >= 5 s

    manifest = pd.DataFrame(
        {
            "synthetic_id": ["S1"],
            "misconception": ["aliasing"],
            "method": ["m"],
            "seed_subject": ["Student1"],
            "injected_at_ms": [35_000],
        }  # fmt: skip
    )
    syn = synthetic_windows(windows, manifest)
    assert syn.window_end_ms.tolist() == [40_000, 70_000] and syn.post.tolist() == [False, True]


def test_blind_sample_and_scoring():
    rng = np.random.default_rng(4)
    syn = frame(200, rng, prefix="X")
    syn["synthetic_id"] = [f"SYN-{i:04d}" for i in range(200)]
    syn["misconception"] = rng.choice(["aliasing", "self_confusion"], 200)
    syn["assignment"], syn["window_end_ms"] = "A1", range(200)
    real = frame(200, rng, prefix="R")
    real["misconception"] = "int_division"
    real["assignment"], real["window_end_ms"] = [f"A{i}" for i in range(200)], range(200)

    mixed = blind_sample(syn, real)
    assert (mixed.source == "synthetic").sum() == 20 and (mixed.source == "real").sum() == 20
    assert mixed.blind_id.is_unique

    key = mixed[["blind_id", "source", "intended"]]
    perfect = key.assign(label=key.intended.where(key.source == "synthetic", "NONE"))
    result = score_blind(key, perfect)
    assert result["kappa"] == 1.0 and result["passes"]
    wrong = perfect.assign(label="NONE")
    assert not score_blind(key, wrong)["passes"]


def test_cohens_kappa():
    assert cohens_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert cohens_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0
