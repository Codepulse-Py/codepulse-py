from textwrap import dedent

import pytest

from detectors import REGISTRY, StructuralAnalyzer, analyse


def hits(name: str, code: str):
    result = analyse(dedent(code), only=[name])
    assert result.parsed, result.error
    return result.findings


def check(name, code, expected):
    found = hits(name, code)
    assert len(found) == expected, [f.message for f in found]
    return found


# ---------------------------------------------------------------- 1 mutable default

MUTABLE_POSITIVE = [
    "def add(item, items=[]):\n    items.append(item)\n    return items\n",
    "def count(word, seen={}):\n    seen[word] = seen.get(word, 0) + 1\n",
    "def tag(x, *, tags=set()):\n    tags.add(x)\n",
    "def grid(n, rows=[[0] * 3 for _ in range(3)]):\n    return rows\n",
    "f = lambda x, acc=list(): acc + [x]\n",
    "class Pet:\n    def __init__(self, name, tricks=[]):\n        self.tricks = tricks\n",
]
MUTABLE_NEGATIVE = [
    "def add(item, items=None):\n    if items is None:\n        items = []\n    return items\n",
    "def area(w=1, h=2.5, unit='cm', point=(0, 0)):\n    return w * h\n",
    "def f(items):\n    items = []\n    return items\n",
    "def f(n=len([1, 2])):\n    return n\n",
]


@pytest.mark.parametrize("code", MUTABLE_POSITIVE)
def test_mutable_default_positive(code):
    check("mutable_default", code, 1)


@pytest.mark.parametrize("code", MUTABLE_NEGATIVE)
def test_mutable_default_negative(code):
    check("mutable_default", code, 0)


def test_mutable_default_message_names_the_parameter():
    (f,) = hits("mutable_default", MUTABLE_POSITIVE[0])
    assert "add()" in f.message and "'items'" in f.message and f.line == 1


# ---------------------------------------------------------------- 2 aliasing

ALIAS_POSITIVE = [
    # mutate the alias, read the original
    """
    scores = [90, 80]
    backup = scores
    backup.append(70)
    print(scores)
    """,
    # mutate the original by item assignment, read the alias
    """
    grid = [[0, 0], [0, 0]]
    old = grid
    grid[0] = [1, 1]
    print(old)
    """,
    # dict alias inside a function, del mutation
    """
    def reset(counts):
        totals = {'a': 1}
        snapshot = totals
        del totals['a']
        return snapshot
    """,
    # list += mutates in place
    """
    a = list(range(3))
    b = a
    b += [9]
    total = sum(a)
    """,
    # set alias, original read in a later expression
    """
    seen = set()
    other = seen
    other.add(1)
    if 1 in seen:
        pass
    """,
]
ALIAS_NEGATIVE = [
    # copied, not aliased
    """
    scores = [90, 80]
    backup = scores[:]
    backup.append(70)
    print(scores)
    """,
    """
    scores = [90, 80]
    backup = list(scores)
    backup.append(70)
    print(scores)
    """,
    # alias rebound before the mutation
    """
    a = [1, 2]
    b = a
    b = [3]
    b.append(4)
    print(a)
    """,
    # immutable values: rebinding, not mutation
    """
    x = 5
    y = x
    y += 1
    print(x)
    """,
    # aliased and mutated but the other name is never read afterwards
    """
    a = [1]
    b = a
    b.append(2)
    print(b)
    """,
    # read of the other name only inside the mutating call (evaluated before it)
    """
    a = [1]
    b = a
    b.append(len(a))
    """,
]


@pytest.mark.parametrize("code", ALIAS_POSITIVE)
def test_aliasing_positive(code):
    check("aliasing", code, 1)


@pytest.mark.parametrize("code", ALIAS_NEGATIVE)
def test_aliasing_negative(code):
    check("aliasing", code, 0)


def test_aliasing_reports_at_the_assignment_with_lines():
    (f,) = hits("aliasing", ALIAS_POSITIVE[0])
    assert f.line == 3  # the `backup = scores` line (dedent keeps the leading newline)
    assert "line 4" in f.message and "line 5" in f.message


# ---------------------------------------------------------------- 3 identity vs equality

IDENTITY_POSITIVE = [
    "if answer is 'yes':\n    pass\n",
    "while count is not 10:\n    count += 1\n",
    "ok = 3.5 is x\n",
    "if n is -1:\n    pass\n",
    "if 0 < x is 5:\n    pass\n",
]
IDENTITY_NEGATIVE = [
    "if x is None:\n    pass\n",
    "if done is True or flag is not False:\n    pass\n",
    "if answer == 'yes':\n    pass\n",
    "if a is b:\n    pass\n",
    "if type(x) is int:\n    pass\n",
]


@pytest.mark.parametrize("code", IDENTITY_POSITIVE)
def test_identity_positive(code):
    check("identity_literal", code, 1)


@pytest.mark.parametrize("code", IDENTITY_NEGATIVE)
def test_identity_negative(code):
    check("identity_literal", code, 0)


def test_identity_message_suggests_equality():
    (f,) = hits("identity_literal", IDENTITY_POSITIVE[1])
    assert "'is not'" in f.message and "'!='" in f.message


# ---------------------------------------------------------------- 4 indentation scope

INDENT_POSITIVE = [
    # return False indented into the loop
    """
    def contains(xs, target):
        for x in xs:
            if x == target:
                return True
            else:
                return False
    """,
    # unconditional break at the end of a while body
    """
    while n > 0:
        total += n
        n -= 1
        break
    """,
    # statement after return in the same block
    """
    def area(w, h):
        return w * h
        print('done')
    """,
    # statement after continue in a loop body
    """
    for i in range(5):
        if i % 2:
            continue
            print(i)
    """,
]
INDENT_POSITIVE.append(
    # real code after a placeholder is still unreachable
    """
    def f():
        return 1
        pass
        print('never')
    """
)
INDENT_NEGATIVE = [
    # return False correctly after the loop
    """
    def contains(xs, target):
        for x in xs:
            if x == target:
                return True
        return False
    """,
    # conditional break: the loop can repeat
    """
    while True:
        guess = input()
        if guess == 'q':
            break
    """,
    # accumulator correctly inside the loop, print after it
    """
    total = 0
    for x in range(10):
        total += x
    print(total)
    """,
    # early return guarded by a condition
    """
    def f(x):
        if x < 0:
            return 0
        return x
    """,
    # starter-template placeholder after the student's return
    """
    def pick(family):
        return family[0]
        pass  # Remove this line to work on this function.
    """,
    # half-typed name after return (student is mid-way through typing)
    """
    def main():
        run()
        return
        p
    """,
]


@pytest.mark.parametrize("code", INDENT_POSITIVE)
def test_indentation_positive(code):
    check("indentation_scope", code, 1)


@pytest.mark.parametrize("code", INDENT_NEGATIVE)
def test_indentation_negative(code):
    check("indentation_scope", code, 0)


def test_indentation_rules_are_labelled():
    assert hits("indentation_scope", INDENT_POSITIVE[0])[0].rule == "loop_exits_first_pass"
    assert hits("indentation_scope", INDENT_POSITIVE[2])[0].rule == "unreachable_after_exit"


# ---------------------------------------------------------------- registry and fallback


def test_registry_holds_detectors_1_to_4():
    numbers = {d.number: name for name, d in REGISTRY.items()}
    assert numbers == {
        1: "mutable_default",
        2: "aliasing",
        3: "identity_literal",
        4: "indentation_scope",
    }
    assert REGISTRY["indentation_scope"].exploratory


def test_analyse_runs_all_detectors_in_line_order():
    code = "def f(x=[]):\n    return x is 1\n"
    result = analyse(code)
    assert [f.detector for f in result.findings] == ["mutable_default", "identity_literal"]


def test_unparseable_code_without_history_returns_nothing():
    result = analyse("def f(:\n")
    assert not result.parsed and result.findings == [] and "SyntaxError" in result.error


def test_falls_back_to_last_parseable_state():
    analyzer = StructuralAnalyzer()
    good = analyzer.analyse("task1.py", "def f(x=[]):\n    return x\n")
    assert good.parsed and not good.stale and len(good.findings) == 1

    broken = analyzer.analyse("task1.py", "def f(x=[]):\n    return x +\n")
    assert not broken.parsed and broken.stale
    assert broken.findings == good.findings
    assert "SyntaxError" in broken.error

    other_file = analyzer.analyse("task2.py", "x = (\n")
    assert not other_file.parsed and not other_file.stale and other_file.findings == []

    fixed = analyzer.analyse("task1.py", "def f(x=None):\n    return x\n")
    assert fixed.parsed and fixed.findings == []


def test_tab_space_mix_is_treated_as_unparseable():
    assert not analyse("if x:\n\tpass\n        pass\n").parsed


def test_no_warnings_escape_for_broken_code_with_bad_escapes(recwarn):
    result = analyse('path = "C:\\ new"\nif x is 1\n')
    assert not result.parsed
    assert not [w for w in recwarn if issubclass(w.category, SyntaxWarning)]
