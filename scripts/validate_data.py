"""Validate the Edwards 2019 and 2021 CS1 keystroke datasets.

Checks that every raw file matches the SHA-256 manifest in data/MANIFEST.md,
that each ProgSnap2 MainTable (keystrokes.csv) parses with the expected
columns and event types, and that event / subject / assignment counts agree
with Edwards et al., JEDM 15(1), 2023, Table 2.

    python scripts/validate_data.py                  # verify everything
    python scripts/validate_data.py --skip-hash      # counts only
    python scripts/validate_data.py --write-manifest # regenerate the manifest
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
MANIFEST = ROOT / "data" / "MANIFEST.md"
CHUNK_ROWS = 500_000


@dataclass(frozen=True)
class Cohort:
    name: str
    columns: tuple[str, ...]
    event_types: frozenset[str]
    # Column holding the assignment id without the 2019 term suffix.
    assignment_col: str
    assignments: int
    reported_subjects: int
    # Subjects actually present in the released MainTable (may be < reported).
    released_subjects: int
    min_events: int
    max_events: int | None
    first_ts: str
    last_ts: str
    main_table: str = "keystrokes.csv"


COHORTS = {
    "2021": Cohort(
        name="2021",
        columns=(
            "EventID",
            "SubjectID",
            "AssignmentID",
            "CodeStateSection",
            "EventType",
            "SourceLocation",
            "EditType",
            "InsertText",
            "DeleteText",
            "X-Metadata",
            "ClientTimestamp",
            "ToolInstances",
            "CodeStateID",
            "X-Compilable",
        ),
        event_types=frozenset(
            {
                "File.Edit",
                "X-Keystroke",
                "X-Action",
                "Run.Program",
                "X-ReplayAction",
                "X-Paste",
                "X-Copy",
                "X-Attention",
            }
        ),
        assignment_col="AssignmentID",
        assignments=8,
        reported_subjects=44,
        released_subjects=44,
        min_events=1_000_000,
        max_events=None,
        first_ts="2021-08-01",
        last_ts="2022-06-30",
    ),
    "2019": Cohort(
        name="2019",
        columns=(
            "EventID",
            "SubjectID",
            "AssignmentID",
            "CodeStateSection",
            "X-Task",
            "EventType",
            "X-Keystroke",
            "InsertText",
            "DeleteText",
            "SourceLocation",
            "ClientTimestamp",
            "EditType",
            "X-RunInput",
            "X-RunOutput",
            "X-RunHasError",
            "X-RunUserTerminated",
            "X-RawAssignmentID",
            "X-Term",
            "X-Compilable",
        ),
        event_types=frozenset({"File.Edit", "Run.Program", "X-SwitchTask", "Submit"}),
        assignment_col="X-RawAssignmentID",
        assignments=5,
        reported_subjects=505,
        released_subjects=487,
        min_events=4_500_000,
        max_events=5_500_000,
        # A few fall students reopened p8 in 2020 (see the dataset readme).
        first_ts="2019-01-01",
        last_ts="2020-12-31",
    ),
}


@dataclass
class Report:
    cohort: str
    columns: list[str] = field(default_factory=list)
    events: int = 0
    event_types: Counter = field(default_factory=Counter)
    subjects: set[str] = field(default_factory=set)
    assignments: set[str] = field(default_factory=set)
    assignment_ids: set[str] = field(default_factory=set)
    first_ts: pd.Timestamp | None = None
    last_ts: pd.Timestamp | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- manifest


def data_files(cohort_dir: Path) -> list[Path]:
    return sorted(
        p
        for p in cohort_dir.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(cohort_dir).parts)
    )


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(1 << 20):
            h.update(block)
    return h.hexdigest()


def write_manifest(raw_dir: Path, cohorts: list[str], out: Path) -> None:
    lines = [
        "# Raw data manifest",
        "",
        "SHA-256 of every file under `data/raw/<cohort>/` (hidden files skipped).",
        "Regenerate with `python scripts/validate_data.py --write-manifest`;",
        "`python scripts/validate_data.py` fails if any file is missing or differs.",
        "",
        "| Cohort | File | Bytes | SHA-256 |",
        "|---|---|---:|---|",
    ]
    for name in cohorts:
        cohort_dir = raw_dir / name
        for path in data_files(cohort_dir):
            rel = path.relative_to(cohort_dir).as_posix()
            lines.append(f"| {name} | `{rel}` | {path.stat().st_size} | `{sha256(path)}` |")
    out.write_text("\n".join(lines) + "\n")


ROW = re.compile(r"^\| (\w+) \| `(.+)` \| (\d+) \| `([0-9a-f]{64})` \|$")


def read_manifest(path: Path) -> dict[tuple[str, str], tuple[int, str]]:
    entries = {}
    for line in path.read_text().splitlines():
        if m := ROW.match(line):
            entries[(m[1], m[2])] = (int(m[3]), m[4])
    return entries


def check_manifest(raw_dir: Path, cohort: str, manifest: dict, report: Report) -> None:
    expected = {rel: v for (c, rel), v in manifest.items() if c == cohort}
    if not expected:
        report.errors.append(f"no manifest entries for cohort {cohort}")
        return
    cohort_dir = raw_dir / cohort
    present = {p.relative_to(cohort_dir).as_posix(): p for p in data_files(cohort_dir)}
    for rel in sorted(expected.keys() - present.keys()):
        report.errors.append(f"missing file: {rel}")
    for rel in sorted(present.keys() - expected.keys()):
        report.errors.append(f"file not in manifest: {rel}")
    for rel in sorted(expected.keys() & present.keys()):
        size, digest = expected[rel]
        path = present[rel]
        if path.stat().st_size != size or sha256(path) != digest:
            report.errors.append(f"checksum mismatch: {rel}")


# ---------------------------------------------------------------- MainTable


def scan_main_table(path: Path, spec: Cohort, report: Report) -> None:
    event_ids = []
    ts_min = ts_max = None
    reader = pd.read_csv(path, dtype=str, keep_default_na=False, chunksize=CHUNK_ROWS)
    for chunk in reader:
        if not report.columns:
            report.columns = list(chunk.columns)
        report.events += len(chunk)
        report.event_types.update(chunk["EventType"].value_counts().to_dict())
        report.subjects.update(chunk["SubjectID"].unique())
        report.assignments.update(chunk[spec.assignment_col].unique())
        report.assignment_ids.update(chunk["AssignmentID"].unique())
        event_ids.append(pd.to_numeric(chunk["EventID"], errors="coerce"))
        for col in ("EventID", "SubjectID", "AssignmentID", "EventType", "ClientTimestamp"):
            if (blank := int((chunk[col] == "").sum())) > 0:
                report.errors.append(f"{blank} blank {col} values")
        ts = pd.to_numeric(chunk["ClientTimestamp"], errors="coerce")
        if (bad := int(ts.isna().sum())) > 0:
            report.errors.append(f"{bad} non-numeric ClientTimestamp values")
        lo, hi = ts.min(), ts.max()
        ts_min = lo if ts_min is None else min(ts_min, lo)
        ts_max = hi if ts_max is None else max(ts_max, hi)

    ids = pd.concat(event_ids)
    if ids.isna().any() or not ids.is_unique:
        report.errors.append("EventID is not a unique integer key")
    if ts_min is not None:
        report.first_ts = pd.to_datetime(ts_min, unit="ms")
        report.last_ts = pd.to_datetime(ts_max, unit="ms")


def check_main_table(raw_dir: Path, spec: Cohort, report: Report) -> None:
    path = raw_dir / spec.name / spec.main_table
    if not path.exists():
        report.errors.append(f"MainTable not found: {path}")
        return
    header = list(pd.read_csv(path, nrows=0).columns)
    if header != list(spec.columns):
        missing = [c for c in spec.columns if c not in header]
        extra = [c for c in header if c not in spec.columns]
        report.errors.append(f"unexpected columns (missing={missing}, extra={extra})")
        return
    scan_main_table(path, spec, report)

    unknown = set(report.event_types) - spec.event_types
    if unknown:
        report.errors.append(f"unknown event types: {sorted(unknown)}")

    if report.events < spec.min_events or (spec.max_events and report.events > spec.max_events):
        bound = f"[{spec.min_events:,}, {spec.max_events:,}]" if spec.max_events else ""
        report.errors.append(
            f"event count {report.events:,} outside {bound or f'>= {spec.min_events:,}'}"
        )

    if len(report.subjects) != spec.released_subjects:
        report.errors.append(
            f"{len(report.subjects)} subjects, expected {spec.released_subjects} in release"
        )
    elif spec.released_subjects < spec.reported_subjects:
        report.warnings.append(
            f"{spec.released_subjects} subjects in MainTable vs {spec.reported_subjects} "
            "participants reported in JEDM 2023 (known gap, see docs/data.md)"
        )

    if len(report.assignments) != spec.assignments:
        report.errors.append(
            f"{len(report.assignments)} assignments, expected {spec.assignments}: "
            f"{sorted(report.assignments)}"
        )

    due = raw_dir / spec.name / "due.csv"
    if due.exists():
        due_ids = set(pd.read_csv(due, dtype=str)["AssignmentID"])
        if due_ids != report.assignment_ids:
            diff = sorted(due_ids ^ report.assignment_ids)
            report.errors.append(f"AssignmentIDs differ from due.csv: {diff}")

    if report.first_ts is not None and (
        report.first_ts < pd.Timestamp(spec.first_ts) or report.last_ts > pd.Timestamp(spec.last_ts)
    ):
        report.errors.append(
            f"timestamps {report.first_ts} .. {report.last_ts} outside "
            f"{spec.first_ts} .. {spec.last_ts}"
        )


# ---------------------------------------------------------------- CLI


def validate(raw_dir: Path, spec: Cohort, manifest: dict | None) -> Report:
    report = Report(cohort=spec.name)
    if not (raw_dir / spec.name).is_dir():
        report.errors.append(f"{raw_dir / spec.name} not found (see docs/data.md)")
        return report
    if manifest is not None:
        check_manifest(raw_dir, spec.name, manifest, report)
    check_main_table(raw_dir, spec, report)
    return report


def print_report(report: Report) -> None:
    print(f"\n== {report.cohort} cohort ==")
    if report.columns:
        print(f"columns ({len(report.columns)}): {', '.join(report.columns)}")
        print(f"events: {report.events:,}")
        for etype, n in report.event_types.most_common():
            print(f"  {etype:<16} {n:>10,}")
        print(f"subjects: {len(report.subjects)}")
        print(f"assignments ({len(report.assignments)}): {', '.join(sorted(report.assignments))}")
        print(f"time range: {report.first_ts} .. {report.last_ts}")
    for w in report.warnings:
        print(f"WARN  {w}")
    for e in report.errors:
        print(f"FAIL  {e}")
    print("PASS" if not report.errors else "FAILED")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--cohort", choices=sorted(COHORTS), action="append")
    parser.add_argument("--skip-hash", action="store_true", help="skip checksum verification")
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args(argv)
    cohorts = args.cohort or sorted(COHORTS)

    if args.write_manifest:
        write_manifest(args.raw_dir, cohorts, args.manifest)
        print(f"wrote {args.manifest}")
        return 0

    manifest = None
    if not args.skip_hash:
        if not args.manifest.exists():
            print(f"FAIL  manifest not found: {args.manifest}")
            return 1
        manifest = read_manifest(args.manifest)

    ok = True
    for name in cohorts:
        report = validate(args.raw_dir, COHORTS[name], manifest)
        print_report(report)
        ok &= not report.errors
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
