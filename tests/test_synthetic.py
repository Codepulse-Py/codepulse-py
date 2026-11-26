import random
from pathlib import Path
from textwrap import dedent

import pandas as pd
import pytest

from detectors import analyse
from replay.progsnap import iter_sessions, load_main_table, replay_session
from synthetic.generate import usable_for_training
from synthetic.inject import GROUNDED, Positions, apply, inject
from synthetic.trace import COLUMNS, Timing, Trace

RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "2021" / "keystrokes.csv"
SNAPSHOTS = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "interim"
    / "replay"
    / "2021"
    / "snapshots.parquet"
)


def run_inject(misconception, code, seed=0, methods=None):
    code = dedent(code).lstrip("\n")
    inj = inject(misconception, code, random.Random(seed), methods)
    return inj, (apply(code, inj.edits) if inj else None)


def flags(misconception, code):
    return analyse(code, only=[misconception]).findings


# ---------------------------------------------------------------- injectors


def test_identity_turns_equality_into_is():
    inj, out = run_inject("identity_literal", "if answer=='yes':\n    print(1)\n")
    assert out == "if answer is 'yes':\n    print(1)\n"
    assert inj.method == "eq_to_is" and flags("identity_literal", out)


def test_identity_not_equal_becomes_is_not():
    _, out = run_inject("identity_literal", "while count != 10:\n    count += 1\n")
    assert "count is not 10" in out


MOVED = """
def add(score):
    scores = []
    scores.append(score)
    return scores

add(1)
add(2)
"""


def test_mutable_default_moves_a_local_accumulator():
    inj, out = run_inject("mutable_default", MOVED, methods=GROUNDED)
    assert inj.method == "moved_local"
    assert "def add(score, scores=[]):" in out and "    scores = []\n" not in out
    assert flags("mutable_default", out)


def test_mutable_default_needs_a_repeatedly_called_function():
    once = MOVED.replace("add(2)\n", "")
    assert run_inject("mutable_default", once)[0] is None


def test_mutable_default_fallback_adds_an_accumulator_parameter():
    code = """
    def square(size):
        return size * size

    for i in range(3):
        square(i)
    """
    assert run_inject("mutable_default", code, methods=GROUNDED)[0] is None
    inj, out = run_inject("mutable_default", code)
    assert inj.method == "accumulator_param" and inj.method not in GROUNDED
    assert flags("mutable_default", out) and ".append(size)" in out


def test_aliasing_inserts_alias_and_retargets_the_mutation():
    code = """
    nums = [3, 1]
    nums.append(2)
    print(nums)
    """
    inj, out = run_inject("aliasing", code)
    alias = inj.note.split("`")[1].split(" = ")[0]
    assert f"{alias} = nums\n" in out and f"{alias}.append(2)" in out
    assert flags("aliasing", out)


def test_self_removed_from_a_method():
    code = """
    class Dog:
        def bark(self, times):
            print("Woof" * times)
    """
    inj, out = run_inject("self_confusion", code)
    assert inj.method == "remove_self" and "def bark(times):" in out
    assert flags("self_confusion", out)[0].rule == "missing_self"


def test_self_call_moved_onto_the_class():
    code = """
    class Dog:
        def bark():
            pass
    class Cat:
        @staticmethod
        def x():
            pass
    """
    assert run_inject("self_confusion", code)[0] is None  # already shows it: no seed
    code = """
    class Dog:
        @staticmethod
        def make():
            return 1
        def bark(self):
            print("Woof")
    d = Dog()
    d.bark()
    """
    for seed in range(10):
        inj, out = run_inject("self_confusion", code, seed=seed)
        if inj.method == "call_on_class":
            assert "Dog.bark()" in out and flags("self_confusion", out)
            break
    else:
        pytest.fail("call_on_class never chosen")


def test_seed_that_already_shows_the_misconception_is_rejected():
    assert run_inject("identity_literal", "if x is 3:\n    pass\n")[0] is None
    assert run_inject("identity_literal", "if x ==\n")[0] is None  # does not parse


def test_positions_handle_non_ascii():
    src = "name = 'é'\nif name == 'é':\n    pass\n"
    _, out = run_inject("identity_literal", src)
    assert out == "name = 'é'\nif name is 'é':\n    pass\n"
    assert Positions(src).offset(2, 3) == len("name = 'é'\n") + 3


# ---------------------------------------------------------------- trace


def test_trace_rows_replay_exactly(tmp_path):
    rng = random.Random(1)
    t = Trace("SYN-0001", "Assign9", "a.py", "x = 1\n", 1_000, Timing([100, 200], [15_000]), rng)
    t._row("File.Edit", SourceLocation="0.0", EditType="X-Checkpoint", InsertText="x = 1\n")
    t.type(6, "if x == 1:\n    pass\n")
    t.replace(11, "==", "is")  # after "x = 1\n" + "if x "
    t.erase(0, "x = 1\n")  # selection delete
    t.run()
    t.idle()
    rows = pd.DataFrame(t.rows, columns=COLUMNS)
    rows["EventID"] = range(len(rows))
    rows.to_csv(tmp_path / "k.csv", index=False)

    ((_, _, events),) = list(iter_sessions(load_main_table(tmp_path / "k.csv")))
    result = replay_session("SYN-0001", "Assign9", events)
    assert result.consistent and result.files["a.py"].text == t.text == "if x is 1:\n    pass\n"
    kinds = rows.EventType.tolist()
    assert kinds.count("X-Keystroke") == len("if x == 1:\n    pass\n") + 2
    assert kinds[-3:] == ["Run.Program", "Run.Program", "X-Action"]
    assert (rows.ToolInstances == "synthetic").all()
    assert rows.ClientTimestamp.astype(int).is_monotonic_increasing


def test_usable_for_training_drops_test_fold_seeds():
    manifest = pd.DataFrame({"synthetic_id": ["a", "b", "c"], "seed_subject": ["S1", "S2", "S1"]})
    assert usable_for_training(manifest, ["S1"]).synthetic_id.tolist() == ["b"]


# ---------------------------------------------------------------- end to end (needs data)


@pytest.mark.skipif(not (RAW.exists() and SNAPSHOTS.exists()), reason="raw data not available")
def test_generate_end_to_end(tmp_path):
    from synthetic.generate import generate

    summary = generate(RAW.parents[1], SNAPSHOTS, tmp_path, per_class=2, seed=3)
    manifest = pd.read_csv(tmp_path / "manifest.csv")
    assert sum(summary["kept"].values()) == len(manifest) >= 6
    assert manifest.synthetic.all() and manifest.seed_subject.str.startswith("Student").all()
    assert set(manifest.misconception) <= {
        "mutable_default", "aliasing", "identity_literal", "self_confusion"
    }  # fmt: skip
