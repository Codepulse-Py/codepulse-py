# RQ1: candidate occurrences per misconception

> **RQ1.** How many genuine instances of each of the seven misconceptions exist in the public
> Edwards CS1 keystroke datasets, and can they be labelled reliably (Cohen's κ ≥ 0.80)?

This document answers the **counting** half of RQ1 with *candidate* episodes, which closes SO1.
The "genuine" and "reliably" halves come from manual verification (#10) and the second
annotator (#11). Counts here are therefore **upper bounds** on verified cases.

Status: for supervisor review (acceptance criterion of #8).

## Method

1. **Every code state.** Each session of both cohorts was replayed (#3), and all seven
   detectors (#6, #40) were run on every distinct code state: 962,719 states in 2021 and about
   5.0 million in 2019. Unparseable states keep the file's last parseable findings.
2. **Episodes.** A pattern stays on screen across many states, so findings are grouped into
   episodes (`mining/episodes.py`):
   - An episode is one continuous stretch during which a detector rule flags a file.
   - A gap of up to 30 s, one window length, is bridged.
   - Simultaneous instances of the same rule in one file count once.
3. **Persistent episodes.** An episode is **persistent** if it lasted at least 10 s (one window
   stride, so it is visible to at least one detection window) or the student ran the code while
   it was present. Fleeting states caught mid-typing are excluded. **The gate uses persistent
   episodes.**
4. **Origin.** Each episode records whether its first flagged state came from typing, a paste
   (> 50 characters, the PASTING threshold in Table 3.1), or 2019 starter content. None of the
   2021 starter files trigger a detector.
5. **Behavioural context.** Each episode carries the session's activity in the 30 s before and
   after its start: edits, characters inserted and deleted, runs and the longest pause. The
   full feature vectors come from Algorithm 2 (#7).

Reproduce (about 5 minutes on 12 worker processes):

```bash
python scripts/replay_cohort.py 2021 && python scripts/replay_cohort.py 2019   # if not built yet
python scripts/mine_candidates.py
```

The outputs go to `data/interim/rq1/` (git-ignored): `<cohort>/episodes.parquet`,
`counts.csv` and `summary.json`.

## Results

601 candidate episodes, of which **448 are persistent**.

| # | Misconception | Phase | 2021 | 2019 | **Both (persistent)** | Students | Typed / pasted |
|---|---|---|---:|---:|---:|---:|---|
| 1 | Mutable default argument | post-run | 0 | 4 | **4** | 3 | 1 / 3 |
| 2 | Variable aliasing | pre-run | 0 | 0 | **0** | 0 | — |
| 3 | Identity vs equality | pre-run | 4 | 1 | **5** | 4 | 5 / 0 |
| 4 | Indentation scope *(exploratory detector)* | pre-run | 147 | 72 | **219** | 76 | 214 / 5 |
| 5 | Global vs local scope | post-run | 45 | 44 | **89** | 35 | 83 / 6 |
| 6 | `self` confusion | post-run | 29 | 0 | **29** | 13 | 29 / 0 |
| 7 | Integer vs float division | pre-run | 43 | 59 | **102** | 62 | 101 / 1 |

Columns 2021 and 2019 count persistent episodes. Students are distinct students with at least
one persistent episode; 2021 IDs (`StudentN`) and 2019 IDs (`SNNN`) don't overlap.

By rule:

- indentation scope: 99 `loop_exits_first_pass`, 120 `unreachable_after_exit`
- global vs local: 60 `unbound_local`, 29 `shadows_global`
- `self` confusion: 18 `called_on_class`, 11 `missing_self`

In the four larger classes, 58–77% of persistent episodes were present while the student ran the
code; all four mutable-default episodes were.

**Where they occur.** In 2021, indentation clusters in Assign6–7, global vs local in Assign13
(recursive search with a module-level `count`), `self` in Assign9 (the first class assignment)
and int division in Assign6 (factor loops with `range(n / 2)`). In 2019, every persistent
candidate is in p6–p8, mostly p8; p4 and p5 have none. The 2019 assignments use no classes, so
zero `self` cases there is structural, not a detector failure.

### Sensitivity to the persistence threshold

| Misconception | All episodes | ≥ 10 s or run *(used)* | ≥ 30 s or run | ≥ 60 s or run |
|---|---:|---:|---:|---:|
| Mutable default | 4 | 4 | 4 | 4 |
| Aliasing | 0 | 0 | 0 | 0 |
| Identity vs equality | 5 | 5 | 4 | 4 |
| Indentation scope | 334 | 219 | 172 | 161 |
| Global vs local | 110 | 89 | 71 | 66 |
| `self` confusion | 38 | 29 | 22 | 22 |
| Int vs float division | 110 | 102 | 85 | 83 |

The gate decision is the same under every threshold. No class moves across 50.

## The 50-case gate (provisional)

The final proposal (§3.2.1): *a misconception with fewer than 50 verified real cases across both
cohorts is reported as exploratory and excluded from the main claims.* Verified cases can only be
fewer than candidates, so:

| Misconception | Persistent candidates | Decision | Precision needed to stay ≥ 50 |
|---|---:|---|---:|
| Indentation scope | 219 | **Provisionally above**, pending verification (#10) | ≥ 23% |
| Int vs float division | 102 | **Provisionally above**, pending verification (#10) | ≥ 49% |
| Global vs local scope | 89 | **Provisionally above**, pending verification (#10) | ≥ 56% |
| `self` confusion | 29 | **Below**: exploratory | — |
| Identity vs equality | 5 | **Below**: exploratory | — |
| Mutable default argument | 4 | **Below**: exploratory | — |
| Variable aliasing | 0 | **Below**: exploratory | — |

"Precision needed" is the share of candidates that must verify as genuine for the class to stay
at or above 50.

## What this means for the plan (for supervisor discussion)

1. **At most three misconceptions can support the main claims:** indentation scope, int vs float
   division, and global vs local. This holds only if #10 confirms at least the precision above.
   Global vs local has the least room. Indentation scope is also the detector the proposal marks
   exploratory (Tables 3.3 and 3.7), so its verification matters most.
2. **Four misconceptions fall below the gate on real data alone:** mutable default, aliasing,
   identity and `self`. Synthetic data (#9, validated against real data in #75, as the panel
   asked) can support *training* for them. Synthetic data is never used for testing, though, so
   these four stay exploratory either way. The main objective's "macro-F1 across seven
   misconceptions" can't be measured on real held-out data for them.
3. **Options to agree with the supervisor:**
   - **(a) Recommended.** Report the main results on the classes that pass verification, plus
     NONE. Report the other four as exploratory, with synthetic-trained results clearly
     separated. This keeps the timeline. The main objective's wording ("seven misconceptions")
     would need adjusting.
   - **(b)** Activate the contingency collection path (#76 ethics, #77 cohort-bias controls),
     with tasks designed to elicit the rare misconceptions (lists, defaults, classes). This
     gives real test cases but needs ethics approval, recruitment and the cohort-bias controls,
     and would push SO2–SO3.
   - **(c)** Not recommended: relax the 50-case rule. This contradicts the defended proposal.
4. **Independence of cases.** Two 2019 students (S261, S364) have the identical line `def
   random_play(doors = ["Goat","Car","Goat"], switch = True):`, mostly pasted, which suggests a
   shared source. Cases are not guaranteed independent. Student-grouped folds (#74) handle this
   *within* a cohort, but shared code across students can't be detected in general.

## Limitations of these counts

- **Candidates, not verified cases.** The structural pattern is present; whether the student
  holds the misconception needs the codebook judgement (#10, Appendix A).
- **Detector recall is unknown.** Genuine misconceptions with no matching structure are missed.
  The random unflagged sample in #10 estimates this.
- **The episode rule under-counts.** Two instances of one rule in the same file at the same time
  are one episode. A different gap or persistence choice changes the totals; the sensitivity
  table shows the gate decision does not change.
- **Single institution.** Both cohorts come from one university's CS1, with turtle-graphics and
  text-logic assignments that rarely call for mutable defaults or aliasing.

## Next steps

- **#10:** stratified verification sample from `episodes.parquet` (by class, cohort and rule),
  plus a random unflagged sample.
- **#74:** student-grouped folds. Check that each above-gate class has candidates in every fold.
- **#9 / #75:** synthetic windows for the four below-gate classes, training folds only.
