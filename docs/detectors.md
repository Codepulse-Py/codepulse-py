# AST misconception detectors (Algorithm 3)

Rule-based detectors that flag **candidate** misconception patterns in a code state (§6.4). A
candidate becomes a misconception only with the behavioural context (#8) and manual
verification (#10). This file covers detectors 1–4 (#6); detectors 5–7 follow in #40.

```python
from detectors import analyse, StructuralAnalyzer

analyse(source).findings  # one code state
an = StructuralAnalyzer()  # one per session
an.analyse("task1.py", source)  # falls back to the file's last parseable state
```

Each `Finding` carries `detector`, `line`, `col`, `end_line`, a `message` written for a student,
and `rule`, which says which signal fired for detectors with more than one.

## Detectors

| # | Name | Fires on | Not flagged |
|---|---|---|---|
| 1 | `mutable_default` | A function or lambda default that is a list, dict or set literal, comprehension, or `list()` / `dict()` / `set()` / `sorted()` call | `None`, numbers, strings, tuples |
| 2 | `aliasing` | `b = a`, where `a` holds a new list, dict or set, then one name is mutated in place (method such as `.append`, item assignment or deletion, or `+=` on a list) and the **other** name is read afterwards | Copies (`a[:]`, `list(a)`, `a.copy()`); either name rebound before the mutation; immutable values; the other name never read again |
| 3 | `identity_literal` | `is` / `is not` against an int, float or str literal, including negative numbers and chained comparisons | `is None`, `is True`, `is False`, name-to-name `is` |
| 4 | `indentation_scope` *(exploratory)* | `loop_exits_first_pass`: every path through a `for` or `while` body ends in `return` or `break`. `unreachable_after_exit`: a statement after `return`, `break`, `continue` or `raise` in the same block | Conditional exits; placeholders (`pass`, a bare string, `...`) and a lone half-typed name after the exit |

- **Aliasing** reads each scope (the module and each function) as a straight line of events in
  execution order. It only tracks values it can see are new lists, dicts or sets. Function
  parameters of unknown type are skipped, which favours precision over recall.
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

This is a sanity check only. The counts and precision for RQ1 come from #8 and #10.

**2021, every replayed state** (962,719 states, 482,122 parseable; 511 s). Distinct
(student, assignment, file, pattern) occurrences:

| Detector / rule | Occurrences | Informal read of a sample |
|---|---:|---|
| `identity_literal` | 13 (3 students) | All genuine, e.g. `str(result) is not "YES"` |
| `indentation_scope` / `loop_exits_first_pass` | 63 | Mostly genuine, e.g. a `break` indented into a `for` body |
| `indentation_scope` / `unreachable_after_exit` | 156 | About 9 of 12 sampled were genuine, e.g. a `def` or `print` stranded under a `return`; the rest were deliberate stubs |
| `mutable_default`, `aliasing` | 0 | — |

**2019, run, submit and final snapshots only** (53,805 distinct file versions): 3 mutable
defaults (e.g. `def random_play(doors=["Goat","Car","Goat"])`), 1 identity, 40 indentation, and 0
aliasing.

Mutable defaults and aliasing are rare, as the proposal expected for the turtle-graphics and
text-logic assignments (§8.3). If #8 confirms fewer than 50 real cases, they are candidates for
the synthetic supplement (#9) or for dropping from the claims.

## Adding a detector

Create a module in `detectors/`, decorate the function with
`@register(number, "name", "Title")`, and import the module in `detectors/__init__.py`. Add at
least 3 positive and 3 negative cases to `tests/test_detectors.py`.
