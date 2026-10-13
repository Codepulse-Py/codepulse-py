import pandas as pd
from hypothesis import given
from hypothesis import strategies as st

from replay.engine import Edit, FileState, fits, splice
from replay.progsnap import Event, iter_sessions, load_main_table, parses, replay_session

# ---------------------------------------------------------------- engine


def test_insert_delete_replace():
    f = FileState()
    assert f.apply(Edit(0, 0, "print(1)"))
    assert f.apply(Edit(1, 6, "", "1"))
    assert f.apply(Edit(2, 6, "42", ""))
    assert f.apply(Edit(3, 0, "pr", "print"))  # replace: delete then insert
    assert f.text == "pr(42)"
    assert f.consistent and f.edits == 4


def test_mismatched_delete_is_counted_but_applied_as_logged():
    f = FileState(text="abcdef")
    assert not f.apply(Edit(7, 1, "", "XY"))
    assert f.text == "adef"
    assert f.mismatches == 1 and f.first_mismatch_event == 7


def test_offset_past_end_is_clamped():
    assert not fits("abc", Edit(0, 10, "z"))
    assert splice("abc", Edit(0, 10, "z")) == "abcz"


def test_checkpoint_replaces_text():
    f = FileState(text="old")
    f.checkpoint("starter\n")
    assert f.text == "starter\n"


@st.composite
def edit_histories(draw):
    """A random editing session: the edit log plus the true file after it."""
    text, log = "", []
    alphabet = st.sampled_from(list("ab \n\t()#:=1é"))
    for event_id in range(draw(st.integers(1, 60))):
        i = draw(st.integers(0, len(text)))
        j = draw(st.integers(i, min(len(text), i + 5)))
        insert = draw(st.text(alphabet, max_size=6))
        if i == j and not insert:
            insert = "x"
        log.append(Edit(event_id, i, insert, text[i:j]))
        text = text[:i] + insert + text[j:]
    return log, text


@given(edit_histories())
def test_replay_reproduces_final_file(history):
    log, final = history
    f = FileState()
    assert all(f.apply(e) for e in log)
    assert f.text == final
    assert f.consistent


# ---------------------------------------------------------------- sessions


def edit(eid, ts, file, offset, insert="", delete="", compilable=True):
    e = Edit(eid, offset, insert, delete)
    return Event(eid, ts, file, "edit", edit=e, compilable=compilable)


def test_session_snapshots_every_file_at_runs_and_end():
    events = [
        edit(0, 100, "main.py", 0, "import util\n"),
        edit(1, 110, "util.py", 0, "X = 1\n"),
        Event(2, 120, "main.py", "run"),
        edit(3, 130, "util.py", 4, "2", "1"),
        Event(4, 140, "main.py", "submit"),
    ]
    r = replay_session("S1", "A1", events)
    assert [s.kind for s in r.snapshots] == ["run", "submit", "final"]
    assert r.snapshots[0].files == {"main.py": "import util\n", "util.py": "X = 1\n"}
    assert r.snapshots[-1].files["util.py"] == "X = 2\n"
    assert r.consistent and r.matches_final


def test_states_are_reported_once_per_timestamp():
    events = [
        edit(0, 100, "a.py", 0, "x = (1"),
        edit(1, 100, "a.py", 6, ")"),  # auto-closed bracket, same ms
        edit(2, 200, "a.py", 6, "+2"),
    ]
    seen = []
    r = replay_session(
        "S1", "A1", events, check_every_state=True, on_state=lambda e, f, t: seen.append(t)
    )
    assert seen == ["x = (1)", "x = (1+2)"]
    assert r.compile_checks == 2 and r.compile_agreements == 2


def test_final_agreement_uses_last_logged_flag():
    events = [edit(0, 1, "a.py", 0, "def f(:", compilable=True)]
    r = replay_session("S1", "A1", events)
    assert r.final_agrees == {"a.py": False}
    assert not r.matches_final


def test_checkpoint_on_empty_file_is_starting_content():
    events = [
        Event(0, 1, "task0.py", "checkpoint", checkpoint="# starter\n", compilable=True),
        edit(1, 2, "task0.py", 10, "print(1)\n"),
    ]
    r = replay_session("S1", "p4s", events)
    assert r.checkpoints_on_empty == 1
    assert r.files["task0.py"].text == "# starter\nprint(1)\n"


def test_parses_handles_bad_source():
    assert parses("x = 1\n")
    assert not parses("def f(:\n")
    assert not parses("if x:\n\tpass\n        pass\n")
    assert not parses("x = 1\0")


# ---------------------------------------------------------------- loading


def test_load_and_iterate_merges_files_by_timestamp(tmp_path):
    rows = [
        # EventIDs are grouped by file, but the timestamps interleave.
        (0, "S1", "A1", "a.py", "File.Edit", "Insert", "0.0", "a = 1\n", "", 100, "", "1"),
        (1, "S1", "A1", "a.py", "Run.Program", "", "", "", "", 300, "Start", "1"),
        (2, "S1", "A1", "a.py", "Run.Program", "", "", "", "", 301, "0", "1"),
        (3, "S1", "A1", "b.py", "File.Edit", "Insert", "0.0", "b = 2\n", "", 200, "", "1"),
        (4, "S1", "A1", "b.py", "File.Edit", "", "0.0", "", "", 210, "", "1"),  # open marker
        (5, "S2", "A1", "a.py", "X-Keystroke", "", "0.0", "", "", 50, "q", "1"),
    ]
    cols = ["EventID", "SubjectID", "AssignmentID", "CodeStateSection", "EventType", "EditType",
            "SourceLocation", "InsertText", "DeleteText", "ClientTimestamp", "X-Metadata",
            "X-Compilable"]  # fmt: skip
    path = tmp_path / "keystrokes.csv"
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False)

    sessions = list(iter_sessions(load_main_table(path)))
    assert [(s, a) for s, a, _ in sessions] == [("S1", "A1"), ("S2", "A1")]
    events = sessions[0][2]
    assert [e.event_id for e in events] == [0, 3, 4, 1, 2]
    assert [e.kind for e in events] == ["edit", "edit", "other", "run", "other"]

    r = replay_session("S1", "A1", events)
    assert r.snapshots[0].kind == "run"
    assert r.snapshots[0].files == {"a.py": "a = 1\n", "b.py": "b = 2\n"}
