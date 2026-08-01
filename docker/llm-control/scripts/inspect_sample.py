#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path("/app/dataset"))
    p.add_argument("--split", choices=["train", "validation", "test"], default="test")
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--group-id")
    args = p.parse_args()
    path = args.root / "raw" / f"{args.split}.jsonl"
    rows = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
    if args.group_id:
        selected = [r for r in rows if r["group_id"] == args.group_id]
        if not selected:
            raise SystemExit(f"group_id not found in {args.split}: {args.group_id}")
        print(json.dumps(selected, ensure_ascii=False, indent=2))
        return
    if args.index < 0 or args.index >= len(rows):
        raise SystemExit(f"index out of range: 0 <= index < {len(rows)}")
    print(json.dumps(rows[args.index], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
