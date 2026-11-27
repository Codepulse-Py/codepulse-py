"""Validate synthetic windows against real data (#75).

    python scripts/validate_synthetic.py run
    python scripts/validate_synthetic.py score --annotations path/to/labels.csv

``run`` performs checks (a) distributions and (b) the discriminator for every
misconception, injection method and comparison set. It also writes the
blinded annotation packet for check (c). Outputs go to
data/interim/synthetic_validation/ (git-ignored):

    report.json          (a) + (b) summary and pass / fail per batch
    distribution.csv     (a) per feature: KS, adjusted p, JS divergence, medians
    blind_packet.csv     (c) for annotators: code + behaviour, no source column
    blind_key.csv        (c) answer key: keep it away from annotators

``score`` reads annotators' labels (columns ``blind_id``, ``label``, using the
codebook labels or NONE) and reports kappa against the intended labels.

Needs: features for 2021 and synthetic (scripts/extract_features.py), the RQ1
episodes (scripts/mine_candidates.py --cohort 2021) and the synthetic set.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from replay.progsnap import iter_sessions, load_main_table, replay_session  # noqa: E402
from synthetic.validate import (  # noqa: E402
    AUROC_LIMIT,
    BEHAVIOUR_FEATURES,
    VALIDATION_FEATURES,
    blind_sample,
    discriminate,
    distribution_check,
    real_candidate_windows,
    score_blind,
    synthetic_windows,
)

INTERIM = ROOT / "data" / "interim"
OUT = INTERIM / "synthetic_validation"
SUMMARY_FEATURES = [
    "n_edits", "chars_inserted", "chars_deleted", "deletion_ratio", "longest_gap_s",
    "pauses_over_10s", "reversal_cycles", "n_runs", "run_errors", "err_type", "err_syntax",
    "state_typing_s", "state_pause_s", "state_deep_thinking_s", "state_flailing_s",
]  # fmt: skip


def load():
    real_w = pd.read_parquet(INTERIM / "features" / "2021" / "windows.parquet")
    syn_w = pd.read_parquet(INTERIM / "features" / "synthetic" / "windows.parquet")
    episodes = pd.read_parquet(INTERIM / "rq1" / "2021" / "episodes.parquet")
    manifest = pd.read_csv(INTERIM / "synthetic" / "manifest.csv")
    return real_candidate_windows(real_w, episodes), synthetic_windows(syn_w, manifest)


def batches(syn: pd.DataFrame):
    """(name, synthetic windows): each class, and each method within a class."""
    for c, g in syn.groupby("misconception"):
        yield c, "all methods", g
        if g.method.nunique() > 1:
            for m, gm in g.groupby("method"):
                yield c, m, gm


def run() -> int:
    warnings.simplefilter("ignore")
    real, syn = load()
    report, dist_rows = [], []
    for c, method, g in batches(syn):
        refs = {"pooled": real}
        same = real[real.misconception == c]
        if len(same):
            refs["same_class"] = same
        for ref_name, ref in refs.items():
            for variant in ("all", "post"):
                s = g if variant == "all" else g[g.post]
                r = ref.drop_duplicates(["subject", "assignment", "window_end_ms"])
                r = r if variant == "all" else r[r.post]
                d = discriminate(s, r, VALIDATION_FEATURES)
                db = discriminate(s, r, BEHAVIOUR_FEATURES)
                entry = {
                    "misconception": c, "method": method, "reference": ref_name,
                    "variant": variant, "synthetic_windows": len(s), "real_windows": len(r),
                    "auroc": round(d.auroc, 3) if d else None,
                    "auroc_behaviour_only": round(db.auroc, 3) if db else None,
                    "fold_aurocs": [round(x, 3) for x in d.fold_aurocs] if d else [],
                    "passes": d.passes if d else None,
                    "passes_behaviour_only": db.passes if db else None,
                    "top_features": d.top_features if d else [],
                    "top_features_behaviour_only": db.top_features if db else [],
                }  # fmt: skip
                if len(s) >= 5 and len(r) >= 5:
                    dist = distribution_check(s, r)
                    entry["features_differing"] = dist[dist.differs].feature.tolist()
                    dist_rows.append(dist.assign(misconception=c, method=method,
                                                 reference=ref_name, variant=variant))  # fmt: skip
                report.append(entry)
                n_diff = len(entry.get("features_differing", []))
                sizes = f"n={len(s):4}/{len(r):5}"
                print(f"{c:17} {method:18} {ref_name:10} {variant:4} {sizes} "
                      f"AUROC={entry['auroc']} behaviour-only={entry['auroc_behaviour_only']} "
                    f"differing={n_diff}")  # fmt: skip

    OUT.mkdir(parents=True, exist_ok=True)
    pd.concat(dist_rows, ignore_index=True).to_csv(OUT / "distribution.csv", index=False)
    primary = [e for e in report if e["method"] == "all methods" and e["reference"] == "pooled"
               and e["variant"] == "all"]  # fmt: skip
    summary = {
        "auroc_limit": AUROC_LIMIT,
        "generator": str(pd.read_csv(INTERIM / "synthetic" / "manifest.csv").generator.iloc[0]),
        "baselines": baselines(),
        "primary": {
            e["misconception"]: {
                "auroc": e["auroc"],
                "auroc_behaviour_only": e["auroc_behaviour_only"],
                "passes": e["passes"],
                "passes_behaviour_only": e["passes_behaviour_only"],
            }
            for e in primary
        },
        "batches": report,
    }
    (OUT / "report.json").write_text(json.dumps(summary, indent=2) + "\n")
    write_blind_packet(real, syn)
    return 0


def baselines() -> dict:
    """What the same discriminator does on real data only, to read the AUROCs against."""
    import numpy as np

    w = pd.read_parquet(INTERIM / "features" / "2021" / "windows.parquet")
    ep = pd.read_parquet(INTERIM / "rq1" / "2021" / "episodes.parquet")
    cand = real_candidate_windows(w, ep).drop_duplicates(["subject", "assignment", "window_end_ms"])
    rest = w.merge(cand[["subject", "assignment", "window_end_ms"]], how="left", indicator=True)
    rest = rest[rest._merge == "left_only"].drop(columns="_merge")
    rng = np.random.default_rng(0)
    rest = rest.iloc[rng.choice(len(rest), len(cand), replace=False)]
    a = w.iloc[rng.choice(len(w), 1500, replace=False)]
    b = w.iloc[rng.choice(len(w), 1500, replace=False)]
    out = {}
    for name, (x, y) in {
        "candidate vs other real moments": (rest, cand),
        "random real vs random real": (a, b),
    }.items():
        x = x.assign(seed_subject=x.subject)
        out[name] = {
            "auroc": round(discriminate(x, y, VALIDATION_FEATURES).auroc, 3),
            "auroc_behaviour_only": round(discriminate(x, y, BEHAVIOUR_FEATURES).auroc, 3),
        }
    return out


def _code_at(source: Path, wanted: pd.DataFrame) -> dict:
    """(subject, assignment, window_end_ms) -> focus file text at the window end."""
    keys = set(zip(wanted.subject, wanted.assignment, strict=True))
    out = {}
    df = load_main_table(source / "keystrokes.csv")
    df = df[[(s, a) in keys for s, a in zip(df.subject, df.assignment, strict=True)]]
    for s, a, events in iter_sessions(df):
        for row in wanted[(wanted.subject == s) & (wanted.assignment == a)].itertuples():
            before = [e for e in events if e.timestamp <= row.window_end_ms]
            files = replay_session(s, a, before).files
            out[(s, a, row.window_end_ms)] = (
                files[row.focus_file].text if row.focus_file in files else ""
            )
    return out


def write_blind_packet(real: pd.DataFrame, syn: pd.DataFrame) -> None:
    sample = blind_sample(syn, real)
    code = {}
    code.update(_code_at(INTERIM / "synthetic", sample[sample.source == "synthetic"]))
    code.update(_code_at(ROOT / "data" / "raw" / "2021", sample[sample.source == "real"]))
    packet = pd.DataFrame(
        {
            "blind_id": sample.blind_id,
            "file": sample.focus_file,
            "code_at_window_end": [
                code.get((r.subject, r.assignment, r.window_end_ms), "")
                for r in sample.itertuples()
            ],
            "behaviour_last_30s": [
                "; ".join(
                    f"{f}={getattr(r, f):.3g}" for f in SUMMARY_FEATURES if pd.notna(getattr(r, f))
                )
                for r in sample.itertuples()
            ],
            "label": "",  # annotator fills: a misconception name from the codebook, or NONE
        }
    )
    key = sample[["blind_id", "source", "intended", "subject", "assignment", "window_end_ms"]]
    packet.to_csv(OUT / "blind_packet.csv", index=False)
    key.to_csv(OUT / "blind_key.csv", index=False)
    print(f"blind packet: {len(packet)} windows ({(sample.source == 'synthetic').sum()} synthetic)")


def score(path: Path) -> int:
    result = score_blind(pd.read_csv(OUT / "blind_key.csv", keep_default_na=False),
                         pd.read_csv(path, keep_default_na=False))  # fmt: skip
    print(json.dumps(result, indent=2))
    return 0 if result["passes"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    s = sub.add_parser("score")
    s.add_argument("--annotations", type=Path, required=True)
    args = parser.parse_args(argv)
    return run() if args.command == "run" else score(args.annotations)


if __name__ == "__main__":
    sys.exit(main())
