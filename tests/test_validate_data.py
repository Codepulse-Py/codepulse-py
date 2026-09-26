import dataclasses

import pandas as pd
import pytest

from scripts import validate_data as vd

COLUMNS = ("EventID", "SubjectID", "AssignmentID", "EventType", "ClientTimestamp")
SPEC = vd.Cohort(
    name="tiny",
    columns=COLUMNS,
    event_types=frozenset({"File.Edit", "Run.Program"}),
    assignment_col="AssignmentID",
    assignments=2,
    reported_subjects=2,
    released_subjects=2,
    min_events=4,
    max_events=10,
    first_ts="2021-01-01",
    last_ts="2021-12-31",
)
TS = 1_634_600_000_000  # 2021-10-18


def write_cohort(raw_dir, rows=None):
    cohort_dir = raw_dir / "tiny"
    cohort_dir.mkdir(parents=True)
    rows = rows or [
        (0, "S1", "A1", "File.Edit", TS),
        (1, "S1", "A2", "File.Edit", TS + 1),
        (2, "S2", "A1", "Run.Program", TS + 2),
        (3, "S2", "A2", "File.Edit", TS + 3),
    ]
    pd.DataFrame(rows, columns=COLUMNS).to_csv(cohort_dir / "keystrokes.csv", index=False)
    pd.DataFrame({"AssignmentID": ["A1", "A2"]}).to_csv(cohort_dir / "due.csv", index=False)
    (cohort_dir / ".DS_Store").write_bytes(b"junk")
    return cohort_dir


@pytest.fixture
def raw(tmp_path):
    raw_dir = tmp_path / "raw"
    write_cohort(raw_dir)
    return raw_dir


def run(raw_dir, spec=SPEC, manifest=None):
    return vd.validate(raw_dir, spec, manifest)


def test_valid_cohort_passes(raw):
    report = run(raw)
    assert report.errors == []
    assert report.events == 4
    assert report.subjects == {"S1", "S2"}
    assert report.event_types == {"File.Edit": 3, "Run.Program": 1}


def test_manifest_roundtrip(raw, tmp_path):
    out = tmp_path / "MANIFEST.md"
    vd.write_manifest(raw, ["tiny"], out)
    manifest = vd.read_manifest(out)
    assert set(manifest) == {("tiny", "keystrokes.csv"), ("tiny", "due.csv")}
    assert run(raw, manifest=manifest).errors == []


def test_manifest_detects_modified_file(raw, tmp_path):
    out = tmp_path / "MANIFEST.md"
    vd.write_manifest(raw, ["tiny"], out)
    (raw / "tiny" / "due.csv").write_text("AssignmentID\nA1\nA2\n\n")
    errors = run(raw, manifest=vd.read_manifest(out)).errors
    assert "checksum mismatch: due.csv" in errors


def test_manifest_detects_missing_and_extra_files(raw, tmp_path):
    out = tmp_path / "MANIFEST.md"
    vd.write_manifest(raw, ["tiny"], out)
    (raw / "tiny" / "due.csv").unlink()
    (raw / "tiny" / "extra.txt").write_text("x")
    errors = run(raw, manifest=vd.read_manifest(out)).errors
    assert "missing file: due.csv" in errors
    assert "file not in manifest: extra.txt" in errors


def test_count_mismatches_fail(raw):
    spec = dataclasses.replace(SPEC, released_subjects=3, assignments=3, min_events=5)
    errors = " | ".join(run(raw, spec).errors)
    assert "2 subjects" in errors
    assert "2 assignments" in errors
    assert "event count 4" in errors


def test_release_gap_is_a_warning(raw):
    report = run(raw, dataclasses.replace(SPEC, reported_subjects=5))
    assert report.errors == []
    assert "5 participants reported" in report.warnings[0]


def test_unknown_event_type_and_duplicate_ids_fail(tmp_path):
    raw_dir = tmp_path / "raw"
    write_cohort(
        raw_dir,
        rows=[
            (0, "S1", "A1", "File.Edit", TS),
            (0, "S1", "A2", "Mystery", TS),
            (2, "S2", "A1", "File.Edit", TS),
            (3, "S2", "A2", "File.Edit", TS),
        ],
    )
    errors = " | ".join(run(raw_dir).errors)
    assert "unknown event types: ['Mystery']" in errors
    assert "EventID is not a unique integer key" in errors


def test_timestamps_out_of_range_fail(tmp_path):
    raw_dir = tmp_path / "raw"
    write_cohort(
        raw_dir,
        rows=[(i, f"S{i % 2}", f"A{i % 2 + 1}", "File.Edit", 1_000) for i in range(4)],
    )
    assert any("outside" in e for e in run(raw_dir).errors)


def test_wrong_columns_fail(raw):
    spec = dataclasses.replace(SPEC, columns=(*COLUMNS, "X-Compilable"))
    assert "missing=['X-Compilable']" in run(raw, spec).errors[0]


def test_missing_cohort_dir_fails(tmp_path):
    assert "not found" in run(tmp_path).errors[0]
