# Data card: Edwards CS1 keystroke datasets

Two public keystroke datasets from CS1 (CS 1400) at Utah State University, released with
Edwards et al., *Review of CSEDM Data and Introduction of Two Public CS1 Keystroke Datasets*,
Journal of Educational Data Mining 15(1), 2023.

| | 2021 cohort | 2019 cohort |
|---|---|---|
| DOI | [10.7910/DVN/BVOF7S](https://doi.org/10.7910/DVN/BVOF7S) | [10.7910/DVN/6BPCXN](https://doi.org/10.7910/DVN/6BPCXN) |
| Role in CodePulse-Py (§7.1) | Train / validation / held-out replay test (70/10/20 by student) | Cross-cohort generalisation test, no retraining |
| Term | Fall 2021 | Spring + fall 2019 |
| Editor | PyCharm + PyPhanon plugin | Phanon (browser, CodeMirror, no autocomplete) |
| Assignments | 8 (`Assign6`–`Assign13`) | 5 (`p4`–`p8`, suffixed `s`/`f` by term) |
| Participants (JEDM 2023) | 44 | 505 |
| Subjects in released `keystrokes.csv` | 44 | 487 (see [Known issues](#known-issues)) |
| Events in `keystrokes.csv` | 2,088,866 | 5,130,297 |
| Time range (UTC) | 2021-10-08 → 2022-01-28 | 2019-01-18 → 2020-05-23 |
| Extra metadata | grades, exams, final score, ACT, HS GPA, major (`students.csv`); run output (`runs1.csv`, `runs2.csv`) | run input/output inline; survey keystrokes; raw uncleaned log |

All counts above come from `scripts/validate_data.py` against the files pinned in
[`data/MANIFEST.md`](../data/MANIFEST.md).

## Getting the data

The data is not committed. Download both releases from Harvard Dataverse and place (or
symlink) each unpacked folder under `data/raw/`, which is git-ignored:

```bash
ln -s /path/to/CS1_Keystroke_2021_dataset data/raw/2021
ln -s /path/to/CS1_Keystroke_2019_dataset data/raw/2019
pip install -r requirements-dev.txt
python scripts/validate_data.py
```

The validator never writes to `data/raw/`. It checks:

1. every file's size and SHA-256 against `data/MANIFEST.md`, with no missing or extra files;
2. the MainTable header matches the exact column list below;
3. every row parses, `EventID` is a unique integer, and core columns are never blank;
4. every `EventType` is one of the known types;
5. event, subject and assignment counts are within the paper's figures, the `AssignmentID`s
   match `due.csv`, and timestamps fall inside the collection period.

It exits non-zero on any failure. `--skip-hash` skips step 1 for a faster rerun.

## Format

Both MainTables (`keystrokes.csv`) are "mostly compliant" ProgSnap2 v8 (Dec 2020). One row is one
event. Sort by `ClientTimestamp` **then** `EventID`, because some consecutive events share a
timestamp.

Deviations from ProgSnap2 (from the dataset readmes):

- `SourceLocation` is a single 0-based character offset into the linearised file, not
  `text:line:col`.
- `CodeStateID` is always empty. Code state is not stored, so code has to be rebuilt by replaying
  `File.Edit` events (#3).
- `ClientTimestamp` is Unix epoch milliseconds, UTC (Java `System.currentTimeMillis()`).
- `X-Compilable` is `1` if the file had no syntax error after the event, `0` otherwise.

### 2021 columns (14)

`EventID`, `SubjectID`, `AssignmentID`, `CodeStateSection`, `EventType`, `SourceLocation`,
`EditType`, `InsertText`, `DeleteText`, `X-Metadata`, `ClientTimestamp`, `ToolInstances`,
`CodeStateID`, `X-Compilable`

| EventType | Count |
|---|---:|
| `File.Edit` | 971,220 |
| `X-Keystroke` | 618,843 |
| `X-Action` | 418,541 |
| `Run.Program` | 54,561 |
| `X-ReplayAction` | 16,247 |
| `X-Paste` | 3,856 |
| `X-Copy` | 3,256 |
| `X-Attention` | 2,342 |

In 2021, keystrokes (`X-Keystroke`) are logged separately from the file edits (`File.Edit`) they
cause. `CodeStateSection` holds 158 distinct file names. Events per student: median 46,987,
range 2,035–122,334.

| Assignment | Events | Students |
|---|---:|---:|
| Assign6 | 529,884 | 43 |
| Assign7 | 394,912 | 35 |
| Assign8 | 308,825 | 34 |
| Assign9 | 318,495 | 32 |
| Assign10 | 73,570 | 32 |
| Assign11 | 132,483 | 30 |
| Assign12 | 258,843 | 33 |
| Assign13 | 71,854 | 23 |

### 2019 columns (19)

`EventID`, `SubjectID`, `AssignmentID`, `CodeStateSection`, `X-Task`, `EventType`,
`X-Keystroke`, `InsertText`, `DeleteText`, `SourceLocation`, `ClientTimestamp`, `EditType`,
`X-RunInput`, `X-RunOutput`, `X-RunHasError`, `X-RunUserTerminated`, `X-RawAssignmentID`,
`X-Term`, `X-Compilable`

| EventType | Count |
|---|---:|
| `File.Edit` | 5,039,755 |
| `Run.Program` | 75,112 |
| `X-SwitchTask` | 12,104 |
| `Submit` | 3,326 |

In 2019, keystrokes and edits are not separated. Each keystroke is a `File.Edit` with
`X-Keystroke` set, and edits that no keystroke caused have `X-Keystroke` empty. Each assignment
has two files, `task0.py` and `task1.py`. `AssignmentID` carries the term (`p4s`, `p4f`); use
`X-RawAssignmentID` for the assignment itself, because the assignments were identical across
terms.

| Assignment | Spring events | Spring students | Fall events | Fall students |
|---|---:|---:|---:|---:|
| p4 | 238,252 | 168 | 222,944 | 172 |
| p5 | 406,456 | 183 | 388,160 | 174 |
| p6 | 430,717 | 126 | 573,296 | 140 |
| p7 | 763,444 | 179 | 955,812 | 183 |
| p8 | 490,409 | 140 | 660,807 | 117 |

### Other files

| File | Cohort | Notes |
|---|---|---|
| `due.csv` | both | Due date per `AssignmentID`, including epoch ms in UTC |
| `students.csv` | 2021 | One row per student (44): assignment and exam scores, final score, major, ACT, HS GPA. The 2019 version was withdrawn by the authors. |
| `runs1.csv`, `runs2.csv` | 2021 | Run records (`Action = r`) and output lines (`Action = o`, drop these for run counts); about 2.4 GB in total |
| `keystrokes-survey.csv` | 2019 | Same schema as `keystrokes.csv`. End-of-fall free-text survey (178 students), not programming. |
| `keystrokes-raw.csv` | 2019 | 9.0 M events before cleaning. Some logs are corrupted, so use it only for single-key or digraph timing, **never** to rebuild code. |
| `Assignment Descriptions/`, starters | both | Task PDFs and starter code |
| `informed-consent.pdf` | both | Consent form shown to participants |

## Cross-validation folds

The 2021 cohort is evaluated with **student-grouped five-fold cross-validation** (final proposal
§3.2.4). With 44 students, a single fixed split would leave too few test students for stable
per-class results, so every student is tested exactly once. The folds are frozen in
[`data/folds.json`](../data/folds.json). The 2019 cohort is not split, because all of it is held
out for the cross-cohort test (Stage C).

| Fold | 0 | 1 | 2 | 3 | 4 |
|---|---:|---:|---:|---:|---:|
| Students | 9 | 9 | 9 | 9 | 8 |
| Sessions | 46 | 59 | 54 | 55 | 48 |
| Share of 2021 events | 19.7% | 23.0% | 19.5% | 18.4% | 19.4% |

**Rounds.** In round *k*, fold *k* is the test set and fold *k + 1* (mod 5) is held back for
threshold tuning (#17). The other three folds (26–27 students) are the training set. Every
student is tested once and used for tuning once. Results are reported as mean ± sd over the five
rounds.

**Stratification.** Folds are balanced on two things:

1. **Grade tier:** thirds (tertiles) of `FinalScore` from `students.csv`, namely low 14.7–90.2,
   mid 90.8–95.7 and high 95.7–100.6. The 3 students with no final score form a fourth tier.
2. **Candidate misconception episodes per student** (#8). Many episodes come from a few students.
   Balancing on grade tier alone left one fold with a single global-vs-local student and 2
   int-division episodes, which could become zero after verification and make per-class F1
   undefined in that fold.

   Students are placed one at a time, those holding the largest share of the rarest classes
   first, each into the fold that keeps every class's counts and every tier's counts most even
   (iterative stratification). This uses candidate counts only, not verified labels or model
   output, and it was fixed before any modelling.

Persistent 2021 candidate episodes per test fold (students in brackets):

| Misconception | 0 | 1 | 2 | 3 | 4 |
|---|---:|---:|---:|---:|---:|
| Indentation scope | 38 (6) | 20 (7) | 33 (7) | 28 (7) | 28 (8) |
| Int vs float division | 7 (5) | 9 (5) | 8 (4) | 9 (4) | 10 (5) |
| Global vs local | 10 (2) | 12 (4) | 7 (5) | 9 (3) | 7 (3) |
| `self` confusion | 5 (2) | 5 (2) | 7 (2) | 6 (3) | 6 (4) |
| Identity vs equality | 1 (1) | 2 (1) | 1 (1) | 0 | 0 |

Identity has only 3 students in 2021, so it can't appear in every fold. It is exploratory anyway
(`docs/rq1.md`).

- **Check it.** `python scripts/make_folds.py` rebuilds the folds from `students.csv` and the RQ1
  episodes, and fails if they differ from the frozen file. Regenerate (`--write`) only on
  purpose: every model and result depends on the folds.
- **Use it.**
  ```python
  from splits.manifest import all_splits

  for r in all_splits():  # r.train, r.tune, r.test
      ...
  ```
  Training code should call `assert_no_leakage(train_subjects, eval_subjects)`. Synthetic data
  is filtered per round with `usable_for_training(manifest, r.test)`, which keeps between 428
  and 501 of the 599 items depending on the round.
- **Leakage tests in CI.** `tests/test_splits.py` checks on every push that:
  - the five folds are disjoint and cover all 44 students;
  - in every round, train, tune and test share no student;
  - every student is tested once and tuned once;
  - every test fold has candidates of each main-claim class.
- **Known limitation.** The per-round tuning set is one fold (8–9 students), so the tuned
  threshold (#17) is still estimated from few students. Report its spread across rounds.

## Known issues

- **2019 subject count.** The JEDM paper reports 505 participants, but the released
  `keystrokes.csv` has 487 distinct `SubjectID`s. The IDs run from `S000` to `S516` with gaps.
  Counted as student-term pairs there are 503, because 16 students took the course in both terms.
  Taking all 2019 files together (`keystrokes-raw.csv` and the survey), there are still only 497.
  Most likely some consenting students have no retained events after cleaning. The validator pins
  487 and prints a warning. Report 487 as the analysable population.
- **Assignment coverage is partial.** For 2019, the paper says 499 students completed p4, but
  only 331 distinct students have p4 events (340 student-terms). The instructor could not enforce
  the logged editor, so some students never used it. Others wrote code elsewhere and pasted it in,
  which shows up as one large paste with few edits after it.
- **Late accesses.** A few fall 2019 students (S117, S193, S243) reopened p8 in 2020, and some
  2021 `Assign6` events run to January 2022. Filter to the due date when measuring time on task.
- **2019 `Submit` events.** There are 3,326 `Submit` events, while the paper's Table 2 lists
  3,126 submissions. Resubmissions probably explain the difference. Don't use `Submit` counts as
  the number of submissions without de-duplicating.

## Ethics and use

Both datasets are de-identified and publicly released under informed consent, and were
collected under Utah State University IRB protocols. The proposal uses them offline only, so no
new data is collected. Do not try to re-identify students. The authors note that some identifying
keystrokes may have been missed during de-identification. Follow the terms of use on the
Dataverse pages.
