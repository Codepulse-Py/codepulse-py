# ProgSnap2 replay engine

Neither cohort stores code (`CodeStateID` is always empty), so every code state is rebuilt by
replaying the edit log (§6.6 step 1). The replay lives in [`replay/`](../replay). Run it with:

```bash
python scripts/replay_cohort.py 2021                      # about 10 s
python scripts/replay_cohort.py 2019 --check-every-state  # about 4 min
```

The outputs go to `data/interim/replay/<cohort>/`, which is git-ignored:

| File | Contents |
|---|---|
| `snapshots.parquet` | Every file of the session at each `Run.Program`, each `Submit` (2019) and the end of the session: `subject, assignment, kind, event_id, timestamp, trigger_file, file, code` |
| `sessions.csv` | Per-session counts: edits, delete mismatches, final agreement, checkpoints, runs |
| `summary.json` | Cohort totals and timings |

For per-event states (the AST detectors, #8), call `replay_session(..., on_state=callback)`.
The callback receives `(event, file, text)` once per distinct code state.

## Semantics

- **Edits.** Each `File.Edit` deletes `DeleteText` and then inserts `InsertText` at
  `SourceLocation`, a 0-based character offset. Insert, delete, replace, paste, cut, undo, redo
  and drag all reduce to this. It is the same reconstruction as the authors' `sample-code.ipynb`.
- **Starting content.** Files start empty. In 2019 the first event of a file is often an
  `X-Checkpoint` row holding the starter or reloaded file; replay treats it as a full-file reset.
  All 2,226 checkpoints occur while the replayed file is still empty, so none of them overwrites
  replayed work.
- **Order.** A session is one student × one assignment. Within a file, `EventID` order is
  chronological; this holds for all 1,304 2021 files. Across the files of one 2021 session, only
  the timestamp is chronological. Replay therefore sorts each session by
  `(ClientTimestamp, EventID)`, which keeps each file's order and merges the files correctly.
- **Multiple files.** Each `CodeStateSection` is replayed separately. A snapshot captures every
  file of the session, because programs import their own modules (for example `modules/*.py`
  in 2021).
- **No-op rows.** A 2021 `File.Edit` with neither text is a file-open marker and is skipped.
  `Run.Program` rows with an exit code are skipped; only `Start` rows trigger a snapshot.

## How a replay is checked

The release contains no submitted files, so "replayed state == submitted file" can't be tested
directly. The data does carry two independent checks:

1. **`X-Compilable`.** The logger recorded after every event whether the real file parsed.
   Replay parses its own text at the same point with `ast.parse` and compares.
   - A session **matches** when the replayed final text of every file agrees with that file's
     last logged flag. This is the acceptance metric.
   - `--check-every-state` repeats the comparison at every distinct state, not just the last one.
2. **`DeleteText`.** Every delete records the text it removed, which must already be at that
   offset. A mismatch is counted, but the edit is still applied as logged.

The property test in `tests/test_replay.py` generates random edit histories and checks that
replay reproduces the true final file exactly, with no mismatches.

## Results

| | 2021 | 2019 |
|---|---:|---:|
| Sessions | 262 | 1,582 |
| Files with content | 749 | 3,028 |
| Edits applied | 970,154 | 5,037,529 |
| **Sessions matching (final `X-Compilable`)** | **262 (100%)** | **1,581 (99.94%)** |
| Files matching | 749 / 749 | 3,027 / 3,028 |
| Every-state `X-Compilable` agreement | 99.89% of 962,862 | 99.96% of 4,982,851 |
| Deletes not matching `DeleteText` | 0.25% of edits | 21 edits (1 file) |
| Sessions with zero delete mismatches | 173 (66%) | 1,581 |
| Runs snapshotted | 27,326 | 75,112 |
| Replay time (load + replay) | 10 s; 100 s with every-state check | 26 s; 226 s with every-state check |

The full 2021 cohort replays in well under the 10-minute target.

The one 2019 session that doesn't match (S290, p8s) is a checker difference, not a replay
error. The file mixes tabs and spaces in its indentation, which Python 3 rejects with
`TabError`, while the Phanon editor's checker accepted it.

## Why 2021 edits are applied in logged order

In 2021, 0.25% of deletes don't match the replayed text. They cluster in bursts of edits that
share one timestamp, produced by bulk IDE operations: Comment with Line Comment, paste over a
selection, Reformat, and Outside edit. In those bursts the logged order looked scrambled, so a
search for an order in which every delete matches was tried and measured against the
every-state `X-Compilable` check:

| 2021 strategy | Every-state agreement | Sessions with zero mismatches |
|---|---:|---:|
| **Logged order (used)** | **99.89%** | 173 |
| Re-order same-timestamp bursts until deletes match | 99.00% | 178 |
| Same, grouping edits up to 5 ms apart | 98.16% | 188 |

Re-ordering removes some mismatches but makes the code wrong more often. This indicates that
the 2021 `DeleteText` values are themselves unreliable inside bulk operations, and the logged
order is usually right. Agreement stays at 99.96% even after a file's first mismatch, so the
damage is local. Replay therefore keeps the logged order and reports mismatches as a diagnostic.

## Known limitations

- **Unlogged content.** A few 2021 files contain content that was never logged, for example
  files created outside PyCharm (Outside edit) or edited with the plugin off. Replay can't
  recover that text, and those files show delete mismatches.
- **Files opened but never edited** in a session (329 open markers in 2021) have no replayable
  content and get no snapshot entry.
- **The checks only cover syntax.** `X-Compilable` validates the syntax state, not every
  character. Two texts that both parse, or both fail, are indistinguishable to it. Together with
  the delete check and the property test, it is the strongest evidence the release allows.
