import math

import pandas as pd
import pytest

from features.run_outcomes import _last_error, load_run_outcomes
from features.states import RUN_DEFAULT_MS, flailing_flags, label
from features.windows import FEATURES, FLAGS, RunOutcome, session_windows, window_ends
from replay.engine import Edit
from replay.progsnap import Event


def edit(eid, ts, offset=0, insert="x", delete="", file="a.py", compilable=True):
    return Event(
        eid, ts, file, "edit", edit=Edit(eid, offset, insert, delete), compilable=compilable
    )


def run(eid, ts, file="a.py"):
    return Event(eid, ts, file, "run")


def states(events, run_end=None):
    return [(iv.start_ms, iv.end_ms, iv.state) for iv in label(events, run_end)]


# ---------------------------------------------------------------- Algorithm 1 (#5)


@pytest.mark.parametrize(
    ("gap", "state"),
    [
        (0, "BURST_TYPING"),
        (99, "BURST_TYPING"),
        (100, "TYPING"),
        (500, "TYPING"),
        (1_999, "TYPING"),
        (2_000, "PAUSE"),
        (9_999, "PAUSE"),
        (10_000, "DEEP_THINKING"),
        (600_000, "DEEP_THINKING"),
    ],
)
def test_gap_thresholds(gap, state):
    assert states([edit(0, 0), edit(1, gap, offset=1)])[0][2] == state


def test_paste_over_50_characters():
    assert states([edit(0, 0), edit(1, 5_000, insert="y" * 51)])[0][2] == "PASTING"
    assert states([edit(0, 0), edit(1, 5_000, insert="y" * 50)])[0][2] == "PAUSE"


def test_running_lasts_until_the_logged_end_then_the_gap_is_labelled():
    events = [run(0, 0), edit(1, 30_000)]
    assert states(events, {0: 5_000}) == [(0, 5_000, "RUNNING"), (5_000, 30_000, "DEEP_THINKING")]
    assert states(events, {0: 60_000}) == [(0, 30_000, "RUNNING")]


def test_running_defaults_when_the_end_is_not_logged():
    events = [run(0, 0), edit(1, 15_000)]
    assert states(events) == [(0, RUN_DEFAULT_MS, "RUNNING"), (RUN_DEFAULT_MS, 15_000, "PAUSE")]


def test_flailing_needs_repeated_delete_retype_at_one_spot():
    # type, backspace, retype x3 at the same place within 10 s
    cycle = []
    for i in range(3):
        cycle += [edit(10 * i, 1000 * i, offset=5, insert="", delete="a"),
                  edit(10 * i + 1, 1000 * i + 300, offset=5, insert="b")]  # fmt: skip
    assert flailing_flags(cycle)[-1]
    assert states(cycle)[-1][2] == "FLAILING"


def test_one_typo_fix_is_not_flailing():
    fix = [edit(0, 0, 5, "x"), edit(1, 200, 5, "", "x"), edit(2, 400, 5, "y")]
    assert not any(flailing_flags(fix))


def test_far_apart_edits_are_not_flailing():
    far = []
    for i in range(3):
        far += [edit(10 * i, 1000 * i, offset=100 * i, insert="", delete="a"),
                edit(10 * i + 1, 1000 * i + 300, offset=100 * i, insert="b")]  # fmt: skip
    assert not any(flailing_flags(far))


# ---------------------------------------------------------------- windows (#7)


def test_window_ends_cover_every_activity_three_times():
    acts = [edit(0, 0), edit(1, 5_000), edit(2, 65_000)]
    ends = window_ends(acts)
    assert ends == [10_000, 20_000, 30_000, 70_000, 80_000, 90_000]
    for e in acts[1:]:
        assert sum(end - 30_000 < e.timestamp <= end for end in ends) == 3


def session():
    code = "for i in range(n / 2):\n    print(i)\n"
    events = [edit(0, 0, 0, code)]
    events += [edit(10 + i, 1_000 + 200 * i, len(code) + i, "#") for i in range(5)]
    events += [run(30, 4_000), edit(31, 20_000, 15, "/", compilable=False)]
    runs = {4_000: RunOutcome(errored=True, terminated=False, error_type="TypeError", end_ms=6_000)}
    return events, runs


def test_session_windows_end_to_end():
    events, runs = session()
    rows = session_windows("S1", "A1", events, runs)
    # the last activity is at 20 s; (20 s, 50 s] would not contain it
    assert [r["window_end_ms"] for r in rows] == [10_000, 20_000, 30_000, 40_000]
    first = rows[0]
    assert set(FEATURES + FLAGS) <= set(first)
    assert first["n_edits"] == 6 and first["n_runs"] == 1 and first["paste_count"] == 0
    assert first["run_errors"] == 1 and first["err_type"] == 1 and first["err_syntax"] == 0
    assert first["flag_int_division"] == 1 and first["parses"] == 1
    assert first["lines_touched"] == 2 and first["files_touched"] == 1
    assert first["state_running_s"] == 2.0  # run 4.0 s -> 6.0 s
    assert first["secs_since_last_run"] == 6.0
    for r in rows:
        assert 0 <= sum(r[f] for f in FEATURES if f.startswith("state_")) <= 30.0
    # the edit at 20 s makes the code `n //`-broken -> unparseable, flags carried over
    later = rows[1]
    assert later["parses"] == 0 and later["flag_int_division"] == 1
    assert later["unparseable_share"] == pytest.approx(1 / 7)  # 1 of the 7 edits in (-10 s, 20 s]


def test_windows_without_runs_have_no_run_timing():
    rows = session_windows("S1", "A1", [edit(0, 0, 0, "x = 1\n")])
    assert math.isnan(rows[0]["secs_since_last_run"]) and rows[0]["n_runs"] == 0


# ---------------------------------------------------------------- run outcomes


def test_last_error_reads_json_lists_and_tracebacks():
    assert _last_error('["SyntaxError: bad input on line 7"]') == "SyntaxError"
    assert _last_error("Traceback...\n  raise ValueError\nTypeError: x\n") == "TypeError"
    assert _last_error("  raise Terminator\nturtle.Terminator\n") == "Terminator"
    assert _last_error("all good") == ""


def write_2021(tmp_path, keystrokes, runs):
    k_cols = ["EventID", "SubjectID", "AssignmentID", "CodeStateSection", "EventType",
              "X-Metadata", "ClientTimestamp"]  # fmt: skip
    r_cols = ["SubjectID", "AssignmentID", "File", "Action", "RunID", "OutputDestination",
              "Output", "ClientTimestamp"]  # fmt: skip
    pd.DataFrame(keystrokes, columns=k_cols).to_csv(tmp_path / "keystrokes.csv", index=False)
    pd.DataFrame(runs, columns=r_cols).to_csv(tmp_path / "runs1.csv", index=False)


def test_2021_outcomes_join_runs_files(tmp_path):
    write_2021(
        tmp_path,
        [
            (0, "S1", "A1", "a.py", "Run.Program", "Start", 1000),
            (1, "S1", "A1", "a.py", "Run.Program", "1", 3000),
            (2, "S1", "A1", "a.py", "Run.Program", "Start", 5000),
            (3, "S1", "A1", "a.py", "Run.Program", "130", 9000),
            (4, "S1", "A1", "a.py", "Run.Program", "Start", 12000),  # not in runs files
            (5, "S1", "A1", "a.py", "Run.Program", "0", 12500),
        ],
        [
            ("S1", "A1", "a.py", "r", 1, "", "", 1000),
            ("S1", "A1", "", "o", 1, "stderr", "TypeError: missing 1 required\n", 1000),
            ("S1", "A1", "", "o", 1, "system", "\nProcess finished with exit code 1\n", 1000),
            ("S1", "A1", "a.py", "r", 2, "", "", 5000),
            ("S1", "A1", "", "o", 2, "stderr", "turtle.Terminator\n", 5000),
            ("S1", "A1", "", "o", 2, "system", "\nProcess finished with exit code 1\n", 5000),
        ],
    )
    out = load_run_outcomes(tmp_path, "2021").set_index("timestamp")
    assert out.loc[1000, "errored"] and out.loc[1000, "error_type"] == "TypeError"
    assert out.loc[1000, "end_ms"] == 3000
    assert out.loc[5000, "terminated"] and not out.loc[5000, "errored"]  # window closed
    assert not out.loc[12000, "errored"] and out.loc[12000, "error_type"] == ""


def test_2019_outcomes(tmp_path):
    cols = ["SubjectID", "AssignmentID", "CodeStateSection", "EventType", "ClientTimestamp",
            "X-RunHasError", "X-RunUserTerminated", "X-RunOutput"]  # fmt: skip
    pd.DataFrame(
        [
            ("S1", "p4s", "task0.py", "Run.Program", 10, "True", "False", '["NameError: x"]'),
            ("S1", "p4s", "task0.py", "Run.Program", 20, "False", "True", "[]"),
            ("S1", "p4s", "task0.py", "File.Edit", 30, "", "", ""),
        ],
        columns=cols,
    ).to_csv(tmp_path / "keystrokes.csv", index=False)
    out = load_run_outcomes(tmp_path, "2019")
    assert out.error_type.tolist() == ["NameError", ""]
    assert out.errored.tolist() == [True, False] and out.terminated.tolist() == [False, True]
    assert out.end_ms.isna().all()


def test_synthetic_runs_file_loads_like_2021(tmp_path):
    from synthetic.generate import Item, _write

    rows = [
        {"EventID": 0, "SubjectID": "SYN-0001", "AssignmentID": "A1", "CodeStateSection": "a.py",
         "EventType": "Run.Program", "X-Metadata": "Start", "ClientTimestamp": 100},
        {"EventID": 1, "SubjectID": "SYN-0001", "AssignmentID": "A1", "CodeStateSection": "a.py",
         "EventType": "Run.Program", "X-Metadata": "1", "ClientTimestamp": 900},
    ]  # fmt: skip
    item = Item("SYN-0001", "self_confusion", "missing_self", "remove_self", "", "Student1", "A1",
                "a.py", 1, 50, 100, [], rows,
                [{"timestamp": 100, "error_type": "TypeError", "exit_code": "1"}])  # fmt: skip
    _write([item], tmp_path / "keystrokes.csv")
    out = load_run_outcomes(tmp_path, "2021")
    assert out.error_type.tolist() == ["TypeError"] and out.errored.tolist() == [True]
    assert out.end_ms.tolist() == [900]
