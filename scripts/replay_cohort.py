"""Replay every session of a cohort and report how well the replay holds up.

    python scripts/replay_cohort.py 2021
    python scripts/replay_cohort.py 2019 --check-every-state

Writes to data/interim/replay/<cohort>/ (git-ignored):

    snapshots.parquet  every file of the session at each Run, Submit and the end
    sessions.csv       per-session replay metrics
    summary.json       cohort totals

A session *matches* when the replayed final text of every file agrees with the
last logged X-Compilable for that file (the release has no submitted files to
compare against; see docs/replay.md). Exits non-zero if fewer than
--min-match of sessions match.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from replay.progsnap import iter_sessions, load_main_table, replay_session  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cohort", choices=["2019", "2021"])
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data" / "interim" / "replay")
    parser.add_argument(
        "--check-every-state",
        action="store_true",
        help="also compare every intermediate code state with X-Compilable (slower)",
    )
    parser.add_argument("--no-snapshots", action="store_true")
    parser.add_argument("--min-match", type=float, default=0.99)
    args = parser.parse_args(argv)

    start = time.perf_counter()
    df = load_main_table(args.raw_dir / args.cohort / "keystrokes.csv")
    loaded = time.perf_counter() - start

    sessions, snapshots = [], []
    for subject, assignment, events in iter_sessions(df):
        r = replay_session(subject, assignment, events, check_every_state=args.check_every_state)
        sessions.append(
            {
                "subject": subject,
                "assignment": assignment,
                "events": len(events),
                "files": len(r.files),
                "edits": sum(f.edits for f in r.files.values()),
                "delete_mismatches": sum(f.mismatches for f in r.files.values()),
                "consistent": r.consistent,
                "files_final_agree": sum(r.final_agrees.values()),
                "matches_final": r.matches_final,
                "compile_checks": r.compile_checks,
                "compile_agreements": r.compile_agreements,
                "checkpoints_on_empty": r.checkpoints_on_empty,
                "checkpoints_matched": r.checkpoints_matched,
                "checkpoints_differed": r.checkpoints_differed,
                "runs": sum(s.kind == "run" for s in r.snapshots),
            }
        )
        if not args.no_snapshots:
            for snap in r.snapshots:
                for name, code in snap.files.items():
                    snapshots.append(
                        (subject, assignment, snap.kind, snap.event_id, snap.timestamp,
                         snap.file, name, code)
                    )  # fmt: skip
    elapsed = time.perf_counter() - start

    table = pd.DataFrame(sessions)
    match_rate = float(table.matches_final.mean())
    edits = int(table.edits.sum())
    summary = {
        "cohort": args.cohort,
        "sessions": len(table),
        "files": int(table.files.sum()),
        "edits": edits,
        "sessions_matching_final": int(table.matches_final.sum()),
        "session_match_rate": round(match_rate, 4),
        "files_final_agree": int(table.files_final_agree.sum()),
        "sessions_consistent": int(table.consistent.sum()),
        "delete_mismatch_rate": round(int(table.delete_mismatches.sum()) / max(edits, 1), 5),
        "checkpoints_on_empty": int(table.checkpoints_on_empty.sum()),
        "checkpoints_matched": int(table.checkpoints_matched.sum()),
        "checkpoints_differed": int(table.checkpoints_differed.sum()),
        "seconds_load": round(loaded, 1),
        "seconds_total": round(elapsed, 1),
    }
    if args.check_every_state:
        checks = int(table.compile_checks.sum())
        summary["state_compile_checks"] = checks
        summary["state_compile_agreement"] = round(
            int(table.compile_agreements.sum()) / max(checks, 1), 5
        )

    out = args.out_dir / args.cohort
    out.mkdir(parents=True, exist_ok=True)
    table.to_csv(out / "sessions.csv", index=False)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if not args.no_snapshots:
        cols = ["subject", "assignment", "kind", "event_id", "timestamp", "trigger_file", "file",
                "code"]  # fmt: skip
        pd.DataFrame(snapshots, columns=cols).to_parquet(out / "snapshots.parquet", index=False)

    print(json.dumps(summary, indent=2))
    # Compare the unrounded rate: 0.98996 must not pass a 0.99 threshold.
    ok = match_rate >= args.min_match
    print(
        f"{'PASS' if ok else 'FAIL'}  {match_rate:.2%} of sessions match "
        f"(threshold {args.min_match:.0%}) in {elapsed:.0f}s"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
