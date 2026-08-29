#!/usr/bin/env python3
"""Build SFT chat JSONL whose assistant target matches runtime Compact UMDL IR v0.2."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.umdl_codec import COMPACT_SYSTEM_PROMPT, compact_from_full

SYSTEM = COMPACT_SYSTEM_PROMPT


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def convert(sample: dict[str, Any]) -> dict[str, Any]:
    inp = sample["input"]
    user_payload = {
        "instruction": inp["command"],
        "runtime_context": inp.get("runtime_context", {}),
        "available_capabilities": inp.get("available_capabilities", []),
    }
    return {
        "id": sample["id"],
        "group_id": sample["group_id"],
        "split": sample["split"],
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True)},
            {"role": "assistant", "content": json.dumps(compact_from_full(sample["target"]), ensure_ascii=False, sort_keys=True)},
        ],
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path("/app/dataset"))
    args = p.parse_args()
    counts: dict[str, int] = {}
    for split in ("train", "validation", "test"):
        raw = load_jsonl(args.root / "raw" / f"{split}.jsonl")
        out = [convert(row) for row in raw]
        write_jsonl(args.root / "chat_compact" / f"{split}.jsonl", out)
        counts[split] = len(out)
    print(json.dumps({"ok": True, "output": str(args.root / "chat_compact"), "counts": counts}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
