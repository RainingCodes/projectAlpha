#!/usr/bin/env python3
"""Evaluate full UMDL predictions against one raw dataset split."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_metrics import evaluate_rows, load_jsonl


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--gold", type=Path, required=True)
    p.add_argument("--pred", type=Path, required=True)
    p.add_argument("--schema", type=Path, required=True)
    p.add_argument("--output", type=Path)
    args = p.parse_args()

    result = evaluate_rows(
        load_jsonl(args.gold),
        load_jsonl(args.pred),
        json.loads(args.schema.read_text(encoding="utf-8")),
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
