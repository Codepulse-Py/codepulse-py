"""Build or verify the frozen 2021 student split in data/splits.json.

    python scripts/make_splits.py           # verify data/splits.json matches the raw data
    python scripts/make_splits.py --write   # (re)generate it

The split is meant to be created once and then frozen: regenerate only on purpose,
since every model and result depends on it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from splits.manifest import SPLITS_PATH, build_from_raw, check_disjoint  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--path", type=Path, default=SPLITS_PATH)
    parser.add_argument("--write", action="store_true", help="write the manifest")
    args = parser.parse_args(argv)

    manifest = build_from_raw(args.raw_dir)
    check_disjoint({k: manifest[k] for k in ("train", "validation", "test")})
    text = json.dumps(manifest, indent=2) + "\n"

    if args.write:
        args.path.write_text(text)
        print(f"wrote {args.path}: {manifest['sizes']}")
        return 0
    if not args.path.exists():
        print(f"FAIL  {args.path} missing; run with --write")
        return 1
    if args.path.read_text() != text:
        print(f"FAIL  {args.path} does not match a fresh build from the raw data")
        return 1
    print(f"PASS  {args.path} matches the raw data: {manifest['sizes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
