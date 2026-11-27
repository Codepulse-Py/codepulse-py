"""Build or verify the frozen 2021 cross-validation folds in data/folds.json.

    python scripts/make_folds.py           # verify data/folds.json matches the raw data
    python scripts/make_folds.py --write   # (re)generate it

Needs the RQ1 episodes (python scripts/mine_candidates.py --cohort 2021), which
the folds are stratified on. The folds are meant to be created once and then
frozen: regenerate only on purpose, since every model and result depends on them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from splits.manifest import (  # noqa: E402
    EPISODES_PATH,
    FOLDS_PATH,
    all_splits,
    build_from_raw,
    check_disjoint,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--path", type=Path, default=FOLDS_PATH)
    parser.add_argument("--episodes", type=Path, default=EPISODES_PATH, help="RQ1 miner output")
    parser.add_argument("--write", action="store_true", help="write the manifest")
    args = parser.parse_args(argv)

    manifest = build_from_raw(args.raw_dir, args.episodes)
    check_disjoint({f"fold {i}": f for i, f in enumerate(manifest["folds"])})
    for s in all_splits(manifest["folds"]):
        check_disjoint({"train": s.train, "tune": s.tune, "test": s.test})
    text = json.dumps(manifest, indent=2) + "\n"

    if args.write:
        args.path.write_text(text)
        print(f"wrote {args.path}: fold sizes {manifest['sizes']}")
        return 0
    if not args.path.exists():
        print(f"FAIL  {args.path} missing; run with --write")
        return 1
    if args.path.read_text() != text:
        print(f"FAIL  {args.path} does not match a fresh build from the raw data")
        return 1
    print(f"PASS  {args.path} matches the raw data: fold sizes {manifest['sizes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
