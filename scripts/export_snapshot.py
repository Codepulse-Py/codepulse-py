"""Write one replay snapshot out as real .py files, optionally opening VS Code.

    python scripts/export_snapshot.py 2021 Student1 Assign10                  # end of session
    python scripts/export_snapshot.py 2021 Student1 Assign10 --list           # list snapshots
    python scripts/export_snapshot.py 2021 Student1 Assign10 --event-id 143   # a single run
    python scripts/export_snapshot.py 2019 S001 p5s --open                    # and open in VS Code

Every file of the session is written, since programs import each other, to

    data/interim/view/<cohort>/<subject>/<assignment>/<final | event_<id>>/<file>

Needs data/interim/replay/<cohort>/snapshots.parquet from scripts/replay_cohort.py.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
REPLAY_DIR = ROOT / "data" / "interim" / "replay"
VIEW_DIR = ROOT / "data" / "interim" / "view"


class ExportError(Exception):
    pass


def load_session(replay_dir: Path, cohort: str, subject: str, assignment: str) -> pd.DataFrame:
    path = replay_dir / cohort / "snapshots.parquet"
    if not path.exists():
        raise ExportError(f"{path} not found; run: python scripts/replay_cohort.py {cohort}")
    snaps = pd.read_parquet(path)
    session = snaps[(snaps.subject == subject) & (snaps.assignment == assignment)]
    if session.empty:
        if subject not in set(snaps.subject):
            raise ExportError(f"no subject {subject!r} in {cohort}")
        have = sorted(snaps.loc[snaps.subject == subject, "assignment"].unique())
        raise ExportError(f"{subject} has no {assignment!r}; available: {', '.join(have)}")
    return session


def list_snapshots(session: pd.DataFrame) -> pd.DataFrame:
    """One row per snapshot: when it was taken and which files it holds."""
    table = (
        session.groupby(["kind", "event_id", "timestamp", "trigger_file"], sort=False)
        .file.apply(lambda f: ", ".join(sorted(f)))
        .reset_index()
        .rename(columns={"file": "files"})
    )
    table["time_utc"] = pd.to_datetime(table.timestamp, unit="ms").dt.strftime("%Y-%m-%d %H:%M:%S")
    return table[["kind", "event_id", "time_utc", "trigger_file", "files"]]


def export(session: pd.DataFrame, out_root: Path, event_id: int | None) -> list[Path]:
    """Write the chosen snapshot's files under ``out_root``; return their paths."""
    if event_id is None:
        rows, label = session[session.kind == "final"], "final"
    else:
        rows, label = session[session.event_id == event_id], f"event_{event_id}"
        if rows.empty:
            raise ExportError(f"no snapshot at event {event_id}; use --list to see them")
        # A run on the session's last event is also the "final" snapshot.
        rows = rows.drop_duplicates("file")
    out = out_root / label
    written = []
    for row in rows.itertuples():
        path = (out / row.file).resolve()
        if not path.is_relative_to(out.resolve()):
            raise ExportError(f"unsafe file name {row.file!r}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(row.code)
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cohort", choices=["2019", "2021"])
    parser.add_argument("subject", help="e.g. Student1 (2021) or S001 (2019)")
    parser.add_argument("assignment", help="e.g. Assign10 (2021) or p5s (2019)")
    parser.add_argument("--event-id", type=int, help="snapshot to export (default: end of session)")
    parser.add_argument("--list", action="store_true", help="list the session's snapshots and exit")
    parser.add_argument("--open", action="store_true", help="open the exported folder in VS Code")
    parser.add_argument("--replay-dir", type=Path, default=REPLAY_DIR)
    parser.add_argument("--out-dir", type=Path, default=VIEW_DIR)
    args = parser.parse_args(argv)

    try:
        session = load_session(args.replay_dir, args.cohort, args.subject, args.assignment)
        if args.list:
            print(list_snapshots(session).to_string(index=False))
            return 0
        out_root = args.out_dir / args.cohort / args.subject / args.assignment
        written = export(session, out_root, args.event_id)
    except ExportError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    for path in written:
        print(path)
    if args.open:
        if shutil.which("code") is None:
            print("VS Code's `code` command not found; in VS Code run "
                  "'Shell Command: Install code command in PATH'", file=sys.stderr)  # fmt: skip
            return 1
        subprocess.run(["code", str(written[0].parent), *map(str, written)], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
