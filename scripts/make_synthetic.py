"""Generate synthetic windows for the rare misconceptions (#9).

    python scripts/make_synthetic.py                     # 150 per rare class
    python scripts/make_synthetic.py --per-class 100 --seed 7

Seeds are sampled from the 2021 cohort's own replayed sessions. Writes to
data/interim/synthetic/ (git-ignored):

    keystrokes.csv   2021-format ProgSnap2 rows, one session per synthetic item
    manifest.csv     one row per item: misconception, rule, seed student, cues ...
    summary.json     counts generated, kept and rejected by QC

Synthetic items are for training only and must pass #75 before use.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from synthetic.generate import generate  # noqa: E402
from synthetic.inject import MISCONCEPTIONS  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--per-class", type=int, default=150)
    parser.add_argument("--seed", type=int, default=1400)
    parser.add_argument("--misconception", choices=MISCONCEPTIONS, action="append")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data" / "interim" / "synthetic")
    args = parser.parse_args(argv)

    warnings.simplefilter("ignore")
    summary = generate(
        args.raw_dir, args.out_dir, args.per_class, args.seed,
        misconceptions=tuple(args.misconception or MISCONCEPTIONS),
    )  # fmt: skip
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=dict) + "\n")
    print(json.dumps(summary, indent=2, default=dict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
