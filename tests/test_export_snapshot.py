import pandas as pd
import pytest

from scripts import export_snapshot as ex

COLS = ["subject", "assignment", "kind", "event_id", "timestamp", "trigger_file", "file", "code"]
ROWS = [
    ("S1", "A1", "run", 5, 1_634_600_000_000, "main.py", "main.py", "import util\n"),
    ("S1", "A1", "run", 5, 1_634_600_000_000, "main.py", "util.py", "X = 1\n"),
    ("S1", "A1", "final", 9, 1_634_600_060_000, "util.py", "main.py", "import util\nprint(1)\n"),
    ("S1", "A1", "final", 9, 1_634_600_060_000, "util.py", "util.py", "X = 2\n"),
    ("S1", "A2", "final", 3, 1_634_700_000_000, "a.py", "a.py", "pass\n"),
]


@pytest.fixture
def dirs(tmp_path):
    replay = tmp_path / "replay"
    (replay / "2021").mkdir(parents=True)
    pd.DataFrame(ROWS, columns=COLS).to_parquet(replay / "2021" / "snapshots.parquet")
    return replay, tmp_path / "view"


def run(dirs, *args):
    replay, view = dirs
    return ex.main(["2021", *args, "--replay-dir", str(replay), "--out-dir", str(view)])


def test_exports_final_version_of_every_file(dirs, capsys):
    assert run(dirs, "S1", "A1") == 0
    out = dirs[1] / "2021" / "S1" / "A1" / "final"
    assert (out / "main.py").read_text() == "import util\nprint(1)\n"
    assert (out / "util.py").read_text() == "X = 2\n"
    assert str(out / "main.py") in capsys.readouterr().out


def test_exports_a_run_by_event_id(dirs):
    assert run(dirs, "S1", "A1", "--event-id", "5") == 0
    out = dirs[1] / "2021" / "S1" / "A1" / "event_5"
    assert (out / "util.py").read_text() == "X = 1\n"


def test_lists_snapshots(dirs, capsys):
    assert run(dirs, "S1", "A1", "--list") == 0
    out = capsys.readouterr().out
    assert "run" in out and "final" in out and "main.py, util.py" in out
    assert "2021-10-18" in out
    assert not dirs[1].exists()


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["S9", "A1"], "no subject 'S9'"),
        (["S1", "A9"], "available: A1, A2"),
        (["S1", "A1", "--event-id", "7"], "no snapshot at event 7"),
    ],
)
def test_errors_are_explained(dirs, capsys, args, message):
    assert run(dirs, *args) == 1
    assert message in capsys.readouterr().err


def test_missing_replay_output_points_to_replay_script(tmp_path, capsys):
    assert ex.main(["2021", "S1", "A1", "--replay-dir", str(tmp_path)]) == 1
    assert "replay_cohort.py 2021" in capsys.readouterr().err


def test_rejects_file_names_outside_the_export_folder(tmp_path):
    session = pd.DataFrame([("S1", "A1", "final", 1, 0, "x", "../evil.py", "")], columns=COLS)
    with pytest.raises(ex.ExportError, match="unsafe"):
        ex.export(session, tmp_path / "out", None)


def test_open_launches_vs_code(dirs, monkeypatch):
    calls = []
    monkeypatch.setattr(ex.shutil, "which", lambda name: "/usr/local/bin/code")
    monkeypatch.setattr(ex.subprocess, "run", lambda cmd, check: calls.append(cmd))
    assert run(dirs, "S1", "A2", "--open") == 0
    assert calls[0][0] == "code" and calls[0][-1].endswith("a.py")
