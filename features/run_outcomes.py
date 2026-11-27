"""What happened on each run: errored, stopped by the student, and the exception type.

The cohorts log run outcomes differently, so each has a loader that returns
the same table, one row per run start::

    subject, assignment, file, timestamp, end_ms, errored, terminated, error_type

- **2019**: ``Run.Program`` rows carry ``X-RunHasError``, ``X-RunUserTerminated``
  and the run's output, from which the exception type is read. When a run
  ended is not logged (``end_ms`` is empty).
- **2021**: the keystroke log has a ``Start`` row and then an exit-code row;
  exit code 1 is an uncaught exception, other non-zero codes are runs the
  student stopped (130 and -1073741510 are Ctrl+C on Linux/macOS and Windows).
  ``runs1.csv`` / ``runs2.csv`` have exactly the same timestamp on their run
  rows as the ``Start`` rows, and give the exception type (stderr) and the
  exit code ("Process finished with exit code N"), which is preferred over the
  keystroke log's exit row. ``turtle.Terminator`` (the student closed the
  turtle window) counts as stopped, not as an error.
- **Synthetic** sessions (#9) are written in the 2021 format, with their own
  ``runs.csv``.

The live editor (#21) reports the same three facts for each run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

ERROR_RE = re.compile(r"\b(\w+(?:Error|Exception))\b")
EXIT_RE = re.compile(r"exit code (-?\d+)")
COLUMNS = ["subject", "assignment", "file", "timestamp", "end_ms", "errored", "terminated",
           "error_type"]  # fmt: skip


def _last_error(text: str) -> str:
    """The last exception name in a run's output; "Terminator" when the turtle window was closed."""
    text = text or ""
    if "turtle.Terminator" in text:
        return "Terminator"
    found = ERROR_RE.findall(text)
    return found[-1] if found else ""


def runs_2019(keystrokes: Path) -> pd.DataFrame:
    cols = ["SubjectID", "AssignmentID", "CodeStateSection", "EventType", "ClientTimestamp",
            "X-RunHasError", "X-RunUserTerminated", "X-RunOutput"]  # fmt: skip
    df = pd.read_csv(keystrokes, usecols=cols, dtype=str, keep_default_na=False)
    df = df[df.EventType == "Run.Program"]
    errored = (df["X-RunHasError"] == "True") & (df["X-RunUserTerminated"] != "True")
    out = pd.DataFrame(
        {
            "subject": df.SubjectID,
            "assignment": df.AssignmentID,
            "file": df.CodeStateSection,
            "timestamp": df.ClientTimestamp.astype("int64"),
            "errored": errored,
            "terminated": df["X-RunUserTerminated"] == "True",
            "error_type": [
                _last_error(o) if e else "" for o, e in zip(df["X-RunOutput"], errored, strict=True)
            ],
        }
    )
    out["end_ms"] = pd.NA  # Phanon does not log when a run ends
    return out.reset_index(drop=True)[COLUMNS]


def _runs_csv_outcomes(paths: list[Path]) -> pd.DataFrame:
    """(subject, assignment, timestamp) -> exception type and exit code, from runs files."""
    starts, errors, exits = [], [], []
    cols = ["SubjectID", "AssignmentID", "Action", "RunID", "OutputDestination", "Output",
            "ClientTimestamp"]  # fmt: skip
    key = ["SubjectID", "AssignmentID", "RunID"]
    for path in paths:
        for chunk in pd.read_csv(path, usecols=cols, dtype=str, keep_default_na=False,
                                 chunksize=1_000_000):  # fmt: skip
            starts.append(chunk[chunk.Action == "r"][[*key, "ClientTimestamp"]])
            out = chunk[chunk.Action == "o"]
            err = out[out.OutputDestination == "stderr"]
            err = err.assign(error_type=err.Output.map(_last_error))
            errors.append(err[err.error_type != ""][[*key, "error_type"]])
            sysl = out[out.OutputDestination == "system"]
            sysl = sysl.assign(exit_code=sysl.Output.str.extract(EXIT_RE, expand=False))
            exits.append(sysl.dropna(subset=["exit_code"])[[*key, "exit_code"]])
    empty = pd.DataFrame(columns=["subject", "assignment", "timestamp", "error_type", "exit_code"])
    if not starts:
        return empty
    runs = pd.concat(starts).drop_duplicates(key)
    runs = runs.join(pd.concat(errors).groupby(key).error_type.last(), on=key)
    runs = runs.join(pd.concat(exits).groupby(key).exit_code.last(), on=key)
    return pd.DataFrame(
        {
            "subject": runs.SubjectID,
            "assignment": runs.AssignmentID,
            "timestamp": runs.ClientTimestamp.astype(float).astype("int64"),
            "error_type": runs.error_type.fillna(""),
            "exit_code": runs.exit_code.fillna(""),
        }
    )


def runs_2021_format(keystrokes: Path, runs_files: list[Path]) -> pd.DataFrame:
    cols = ["SubjectID", "AssignmentID", "CodeStateSection", "EventType", "ClientTimestamp",
            "X-Metadata", "EventID"]  # fmt: skip
    df = pd.read_csv(keystrokes, usecols=cols, dtype=str, keep_default_na=False)
    df = df[df.EventType == "Run.Program"].copy()
    df["ts"] = df.ClientTimestamp.astype("int64")
    df["eid"] = df.EventID.astype("int64")
    df = df.sort_values(["SubjectID", "AssignmentID", "CodeStateSection", "ts", "eid"])
    # Each Start is followed (same subject, assignment, file) by its exit-code row.
    grouped = df.groupby(["SubjectID", "AssignmentID", "CodeStateSection"])
    nxt, nxt_ts = grouped["X-Metadata"].shift(-1), grouped["ts"].shift(-1)
    starts = df[df["X-Metadata"] == "Start"]
    code = nxt.loc[starts.index].fillna("")
    # The exit row marks when the run ended (unless the next row is another Start).
    end_ms = nxt_ts.loc[starts.index].where(code.ne("Start") & code.ne(""))
    out = pd.DataFrame(
        {
            "subject": starts.SubjectID,
            "assignment": starts.AssignmentID,
            "file": starts.CodeStateSection,
            "timestamp": starts.ts,
            "end_ms": end_ms.values,
            "log_exit": code.values,
        }
    ).reset_index(drop=True)
    out = out.merge(_runs_csv_outcomes(runs_files), on=["subject", "assignment", "timestamp"],
                    how="left")  # fmt: skip
    out["error_type"] = out.error_type.fillna("")
    exit_code = out.exit_code.fillna("").where(out.exit_code.fillna("") != "", out.log_exit)
    stopped = out.error_type == "Terminator"
    out["errored"] = (exit_code == "1") & ~stopped
    out["terminated"] = (~exit_code.isin(["0", "1", "", "Start"])) | stopped
    out.loc[stopped, "error_type"] = ""
    return out.drop_duplicates(["subject", "assignment", "file", "timestamp"])[COLUMNS]


def load_run_outcomes(source_dir: Path, cohort: str) -> pd.DataFrame:
    """Run outcomes for a cohort directory (``data/raw/2019``, ``data/raw/2021`` or synthetic)."""
    keystrokes = source_dir / "keystrokes.csv"
    if cohort == "2019":
        return runs_2019(keystrokes)
    runs_files = sorted(source_dir.glob("runs*.csv"))
    return runs_2021_format(keystrokes, runs_files)
