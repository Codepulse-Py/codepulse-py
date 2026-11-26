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


def test_registry_holds_all_seven_detectors_with_phases():
    table = {d.number: (name, d.phase) for name, d in REGISTRY.items()}
    assert table == {
        1: ("mutable_default", "post-run"),
        2: ("aliasing", "pre-run"),
        3: ("identity_literal", "pre-run"),
        4: ("indentation_scope", "pre-run"),
        5: ("global_local", "post-run"),
        6: ("self_confusion", "post-run"),
        7: ("int_division", "pre-run"),
    }
    assert [n for n, d in REGISTRY.items() if d.exploratory] == ["indentation_scope"]


def test_register_rejects_bad_phase_and_duplicates():
    from detectors.base import register

    with pytest.raises(ValueError, match="phase"):
        register(99, "x", "X", phase="during-run")
    with pytest.raises(ValueError, match="registered twice"):
        register(1, "another", "Another", phase="pre-run")(lambda tree, source: [])


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


# ---------------------------------------------------------------- 5 global vs local

GLOBAL_POSITIVE = [
    # read before assignment: UnboundLocalError
    """
    count = 0
    def increment():
        count = count + 1
    """,
    # augmented assignment
    """
    score = 0
    def add_point():
        score += 1
        return score
    """,
    # read in a condition before the assignment
    """
    total = 10
    def spend(x):
        if total > x:
            total = total - x
    """,
    # assignment meant for the global: local never used, global read by the loop
    """
    done = False
    def finish():
        done = True
    while not done:
        finish()
    """,
    # global read in another function
    """
    lives = 3
    def lose_life():
        lives = 2
    def show():
        print(lives)
    """,
    # method of a class assigning a module-level name
    """
    counter = 0
    class Pet:
        def feed(self):
            counter = counter + 1
    """,
]
GLOBAL_NEGATIVE = [
    # global declared
    """
    count = 0
    def increment():
        global count
        count = count + 1
    """,
    # only read, never assigned
    """
    rate = 0.1
    def interest(x):
        return x * rate
    """,
    # parameter with the same name
    """
    size = 5
    def draw(size):
        size = size * 2
        return size
    """,
    # loop variable named like a module variable
    """
    i = 0
    def show(items):
        for i in items:
            print(i)
    """,
    # local name not defined at module level
    """
    def f():
        total = 0
        total = total + 1
        return total
    """,
    # assigned but the module-level value is never read anywhere
    """
    done = False
    def finish():
        done = True
    """,
    # a local that reuses a script variable's name and is used locally: ordinary code
    """
    radius = 50
    def draw():
        radius = random.randint(10, 200)
        turtle.circle(radius)
    print(radius)
    """,
]


@pytest.mark.parametrize("code", GLOBAL_POSITIVE)
def test_global_local_positive(code):
    check("global_local", code, 1)


@pytest.mark.parametrize("code", GLOBAL_NEGATIVE)
def test_global_local_negative(code):
    check("global_local", code, 0)


def test_global_local_rules():
    assert hits("global_local", GLOBAL_POSITIVE[0])[0].rule == "unbound_local"
    assert hits("global_local", GLOBAL_POSITIVE[1])[0].rule == "unbound_local"
    (shadow,) = hits("global_local", GLOBAL_POSITIVE[3])
    assert shadow.rule == "shadows_global" and "'done'" in shadow.message


# ---------------------------------------------------------------- 6 self confusion

SELF_POSITIVE = [
    # no parameters at all
    """
    class Dog:
        def bark():
            print("Woof")
    """,
    # first parameter is not self, body uses self
    """
    class Card:
        def setTitle(title):
            self.title = title
    """,
    # first parameter is not self (instance lands in 'width')
    """
    class Box:
        def area(width, height):
            return width * height
    """,
    # method called on the class with the instance left out
    """
    class Dog:
        def bark(self):
            print("Woof")
    Dog.bark()
    """,
    # called on the class with the other arguments but no instance
    """
    class Face:
        def setSmile(self, smile):
            self.smile = smile
    Face.setSmile(True)
    """,
]
SELF_NEGATIVE = [
    """
    class Dog:
        def bark(self):
            print("Woof")
    d = Dog()
    d.bark()
    """,
    """
    class Shape:
        @staticmethod
        def sides():
            return 0

        @classmethod
        def make(cls):
            return cls()
    Shape.sides()
    """,
    # explicit instance passed to the class-level call
    """
    class Base:
        def __init__(self, name):
            self.name = name
    class Child(Base):
        def __init__(self, name):
            Base.__init__(self, name)
    """,
    # module function without self is fine
    """
    def bark():
        print("Woof")
    bark()
    """,
    # call on something that is not a class in this file
    """
    import random
    x = random.randint(1, 5)
    """,
]


@pytest.mark.parametrize("code", SELF_POSITIVE)
def test_self_confusion_positive(code):
    check("self_confusion", code, 1)


@pytest.mark.parametrize("code", SELF_NEGATIVE)
def test_self_confusion_negative(code):
    check("self_confusion", code, 0)


def test_self_confusion_rules():
    assert hits("self_confusion", SELF_POSITIVE[0])[0].rule == "missing_self"
    (call,) = hits("self_confusion", SELF_POSITIVE[3])
    assert call.rule == "called_on_class" and "Dog.bark()" in call.message


# ---------------------------------------------------------------- 7 int vs float division

DIVISION_POSITIVE = [
    "middle = items[len(items) / 2]\n",
    "for i in range(n / 2):\n    pass\n",
    'print("*" * (width / 2))\n',
    "half = word[: len(word) / 2]\n",
    "roll = random.randint(1, sides / 2)\n",
    "row = [0] * (size / 2)\n",
    "x = grid[r][c / 2 + 1]\n",
]
DIVISION_NEGATIVE = [
    "middle = items[len(items) // 2]\n",
    "for i in range(int(n / 2)):\n    pass\n",
    "average = total / count\n",
    "x = items[round(n / 2)]\n",
    "step = values[0] / 2.0\n",
    "for i in range(10):\n    turtle.forward(size / 2)\n",
    "y = items[i] / 2\n",
]


@pytest.mark.parametrize("code", DIVISION_POSITIVE)
def test_int_division_positive(code):
    check("int_division", code, 1)


@pytest.mark.parametrize("code", DIVISION_NEGATIVE)
def test_int_division_negative(code):
    check("int_division", code, 0)


def test_int_division_message_names_the_context():
    (f,) = hits("int_division", DIVISION_POSITIVE[1])
    assert "'n / 2'" in f.message and "range()" in f.message and "'//'" in f.message
