# Window features (Algorithm 2, #7)

For every window, `features/windows.py` computes a behavioural and structural vector `b_k` (52
features) and the seven detector flags `a_k` (final proposal §3.1.2, Table 3.2). The language
model receives them as short labelled numbers, never raw timestamps.

```bash
python scripts/extract_features.py                      # 2021 and 2019 (about 1.5 minutes)
python scripts/extract_features.py --cohort synthetic   # the #9 synthetic windows
```

The output is `data/interim/features/<cohort>/windows.parquet` (git-ignored): one row per
window, with `subject`, `assignment`, `window_end_ms`, `focus_file`, the 52 features and the 7
`flag_*` columns.

| Cohort | Windows | Sessions | Time |
|---|---:|---:|---:|
| 2021 | 168,831 | 261 | 31 s |
| 2019 | 564,541 | 1,578 | 56 s |
| Synthetic (#9) | 5,107 | 599 | about 1 s |

## Windows

Windows follow eq. 3.1: `W_k = (t_k − 30 s, t_k]`, with `t_k = t_0 + 10 s · k`, where `t_0` is
the session's first edit or run. Only windows containing at least one edit or run are kept. A
2021 session can span several days, and the idle stretches would otherwise produce thousands of
empty windows. Each event therefore falls in exactly three windows; this was checked on 2021,
where the window edit counts sum to 3× the cohort's edits, apart from edits in a session's first
10 s.

## Editor independence

Every feature is computed only from what both cohorts log **and** what the live editor (#21)
will send:

- edits: the offset, the inserted text and the deleted text;
- run starts, with their outcome (errored, stopped, exception type, end time);
- the code reconstructed from the edits (#3).

No feature uses key codes, cursor events or anything PyCharm- or Phanon-specific. Cursor
movement is the distance between consecutive edit positions in the same file, as the final
proposal specifies.

## Features

### Timing (8)

| Feature | Definition |
|---|---|
| `n_edits` | Edit events in the window |
| `iei_mean_s`, `iei_median_s`, `iei_std_s` | Inter-edit intervals inside the window, in seconds (NaN below 2 or 3 edits) |
| `longest_gap_s` | Longest stretch with no edit or run, including the window's edges |
| `pauses_2_10s`, `pauses_over_10s` | Gaps between events ending in the window that last 2–10 s, or 10 s and more |
| `secs_since_last_edit` | Window end minus the last edit (possibly before the window) |

### Editing (11)

| Feature | Definition |
|---|---|
| `n_inserts`, `n_deletes`, `n_replaces` | Edits that only insert, only delete, or do both |
| `chars_inserted`, `chars_deleted`, `net_chars` | Characters added, removed, and the difference |
| `deletion_ratio` | Deleted / (inserted + deleted) |
| `edit_churn` | (Inserted + deleted) / max(1, \|net change\|): how much editing per character of net progress |
| `paste_count`, `paste_chars` | Inserts of more than 50 characters, and their size |
| `reversal_cycles` | Consecutive insert↔delete switches within 10 characters in the same file |

### Locality (5)

| Feature | Definition |
|---|---|
| `jump_mean`, `jump_max` | Distance in characters between consecutive edit positions in one file |
| `large_jumps` | Jumps over 80 characters (roughly a line or more) |
| `lines_touched` | Distinct (file, line) pairs edited |
| `files_touched` | Distinct files edited |

### Behavioural states (7)

`state_<name>_s`: seconds of the window spent in each state from Algorithm 1 (`docs/states.md`).
The values sum to 30 s or less (less only near a session's start).

### Structure (9)

These describe the **focus file**, the file last edited at or before the window end.

| Feature | Definition |
|---|---|
| `parses` | 1 if the focus file parses at the window end |
| `unparseable_share` | Share of the window's edits that left the file unparseable |
| `ast_nodes`, `n_functions`, `n_classes`, `n_loops`, `n_branches` | Counts in the last parseable tree |
| `n_flags` | Detector flags raised at the window end |
| `flags_changed` | Flags raised or cleared since the previous window: the "changes to flagged nodes over time" in Table 3.2 |

When the focus file doesn't parse, the counts and flags come from its last parseable state (the
detectors' fallback, #6).

### Execution (12)

| Feature | Definition |
|---|---|
| `n_runs` | Runs started in the window |
| `secs_since_last_run` | Window end minus the last run start (NaN before the first run) |
| `run_errors` | Runs that ended in an uncaught exception |
| `runs_terminated` | Runs the student stopped (Ctrl+C, closing the turtle window) |
| `err_syntax` | SyntaxError, IndentationError, TabError |
| `err_name`, `err_unbound_local`, `err_type`, `err_attribute`, `err_value` | One exception type each |
| `err_index_key` | IndexError, KeyError |
| `err_other` | Any other typed exception |

Exception types matter for the misconceptions:

- `UnboundLocalError` is the Table 3.3 cue for global vs local.
- `TypeError: missing 1 required positional argument` is the cue for `self` confusion.
- `TypeError: 'float' object cannot be interpreted as an integer` follows int/float division.

### Flags (7, the vector `a_k`)

`flag_mutable_default`, `flag_aliasing`, `flag_identity_literal`, `flag_indentation_scope`,
`flag_global_local`, `flag_self_confusion`, `flag_int_division`: 1 when that detector fires on
the focus file at the window end.

## Run outcomes by cohort (`features/run_outcomes.py`)

| | 2019 | 2021 | Synthetic |
|---|---|---|---|
| Errored | `X-RunHasError` | Exit code 1, from the runs files' "Process finished with exit code N", else the keystroke exit row | As 2021 |
| Stopped | `X-RunUserTerminated` | Any other non-zero exit code, or `turtle.Terminator` (the window was closed) | As 2021 |
| Exception type | Last exception named in `X-RunOutput` | Last exception in the run's stderr lines in `runs1.csv` / `runs2.csv` | Written by the generator |
| Run end | Not logged (RUNNING assumes 10 s) | Exit-code row | Exit-code row |
| Runs | 75,112; 11,569 errored, 111 without a type | 27,326; 7,952 errored, 3,291 without a type | — |

**2021 coverage gap.** 8,590 of the 27,326 2021 runs (31%) never appear in the runs files,
presumably logs that were not submitted. For those runs, whether the run failed comes from the
keystroke log, but the exception type is unknown, so `run_errors` can be higher than the sum of
the `err_*` counts. The live editor reports a type for every run.

**Synthetic runs (#9, generator v2).** The generator records the exception a run of the injected
code would raise:

- a `TypeError` once a method has lost `self`, or is called on its class;
- a `SyntaxError` whenever the code doesn't parse;
- nothing for mutable defaults, aliasing and identity, which run without errors. That is exactly
  why they are hard to notice.

Runs copied from a real lead-in keep their real outcome. Without this, synthetic runs of broken
`self` code would have exited cleanly, an obvious tell for the #75 discriminator.

## Size of `b_k`

The proposal says about 40 features. This implementation has 52, because each exception type
counts as its own feature, as do the three inter-edit statistics. Groups can be pruned when the
models are built (#13, #14), using importance on the training folds only.
