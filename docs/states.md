# Behavioural states (Algorithm 1, #5)

Every interval between consecutive events of a session is labelled with one of seven states
(final proposal Table 3.1). The implementation is `features/states.py`. The time spent in each
state per window is a feature group in Algorithm 2 (`docs/features.md`).

## Operational definitions

Only **edit** and **run** events count, from every file of the session. That is what both
cohorts log and what the live editor sends, so a state means the same thing everywhere. 2021-only
rows, such as arrow-key `X-Keystroke` and `X-Action` events, are ignored. The rules apply in this
order:

| # | State | Rule |
|---:|---|---|
| 1 | RUNNING | From a run start until the run ends: the logged end in 2021 (the exit-code row) and the live editor, otherwise 10 s (2019 does not log run ends). If the next event comes later, the rest of the gap is labelled by rules 2–7 |
| 2 | PASTING | The interval ends at an insert of more than 50 characters |
| 3 | FLAILING | The interval ends at an edit inside a delete/retype cycle (below) |
| 4 | BURST_TYPING | Under 100 ms between events |
| 5 | TYPING | 100 ms to 2 s |
| 6 | PAUSE | 2 to 10 s |
| 7 | DEEP_THINKING | 10 s or more |

**TYPING extended to 2 s.** Table 3.1 gives TYPING as 100–500 ms and PAUSE as 2–10 s, which
leaves 0.5–2 s unassigned. Gaps of that length are typing with short hesitations, so TYPING
covers 100 ms to 2 s.

**FLAILING.** An edit is in a delete/retype cycle when, among the edits to the same file in the
last 10 s that are within 20 characters of it, the student switched from deleting to inserting at
least 3 times. One typo fix (type, backspace, retype) is a single switch and is not flailing.
Rewriting the same spot again and again is.

**RUNNING ends with the run.** An earlier version labelled the whole gap after a run as RUNNING.
That counted a student who ran the code and then stopped for ten minutes as "running" for ten
minutes, and RUNNING took 32% of all window time in 2021. Bounding it by the run's real duration
(2021 median 4.6 s, 90th percentile 74 s for interactive programs) brings it to 13.8%.

## Distribution

| State | 2021 intervals | % | Median | 2019 intervals | % | Median |
|---|---:|---:|---:|---:|---:|---:|
| BURST_TYPING | 213,225 | 20.9 | 0.03 s | 813,454 | 15.8 | 0.07 s |
| TYPING | 629,070 | 61.7 | 0.23 s | 3,596,330 | 69.8 | 0.20 s |
| PAUSE | 83,200 | 8.2 | 3.44 s | 302,223 | 5.9 | 3.39 s |
| DEEP_THINKING | 37,545 | 3.7 | 26.8 s | 108,182 | 2.1 | 24.1 s |
| FLAILING | 28,949 | 2.8 | 0.16 s | 251,673 | 4.9 | 0.17 s |
| PASTING | 2,482 | 0.2 | 0.03 s | 8,705 | 0.2 | 2.25 s |
| RUNNING | 24,449 | 2.4 | 5.94 s | 74,185 | 1.4 | 10.0 s |

Share of window time (state seconds summed over all active windows):

| State | 2021 | 2019 |
|---|---:|---:|
| BURST_TYPING | 0.5% | 0.9% |
| TYPING | 15.6% | 23.9% |
| PAUSE | 20.5% | 22.1% |
| DEEP_THINKING | 48.3% | 40.6% |
| FLAILING | 0.6% | 1.4% |
| PASTING | 0.7% | 1.2% |
| RUNNING | 13.8% | 9.9% |

Notes:

- **Editor differences.** 2021 (PyCharm) has more BURST_TYPING, because bulk operations and
  autocomplete log several edits in the same millisecond. 2019 (Phanon, no autocomplete) has more
  TYPING and FLAILING, because students type and fix every character themselves. This is the
  editor domain shift in Table 3.7. It is one reason the features use timing and edit ratios,
  not key codes.
- **2019 RUNNING** is the assumed 10 s per run (median exactly 10.0 s), because its run ends are
  not logged.
