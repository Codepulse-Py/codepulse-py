"""Extract 30 s / 10 s window features for a cohort (Algorithm 2, #7).

    python scripts/extract_features.py                     # 2021 and 2019
    python scripts/extract_features.py --cohort synthetic  # the #9 synthetic windows

Writes data/interim/features/<cohort>/windows.parquet (one row per active
window) and summary.json. Synthetic sessions are in the 2021 format, so they
go through exactly the same code as the real cohorts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from multiprocessing import Pool
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from features.run_outcomes import load_run_outcomes  # noqa: E402
from features.windows import (  # noqa: E402
    FEATURE_GROUPS,
    FEATURES,
    FLAGS,
    RunOutcome,
    columns,
    session_windows,
)
from replay.progsnap import iter_sessions, load_main_table  # noqa: E402

SOURCES = {
    "2021": (ROOT / "data" / "raw" / "2021", "2021"),
    "2019": (ROOT / "data" / "raw" / "2019", "2019"),
    "synthetic": (ROOT / "data" / "interim" / "synthetic", "2021"),  # 2021 log format
}


def _work(task):
    warnings.simplefilter("ignore")
    subject, assignment, events, runs = task
    return session_windows(subject, assignment, events, runs)


def extract(cohort: str, workers: int) -> tuple[pd.DataFrame, dict]:
    source, log_format = SOURCES[cohort]
    start = time.perf_counter()
    outcomes = load_run_outcomes(source, log_format)
    by_session: dict[tuple[str, str], dict[int, RunOutcome]] = {}
    for r in outcomes.itertuples(index=False):
        end = None if pd.isna(r.end_ms) else int(r.end_ms)
        by_session.setdefault((r.subject, r.assignment), {})[int(r.timestamp)] = RunOutcome(
            bool(r.errored), bool(r.terminated), r.error_type, end
        )
    df = load_main_table(source / "keystrokes.csv")
    tasks = ((s, a, events, by_session.get((s, a), {})) for s, a, events in iter_sessions(df))
    rows = []
    with Pool(workers) as pool:
        for session_rows in pool.imap_unordered(_work, tasks, chunksize=2):
            rows.extend(session_rows)
    windows = pd.DataFrame(rows, columns=columns())
    windows = windows.sort_values(["subject", "assignment", "window_end_ms"], ignore_index=True)
    windows.insert(0, "cohort", cohort)
    summary = {
        "cohort": cohort,
        "windows": len(windows),
        "sessions": int(windows.groupby(["subject", "assignment"]).ngroups) if len(windows) else 0,
        "features": len(FEATURES),
        "feature_groups": {g: len(f) for g, f in FEATURE_GROUPS.items()},
        "flags": FLAGS,
        "runs_with_outcome": len(outcomes),
        "seconds": round(time.perf_counter() - start, 1),
        "workers": workers,
    }
    return windows, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cohort", choices=sorted(SOURCES), action="append")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data" / "interim" / "features")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = parser.parse_args(argv)

    for cohort in args.cohort or ["2021", "2019"]:
        windows, summary = extract(cohort, args.workers)
        out = args.out_dir / cohort
        out.mkdir(parents=True, exist_ok=True)
        windows.to_parquet(out / "windows.parquet", index=False)
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
