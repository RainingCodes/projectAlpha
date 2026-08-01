#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path("/app/dataset"))
    args = p.parse_args()
    rows = read_jsonl(args.root / "raw" / "all.jsonl")
    summary = {
        "samples": len(rows),
        "groups": len({r["group_id"] for r in rows}),
        "split": dict(sorted(Counter(r["split"] for r in rows).items())),
        "family": dict(sorted(Counter(r["metadata"]["canonical_family"] for r in rows).items())),
        "decision": dict(sorted(Counter(r["target"]["decision"] for r in rows).items())),
        "intent": dict(sorted(Counter(r["target"]["intent"] for r in rows).items())),
        "priority": dict(sorted(Counter(r["target"]["priority"] for r in rows).items())),
        "language": dict(sorted(Counter(r["metadata"]["language"] for r in rows).items())),
        "style": dict(sorted(Counter(r["metadata"]["style"] for r in rows).items())),
        "human_reviewed": dict(sorted(Counter(str(r["metadata"]["human_reviewed"]) for r in rows).items())),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
