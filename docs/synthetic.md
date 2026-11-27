# Synthetic windows for rare misconceptions (#9)

> **Rejected by validation (#75).** Every batch fails the real-vs-synthetic discriminator check
> (AUROC ≥ 0.99, against a limit of 0.70, even on behaviour alone), after three generator
> revisions (v2–v4). Under §3.2.1 this data is **not used for training**, and the four classes
> are exploratory. See [`docs/synthetic_validation.md`](synthetic_validation.md). The generator
> stays in the repository so the result can be reproduced, and in case a revised approach is
> agreed.

The occurrence count (`docs/rq1.md`) left four misconceptions far below the 50-case gate:
mutable default (4 real candidates), aliasing (0), identity vs equality (5) and `self` confusion
(29). This dataset gives the model **training** examples for them.

> **What synthetic data can and cannot do.** Under the final proposal (§3.2.1, Table 3.7),
> synthetic examples are used **in training only**, never in validation or test folds. The four
> classes above therefore stay **exploratory** in the results, because there are no real held-out
> cases to measure them on. Synthetic data lets the 8-label model learn them and keeps the
> pipeline complete. It does not turn them into main-claim classes. Each batch must also pass
> the real-vs-synthetic checks in #75 (the panel's comment) before it is used.

## Method change from the proposal: needs supervisor sign-off

The proposal says synthetic windows are produced by *prompting a language model with the
misconception definition and real seed examples*. This implementation instead **injects the
misconception into real student code with a minimal, rule-based edit**. No language model is
involved. Reasons:

- **Real context.** Each example is real novice code, with real names, comments, style and
  surrounding errors, changed only where the misconception sits. That should make it harder for
  the #75 discriminator to separate synthetic from real than freshly generated code would be.
- **Reproducible.** Generation is deterministic given a seed (`--seed`, default 1400) and needs
  no model or API.
- **Exact signature.** Every example is checked with the same detector used to mine the real
  data.

The proposal's other requirements are kept: a code state with a simulated edit trace, seeds from
training data only, 100–200 per rare class, training-only use, and #75 validation.

## How an example is built (`synthetic/`)

1. **Seed.** A real file at a real run, or at the end of a session, in the **2021 cohort**, whose
   code parses and does not already show the misconception. 2019 is never used: it is the
   cross-cohort test cohort (Stage C).
2. **Real lead-in.** The file is replayed to 45 s before the seed run, and the student's **real
   logged rows** for that file are copied unchanged up to the run. The 30 s *before* each
   flagged state is therefore genuine behaviour. 27,217 of the 70,246 rows are real.
3. **Injection.** The misconception is typed into the student's code at **the student's own
   typing speed**, using keystroke gaps and long pauses sampled from their 2021 logs. Typed
   characters produce `File.Edit` + `X-Keystroke` rows, and deletions produce `Backspace`
   actions, as in the 2021 PyPhanon logs.
4. **Behaviour.** One to three cues from Table 3.3 and the Appendix A codebook follow, so each
   window has the structure **and** a behavioural indicator, as the codebook requires:

   | Misconception | Cues (chosen at random) |
   |---|---|
   | Mutable default | repeated runs; long pause; `print(...)` added inside the function |
   | Aliasing | pause after the alias assignment; `print` of both names; repeated runs |
   | Identity vs equality | trial switching `is` → `==` → `is`; repeated runs; long pause |
   | `self` confusion | `self` added back then removed again; repeated runs; long pause |

5. **QC.** Every synthetic session is replayed and mined **with the same code as the real
   data**. It is kept only if:
   - replay is exact, with no `DeleteText` mismatches;
   - a persistent episode of the intended misconception starts after the real lead-in.

### Injection methods

| Misconception | Method | Grounded? | What changes |
|---|---|---|---|
| Mutable default | `moved_local` | yes | A repeatedly-called function's `acc = []` moves into a default: `def f(x, acc=[])` |
| Mutable default | `accumulator_param` | **no: 2 invented lines** | A repeatedly-called function gets a new `history=[]` parameter and an `.append(...)` line |
| Aliasing | `alias_then_mutate` | yes, plus one line | `alias = xs` is inserted after `xs` is created, a later `xs.append(...)` becomes `alias.append(...)`, and `xs` is still read afterwards |
| Identity vs equality | `eq_to_is` | yes | `==` / `!=` against an int or str literal becomes `is` / `is not` |
| `self` confusion | `remove_self` | yes | `self` is removed from a method's parameters |
| `self` confusion | `call_on_class` | yes | `obj.method()` becomes `Cls.method()`, where `obj = Cls(...)` |

- **Mutable defaults need repeated calls.** Seeds are restricted to functions called at two or
  more sites, inside a loop, or recursively. A default on a `main()` called once never
  accumulates, and the codebook would label it NONE.
- **Only 11 grounded mutable-default examples exist.** In all of the 2021 data, only 10 distinct
  functions are both called repeatedly *and* build a local list. The other 139 mutable-default
  examples use `accumulator_param`. Grounded methods are always tried first (two-pass
  generation), and every item records its `method`, so #75 can test the methods separately and
  drop `accumulator_param` if it fails.

## Result (seed 1400, 150 requested per class, generator v1)

The current generator is v4 (`GENERATOR_VERSION`):

- **v2** adds run outcomes;
- **v3** samples seeds from any moment of a session, auto-closes brackets and adds typos;
- **v4** tunes the typo rate and the cues.

v4 keeps 149 / 149 / 149 / 148 items (mutable default, aliasing, identity, `self`). Mutable
default is 8 grounded `moved_local` plus 141 `accumulator_param`. The table below is the original
v1 run.

| Misconception | Kept | Seed students | Assignments | Distinct seed files | Max items per student | Median rows per item |
|---|---:|---:|---:|---:|---:|---:|
| Mutable default | 150 (11 grounded) | 33 | 8 | 86 | 14 | 136 |
| Aliasing | 150 | 31 | 5 | 71 | 11 | 190 |
| Identity vs equality | 150 | 38 | 8 | 106 | 10 | 61 |
| `self` confusion | 149 | 30 | 6 | 63 | 15 | 55 |

- Overall, 599 of 600 items passed QC. One was rejected because no persistent episode formed.
- Each class has 1, 2 or 3 cues in roughly equal thirds.
- No seed student supplies more than 10% of a class (15 items). No seed file is used more than
  3 times.
- The classes concentrate where the code allows them: `self` in Assign9 (107 of 149, the first
  class assignment), aliasing in Assign11–12 (lists of objects and cards).

## Using it

```bash
python scripts/replay_cohort.py 2021      # if the snapshots are not built yet
python scripts/make_synthetic.py          # about 1.5 minutes
```

The outputs go to `data/interim/synthetic/` (git-ignored):

| File | Contents |
|---|---|
| `keystrokes.csv` | One session per item, in 2021 ProgSnap2 columns. `SubjectID` is `SYN-NNNN`. Generated rows have `ToolInstances = synthetic`; the copied lead-in rows keep the original value. |
| `manifest.csv` | One row per item: `synthetic=True`, misconception, rule, method, a note on the edit, seed student, assignment, file and event, `seed_ms`, `injected_at_ms`, cues, generator version and seed. |
| `runs.csv` | Run records in the 2021 `runs.csv` format, with the exception each run would raise (generator v2: a `TypeError` for `self` confusion, a `SyntaxError` for unparseable code). |
| `summary.json` | Counts requested, generated, kept by method and rejected. |

**Training-fold rule.** When training fold *k*, drop every item whose seed student is one of
fold *k*'s test students, so no test student's code reaches training:

```python
from synthetic.generate import usable_for_training

train_synthetic = usable_for_training(manifest, test_subjects_of_fold_k)
```

Report every result with and without synthetic data (#75 (d)). The result without synthetic
data is primary.

## Limitations

- The 30 s **after** injection is simulated. Cue timing uses the student's own rhythm, but the
  choice and order of cues is scripted. The #75 discriminator test is the check on this.
- The injected misconception was never actually held by that student. The label is true *by
  construction*: the code has the structure, and the trace shows a codebook indicator.
- Only one file of the session is in each synthetic window. Other files the program imports are
  not included, which matches what the detectors look at.
