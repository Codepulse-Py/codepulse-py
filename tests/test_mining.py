from detectors.base import Finding
from mining.episodes import GAP_MS, Episode, EpisodeTracker, behaviour_context, mine_session
from replay.engine import Edit
from replay.progsnap import Event


def ev(eid, ts, file="a.py", insert="x", kind="edit"):
    edit = Edit(eid, 0, insert) if kind == "edit" else None
    return Event(eid, ts, file, kind, edit=edit)


def flag(detector="int_division", rule="", line=1):
    return Finding(detector, line, 0, line, "msg", rule)


def track(observations, end):
    t = EpisodeTracker("S1", "A1")
    for e, findings in observations:
        t.observe(e, e.file, "x = 1\n", findings)
    return t.finish(end)


def test_one_continuous_stretch_is_one_episode():
    obs = [(ev(i, i * 1000), [flag()]) for i in range(5)] + [(ev(5, 5000), [])]
    (ep,) = track(obs, end=9000)
    assert (ep.start_ms, ep.end_ms, ep.states) == (0, 5000, 5)


def test_short_disappearance_is_merged():
    obs = [(ev(0, 0), [flag()]), (ev(1, 1000), []), (ev(2, 1000 + GAP_MS - 1), [flag()])]
    (ep,) = track(obs, end=60_000)
    assert ep.states == 2


def test_long_disappearance_starts_a_new_episode():
    obs = [(ev(0, 0), [flag()]), (ev(1, 1000), []), (ev(2, 1000 + GAP_MS + 1), [flag()])]
    first, second = track(obs, end=60_000)
    assert first.end_ms == 1000 and second.start_ms == 1000 + GAP_MS + 1


def test_rules_files_and_instances_are_tracked_separately_and_merged():
    obs = [
        (ev(0, 0, "a.py"), [flag(line=1), flag(line=5)]),  # two instances, one episode
        (ev(1, 10, "a.py"), [flag("global_local", "unbound_local")]),
        (ev(2, 20, "b.py"), [flag()]),
    ]
    episodes = track(obs, end=100)
    keys = sorted((e.file, e.detector, e.rule) for e in episodes)
    assert keys == [("a.py", "global_local", "unbound_local"), ("a.py", "int_division", ""),
                    ("b.py", "int_division", "")]  # fmt: skip


def test_other_files_do_not_end_an_episode():
    obs = [(ev(0, 0, "a.py"), [flag()]), (ev(1, 50_000, "b.py"), [])]
    (ep,) = track(obs, end=90_000)
    assert ep.file == "a.py" and ep.end_ms == 90_000


def test_origin_and_persistence():
    paste = ev(0, 0, insert="y" * 60)
    (ep,) = track([(paste, [flag()]), (ev(1, 3000), [])], end=10_000)
    assert ep.origin == "paste" and ep.duration_ms == 3000 and not ep.persistent
    ep.runs_during = 1
    assert ep.persistent


def test_behaviour_context_counts_both_sides():
    events = [
        ev(0, 0, insert="ab"),  # outside the pre window [1000, 31000)
        ev(1, 10_000, kind="run"),
        ev(2, 31_000, insert="xyz"),  # the start event itself: post only
        ev(3, 40_000, insert="c"),
    ]
    ep = Episode("S1", "A1", "a.py", "d", "", 31_000, 2, "typed", 1, "", "")
    ctx = behaviour_context(ep, [e.timestamp for e in events], events)
    assert ctx["pre_edits"] == 0 and ctx["pre_runs"] == 1 and ctx["pre_longest_pause_s"] == 30.0
    assert ctx["post_edits"] == 2 and ctx["post_chars_inserted"] == 4


def test_mine_session_end_to_end():
    code = "for i in range(n / 2):\n    pass\n"
    events = [
        Event(0, 0, "a.py", "edit", edit=Edit(0, 0, code), compilable=True),
        Event(1, 20_000, "a.py", "run"),
        Event(2, 25_000, "a.py", "edit", edit=Edit(2, 15, "//", "/"), compilable=True),
    ]
    (ep,) = mine_session("S1", "A1", events)
    assert ep.detector == "int_division" and ep.origin == "typed"
    assert (ep.start_ms, ep.end_ms, ep.runs_during) == (0, 25_000, 1)
    assert ep.persistent and ep.line_text == "for i in range(n / 2):"
