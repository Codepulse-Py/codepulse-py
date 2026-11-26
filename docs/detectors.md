# AST misconception detectors (Algorithm 3)

Seven rule-based detectors that flag **candidate** misconception patterns in a code state
(final proposal, Table 3.3). A candidate becomes a misconception only with the behavioural
context (#8) and manual verification (#10). Detectors 1–4 came in #6 and 5–7 in #40.

```python
from detectors import analyse, StructuralAnalyzer

analyse(source).findings  # one code state
an = StructuralAnalyzer()  # one per session
an.analyse("task1.py", source)  # falls back to the file's last parseable state
```

Each `Finding` carries `detector`, `line`, `col`, `end_line`, a `message` written for a student,
and `rule`, which says which signal fired for detectors with more than one.

## Detectors

| # | Name | Phase | Fires on | Not flagged |
|---|---|---|---|---|
| 1 | `mutable_default` | post-run | A function or lambda default that is a list, dict or set literal, comprehension, or `list()` / `dict()` / `set()` / `sorted()` call | `None`, numbers, strings, tuples |
| 2 | `aliasing` | pre-run | `b = a`, where `a` holds a new list, dict or set, then one name is mutated in place (method such as `.append`, item assignment or deletion, or `+=` on a list) and the **other** name is read afterwards | Copies (`a[:]`, `list(a)`, `a.copy()`); either name rebound before the mutation; immutable values; the other name never read again |
| 3 | `identity_literal` | pre-run | `is` / `is not` against an int, float or str literal, including negative numbers and chained comparisons | `is None`, `is True`, `is False`, name-to-name `is` |
| 4 | `indentation_scope` *(exploratory)* | pre-run | `loop_exits_first_pass`: every path through a `for` or `while` body ends in `return` or `break`. `unreachable_after_exit`: a statement after `return`, `break`, `continue` or `raise` in the same block | Conditional exits; placeholders (`pass`, a bare string, `...`) and a lone half-typed name after the exit |
| 5 | `global_local` | post-run | `unbound_local`: a function reads a module-level name before assigning it, or uses `count += 1`, with no `global` (UnboundLocalError). `shadows_global`: a function assigns a module-level name, never reads that local, and the program reads the module-level variable elsewhere | `global`/`nonlocal` names; parameters; loop, `with` and `except` targets; a local that reuses a script variable's name and is used locally |
| 6 | `self_confusion` | post-run | `missing_self`: an instance method with no parameters, or whose first parameter isn't `self`. `called_on_class`: `Dog.bark()` on a class from the same file with the instance argument left out | `@staticmethod`, `@classmethod`; `Base.__init__(self, …)`; calls on modules |
| 7 | `int_division` | pre-run | `/` in an index or slice bound, a `range()` / `randint()` / `randrange()` argument, or a string or list repetition count | `//`; division wrapped in a call (`int(n / 2)`, `round(n / 2)`); a float operand (`n / 2.0`, `float(n) / 2`) |

- **Aliasing** reads each scope (the module and each function) as a straight line of events in
  execution order. It only tracks values it can see are new lists, dicts or sets. Function
  parameters of unknown type are skipped, which favours precision over recall.
- **Phase** comes from Table 3.3. Earliness is measured only for pre-run misconceptions (#27),
  and it is stored on each registered detector (`REGISTRY[name].phase`).
- **Global vs local.** `unbound_local` is the Table 3.3 signature, "reads and assigns without
  `global`". `shadows_global` is deliberately narrow. A first version that flagged any function
  assigning *and* using a module-level name mostly hit ordinary locals, such as a function's
  own `radius` or `word1`, so it now needs the local to be unused and the global to be read
  elsewhere. Functions nested in functions are skipped.
- **Indentation scope** is exploratory because intent isn't visible in the code (§8.3). The two
  rules are structural symptoms of a mis-indented statement. The placeholder exclusions exist
  because, in the 2021 data, those cases came from starter templates (`pass  # Remove this
  line…`) and from students part-way through typing a line, not from indentation.

## Code that doesn't parse

About half of all replayed states don't parse, because students are mid-edit. `analyse()`
returns `parsed=False` with the error message. `StructuralAnalyzer` keeps each file's last
parseable state and reports its findings with `stale=True`, so a detection isn't lost while a
line is being typed. Warnings that Python emits while parsing student code, such as an
`invalid escape sequence` `SyntaxWarning`, are suppressed.

## First run on real data

This is a sanity check only. The counts and precision for RQ1 come from #8 and #10, where
transient states, such as a name caught half-typed, are merged into episodes.

**2021, every replayed state** (962,719 states, 482,122 parseable). Detectors 1–4 took 511 s and
5–7 took 484 s. Distinct (student, assignment, file, pattern) occurrences:

| Detector / rule | Occurrences | Informal read of a sample |
|---|---:|---|
| `identity_literal` | 13 (3 students) | All genuine, e.g. `str(result) is not "YES"` |
| `indentation_scope` / `loop_exits_first_pass` | 63 | Mostly genuine, e.g. a `break` indented into a `for` body |
| `indentation_scope` / `unreachable_after_exit` | 156 | About 9 of 12 sampled were genuine, e.g. a `def` or `print` stranded under a `return`; the rest were deliberate stubs |
| `global_local` / `unbound_local` | 34 | Genuine, e.g. `count += 1` in a recursive search function with a module-level `count` |
| `global_local` / `shadows_global` | 14 | Mostly genuine, e.g. `count = 1` reset inside the function; some are incomplete functions |
| `self_confusion` / `missing_self` | 138 (15 students across both `self` rules) | Mostly genuine, e.g. `def __init__():` with `self.x` in the body, or the instance named `blobber`; some are names caught half-typed |
| `self_confusion` / `called_on_class` | 31 | Genuine, e.g. `Face.draw_face()` instead of calling it on an object |
| `int_division` | 89 (24 students) | Genuine, e.g. `range(1, inti/2 + 1)`, `word[len(word) / 4 :]` |
| `mutable_default`, `aliasing` | 0 | — |

**2019, run, submit and final snapshots only** (53,805 distinct file versions): 3 mutable
defaults (e.g. `def random_play(doors=["Goat","Car","Goat"])`), 1 identity, 40 indentation,
14 `unbound_local`, 14 `shadows_global`, 40 int division, and 0 aliasing or `self` confusion.
The 2019 assignments don't use classes, so a zero for `self` is expected there.

Mutable defaults and aliasing are rare, as the proposal expected for the turtle-graphics and
text-logic assignments. If #8 confirms fewer than 50 verified real cases across both cohorts,
they are reported as exploratory, with synthetic data (#9, validated by #75) as the fallback.

## Adding a detector

Create a module in `detectors/`, decorate the function with
`@register(number, "name", "Title", phase="pre-run" | "post-run")`, and import the module in
`detectors/__init__.py`. The registry rejects an unknown phase and a duplicate name or number.
Add at least 3 positive and 3 negative cases to `tests/test_detectors.py`.
