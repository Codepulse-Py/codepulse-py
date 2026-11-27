"""Validate synthetic windows against real data (#75, the defence panel's comment).

Final proposal §3.2.1 requires four checks before any synthetic batch is used:

(a) **Distribution check.** Per feature, synthetic vs real windows: the
    two-sample Kolmogorov-Smirnov test (Benjamini-Hochberg corrected) and the
    Jensen-Shannon divergence.
(b) **Discriminator test.** A gradient-boosted classifier tries to tell real
    from synthetic windows under student-grouped cross-validation. A batch is
    rejected if its AUROC exceeds 0.70.
(c) **Blind annotation.** 10% of synthetic windows, mixed with real ones, are
    labelled with the codebook by annotators who do not know which is which
    (``blind_packet`` / ``score_blind``; the labelling itself is done by people).
(d) **With-and-without ablation** of the fusion model, run when it exists (#15).

**Comparison windows.** A synthetic window *covers the injection* when it ends
within 60 s after the misconception was typed in. The real counterpart is a
real 2021 window ending within 60 s after a persistent candidate episode
starts (#8), the same "misconception moment" in real data. Each batch is
compared with two real reference sets:

- ``pooled``: real candidate windows of every class (always available);
- ``same_class``: real candidate windows of the same misconception (only
  where real candidates exist: none for aliasing).

Synthetic windows come in two variants: ``all`` (covering the injection, which
may include real lead-in behaviour) and ``post`` (starting after the
injection, so purely simulated). 2021 only: the synthetic data is built from
2021 and the 2019 editor differs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.spatial.distance import jensenshannon
from scipy.stats import ks_2samp
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold

from features.windows import FEATURE_GROUPS, FEATURES

# Flag-derived features are excluded: synthetic windows carry a flag by construction,
# and on real data alone they separate candidate from other moments (AUROC 0.93).
FLAG_DERIVED = {"n_flags", "flags_changed"}
VALIDATION_FEATURES = [f for f in FEATURES if f not in FLAG_DERIVED]
# Behaviour only: code-size features differ legitimately by misconception class (mutable
# defaults and self need functions and classes), which confounds the pooled comparison.
BEHAVIOUR_FEATURES = [f for f in VALIDATION_FEATURES if f not in FEATURE_GROUPS["structure"]]

AUROC_LIMIT = 0.70  # a batch above this is rejected (§3.2.1 (b))
FOLLOW_MS = 60_000  # windows ending within this long after the flag / injection
WINDOW_MS = 30_000
ALPHA = 0.05
JS_MATERIAL = 0.10  # JS divergence above this counts as a material difference
MAX_REAL_RATIO = 3  # real reference windows sampled up to this multiple of synthetic
SEED = 1400


# ---------------------------------------------------------------- comparison sets


def real_candidate_windows(windows: pd.DataFrame, episodes: pd.DataFrame) -> pd.DataFrame:
    """Real windows ending within FOLLOW_MS after a persistent episode starts.

    Returns the windows with the detector of the episode (a window can appear
    once per detector) and ``post`` = the window starts at or after the episode
    start.
    """
    eps = episodes[episodes.persistent][["subject", "assignment", "detector", "start_ms"]]
    joined = windows.merge(eps, on=["subject", "assignment"])
    end = joined.window_end_ms
    keep = (end > joined.start_ms) & (end <= joined.start_ms + FOLLOW_MS)
    joined = joined[keep].copy()
    joined["post"] = joined.window_end_ms - WINDOW_MS >= joined.start_ms
    joined = joined.sort_values("start_ms").drop_duplicates(
        ["subject", "assignment", "window_end_ms", "detector"]
    )
    return joined.rename(columns={"detector": "misconception"})


def synthetic_windows(windows: pd.DataFrame, manifest: pd.DataFrame) -> pd.DataFrame:
    """Synthetic windows ending within FOLLOW_MS after the injection, with item metadata."""
    meta = manifest[["synthetic_id", "misconception", "method", "seed_subject", "injected_at_ms"]]
    joined = windows.merge(meta, left_on="subject", right_on="synthetic_id")
    end = joined.window_end_ms
    keep = (end > joined.injected_at_ms) & (end <= joined.injected_at_ms + FOLLOW_MS)
    joined = joined[keep].copy()
    joined["post"] = joined.window_end_ms - WINDOW_MS >= joined.injected_at_ms
    return joined


# ---------------------------------------------------------------- (a) distributions


def js_divergence(a: np.ndarray, b: np.ndarray, bins: int = 10) -> float:
    """Jensen-Shannon divergence (base 2, 0..1) on shared quantile bins of the pooled values."""
    pooled = np.concatenate([a, b])
    edges = np.unique(np.quantile(pooled, np.linspace(0, 1, bins + 1)))
    if len(edges) < 2:
        return 0.0
    p = np.histogram(np.clip(a, edges[0], edges[-1]), edges)[0] + 0.5
    q = np.histogram(np.clip(b, edges[0], edges[-1]), edges)[0] + 0.5
    return float(jensenshannon(p / p.sum(), q / q.sum(), base=2) ** 2)


def _bh(pvalues: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values."""
    n = len(pvalues)
    order = sorted(range(n), key=lambda i: pvalues[i])
    adjusted = [1.0] * n
    running = 1.0
    for rank, i in reversed(list(enumerate(order, start=1))):
        running = min(running, pvalues[i] * n / rank)
        adjusted[i] = running
    return adjusted


def distribution_check(
    synthetic: pd.DataFrame, real: pd.DataFrame, features=VALIDATION_FEATURES
) -> pd.DataFrame:
    rows = []
    for f in features:
        a, b = synthetic[f].dropna().to_numpy(float), real[f].dropna().to_numpy(float)
        if len(a) < 5 or len(b) < 5:
            rows.append({"feature": f, "ks": math.nan, "p": math.nan, "js": math.nan})
            continue
        ks = ks_2samp(a, b)
        rows.append(
            {
                "feature": f,
                "ks": float(ks.statistic),
                "p": float(ks.pvalue),
                "js": js_divergence(a, b),
                "synthetic_median": float(np.median(a)),
                "real_median": float(np.median(b)),
                "nan_gap": float(synthetic[f].isna().mean() - real[f].isna().mean()),
            }
        )
    table = pd.DataFrame(rows)
    tested = table.p.notna()
    table.loc[tested, "p_adj"] = _bh(table.loc[tested, "p"].tolist())
    table["differs"] = (table.p_adj < ALPHA) & (table.js > JS_MATERIAL)
    return table.sort_values("js", ascending=False, ignore_index=True)


# ---------------------------------------------------------------- (b) discriminator


@dataclass
class Discrimination:
    auroc: float
    fold_aurocs: list[float]
    n_synthetic: int
    n_real: int
    top_features: list[tuple[str, float]]

    @property
    def passes(self) -> bool:
        return self.auroc <= AUROC_LIMIT


def discriminate(
    synthetic: pd.DataFrame, real: pd.DataFrame, features=VALIDATION_FEATURES, seed: int = SEED
) -> Discrimination | None:
    """Out-of-fold AUROC of a real-vs-synthetic classifier, folds grouped by student.

    Synthetic windows are grouped by their seed student, real ones by their
    student, so a student's real and synthetic windows never sit on opposite
    sides of a split.
    """
    rng = np.random.default_rng(seed)
    if len(real) > MAX_REAL_RATIO * len(synthetic):
        real = real.iloc[rng.choice(len(real), MAX_REAL_RATIO * len(synthetic), replace=False)]
    X = pd.concat([synthetic[features], real[features]], ignore_index=True).astype(float)
    y = np.r_[np.ones(len(synthetic)), np.zeros(len(real))]
    groups = np.r_[synthetic.seed_subject.to_numpy(), real.subject.to_numpy()]
    n_groups_each = min(len(set(synthetic.seed_subject)), len(set(real.subject)))
    if len(synthetic) < 20 or len(real) < 20 or n_groups_each < 3:
        return None
    k = min(5, n_groups_each)
    cv = StratifiedGroupKFold(n_splits=k, shuffle=True, random_state=seed)
    oof = np.full(len(y), np.nan)
    fold_aurocs, importance = [], None
    for i, (tr, te) in enumerate(cv.split(X, y, groups)):
        model = HistGradientBoostingClassifier(max_iter=200, max_leaf_nodes=15, random_state=seed)
        model.fit(X.iloc[tr], y[tr])
        oof[te] = model.predict_proba(X.iloc[te])[:, 1]
        if len(set(y[te])) == 2:
            fold_aurocs.append(float(roc_auc_score(y[te], oof[te])))
        if i == 0 and len(set(y[te])) == 2:
            imp = permutation_importance(
                model, X.iloc[te], y[te], scoring="roc_auc", n_repeats=5, random_state=seed
            )
            importance = sorted(
                zip(features, imp.importances_mean, strict=True), key=lambda t: -t[1]
            )[:5]
    done = ~np.isnan(oof)
    return Discrimination(
        auroc=float(roc_auc_score(y[done], oof[done])),
        fold_aurocs=fold_aurocs,
        n_synthetic=len(synthetic),
        n_real=len(real),
        top_features=[(f, round(float(v), 3)) for f, v in (importance or [])],
    )


# ---------------------------------------------------------------- (c) blind annotation


def blind_sample(
    synthetic: pd.DataFrame, real: pd.DataFrame, share: float = 0.10, seed: int = SEED
) -> pd.DataFrame:
    """10% of synthetic items (one window each) plus as many real candidate windows, shuffled.

    The ``source`` and ``intended`` columns are the answer key: keep them away
    from annotators (``write_blind_packet`` splits them into a separate file).
    """
    rng = np.random.default_rng(seed)
    items = synthetic.drop_duplicates("synthetic_id")
    n = max(1, round(share * items.synthetic_id.nunique()))
    picked_ids = rng.choice(items.synthetic_id.unique(), n, replace=False)
    syn = synthetic[synthetic.synthetic_id.isin(picked_ids)].groupby("synthetic_id").head(1)
    syn = syn.assign(source="synthetic", intended=syn.misconception)
    pool = real.drop_duplicates(["subject", "assignment", "misconception"])
    rl = pool.iloc[rng.choice(len(pool), min(n, len(pool)), replace=False)]
    rl = rl.assign(source="real", intended="")
    mixed = pd.concat([syn, rl], ignore_index=True).sample(frac=1, random_state=seed)
    mixed.insert(0, "blind_id", [f"W{i:03d}" for i in range(1, len(mixed) + 1)])
    return mixed.reset_index(drop=True)


def cohens_kappa(a: list[str], b: list[str]) -> float:
    labels = sorted(set(a) | set(b))
    n = len(a)
    if n == 0:
        return math.nan
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    expected = sum((a.count(c) / n) * (b.count(c) / n) for c in labels)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def score_blind(key: pd.DataFrame, annotations: pd.DataFrame) -> dict:
    """Agreement of annotators' labels with the intended labels on the synthetic windows."""
    merged = key.merge(annotations[["blind_id", "label"]], on="blind_id")
    syn = merged[merged.source == "synthetic"]
    kappa = cohens_kappa(syn.intended.tolist(), syn.label.tolist())
    return {
        "synthetic_windows": len(syn),
        "real_windows": int((merged.source == "real").sum()),
        "accuracy": float((syn.intended == syn.label).mean()) if len(syn) else math.nan,
        "kappa": kappa,
        "passes": bool(kappa >= 0.80),
        "per_class": {c: float((g.intended == g.label).mean()) for c, g in syn.groupby("intended")},
    }
