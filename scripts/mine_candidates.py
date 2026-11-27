"""Mine candidate misconception episodes from every replayed code state (RQ1, #8).

    python scripts/mine_candidates.py              # both cohorts
    python scripts/mine_candidates.py --cohort 2021 --workers 8

Replays every session, runs all seven detectors on every code state, groups
the findings into episodes (see mining/episodes.py) and writes, under
data/interim/rq1/ (git-ignored):

    <cohort>/episodes.parquet   one row per candidate episode, with its ±30 s context
    counts.csv                  episodes, persistent episodes, students per class x cohort
    summary.json                totals, timings and the provisional 50-case gate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from dataclasses import asdict
from multiprocessing import Pool
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from detectors import REGISTRY  # noqa: E402
from mining.episodes import mine_session  # noqa: E402
from replay.progsnap import iter_sessions, load_main_table  # noqa: E402

GATE = 50  # minimum real cases per misconception for the main claims (§3.2.1)


def _work(task):
    warnings.simplefilter("ignore")
    subject, assignment, events = task
    rows = []
    for ep in mine_session(subject, assignment, events):
        row = asdict(ep)
        row.pop("absent_since")
        row.update(row.pop("context"))
        row["duration_s"] = round(ep.duration_ms / 1000, 1)
        row["persistent"] = ep.persistent
        rows.append(row)
    return rows


def mine_cohort(raw_dir: Path, cohort: str, workers: int) -> pd.DataFrame:
    df = load_main_table(raw_dir / cohort / "keystrokes.csv")
    tasks = iter_sessions(df)
    rows = []
    with Pool(workers) as pool:
        for session_rows in pool.imap_unordered(_work, tasks, chunksize=4):
            rows.extend(session_rows)
    episodes = pd.DataFrame(rows)
    episodes.insert(0, "cohort", cohort)
    episodes["phase"] = episodes.detector.map(lambda d: REGISTRY[d].phase)
    return episodes.sort_values(
        ["subject", "assignment", "start_ms", "detector"], ignore_index=True
    )


def counts(episodes: pd.DataFrame) -> pd.DataFrame:
    """Per misconception x cohort: candidate episodes, persistent ones, students, by origin."""
    order = sorted(REGISTRY, key=lambda n: REGISTRY[n].number)
    rows = []
    for name in order:
        for cohort in sorted(episodes.cohort.unique()):
            ep = episodes[(episodes.detector == name) & (episodes.cohort == cohort)]
            persistent = ep[ep.persistent]
            rows.append(
                {
                    "number": REGISTRY[name].number,
                    "misconception": name,
                    "phase": REGISTRY[name].phase,
                    "cohort": cohort,
                    "episodes": len(ep),
                    "persistent": len(persistent),
                    "persistent_typed": int((persistent.origin == "typed").sum()),
                    "persistent_pasted": int((persistent.origin != "typed").sum()),
                    "students": persistent.subject.nunique(),
                    "sessions": persistent.groupby(["subject", "assignment"]).ngroups,
                    "median_duration_s": float(persistent.duration_s.median())
                    if len(persistent)
                    else 0.0,
                }
            )
    return pd.DataFrame(rows)


def gate(table: pd.DataFrame) -> list[dict]:
    """Provisional 50-case gate on persistent candidate episodes across both cohorts.

    Verified cases (#10) can only be fewer than candidates, so a class below the
    gate here is certainly below it after verification.
    """
    out = []
    for name, grp in table.groupby("misconception", sort=False):
        total = int(grp.persistent.sum())
        out.append(
            {
                "misconception": name,
                "persistent_candidates": total,
                "decision": (
                    "below gate: exploratory unless synthetic data (#9, #75) is added"
                    if total < GATE
                    else "provisionally above gate: confirm after verification (#10)"
                ),
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cohort", choices=["2019", "2021"], action="append")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data" / "interim" / "rq1")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = parser.parse_args(argv)

    cohorts = args.cohort or ["2021", "2019"]
    timings, frames = {}, []
    for cohort in cohorts:
        start = time.perf_counter()
        episodes = mine_cohort(args.raw_dir, cohort, args.workers)
        timings[cohort] = round(time.perf_counter() - start, 1)
        out = args.out_dir / cohort
        out.mkdir(parents=True, exist_ok=True)
        episodes.to_parquet(out / "episodes.parquet", index=False)
        frames.append(episodes)
        print(f"{cohort}: {len(episodes)} episodes in {timings[cohort]}s")

    if len(cohorts) < 2:  # combine with the other cohort's earlier run when present
        for other in {"2019", "2021"} - set(cohorts):
            path = args.out_dir / other / "episodes.parquet"
            if path.exists():
                frames.append(pd.read_parquet(path))

    table = counts(pd.concat(frames, ignore_index=True))
    table.to_csv(args.out_dir / "counts.csv", index=False)
    summary = {"seconds": timings, "workers": args.workers, "gate": gate(table)}
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(table.to_string(index=False))
    for g in summary["gate"]:
        print(f"{g['misconception']:<18} {g['persistent_candidates']:>5}  {g['decision']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
