#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:
    raise SystemExit("jsonschema is required: pip install jsonschema") from exc

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.umdl_codec import compact_from_full, compile_umdl


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_no}: row must be a JSON object")
            rows.append(obj)
    return rows


def target_hash(target: Any) -> str:
    raw = json.dumps(target, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path("/app/dataset"))
    args = p.parse_args()

    full_schema = json.loads((args.root / "schema" / "umdl-0.1.schema.json").read_text(encoding="utf-8"))
    compact_schema = json.loads((args.root / "schema" / "umdl-generation-0.2.schema.json").read_text(encoding="utf-8"))
    full_validator = Draft202012Validator(full_schema)
    compact_validator = Draft202012Validator(compact_schema)

    split_rows: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    all_ids: set[str] = set()
    group_splits: dict[str, set[str]] = defaultdict(set)
    group_hashes: dict[str, set[str]] = defaultdict(set)
    roundtrip_ok = 0
    compact_schema_ok = 0

    for split in ("train", "validation", "test"):
        path = args.root / "raw" / f"{split}.jsonl"
        rows = read_jsonl(path)
        split_rows[split] = rows
        for idx, row in enumerate(rows):
            rid = row.get("id")
            gid = row.get("group_id")
            declared = row.get("split")
            if not isinstance(rid, str) or not rid:
                errors.append(f"{split}[{idx}]: invalid id")
                continue
            if rid in all_ids:
                errors.append(f"duplicate id: {rid}")
            all_ids.add(rid)
            if declared != split:
                errors.append(f"{rid}: declared split={declared!r}, file split={split!r}")
            if not isinstance(gid, str) or not gid:
                errors.append(f"{rid}: invalid group_id")
                continue
            group_splits[gid].add(split)
            target = row.get("target")
            group_hashes[gid].add(target_hash(target))
            command = row.get("input", {}).get("command")
            if not isinstance(command, str) or not command.strip():
                errors.append(f"{rid}: empty command")

            full_errors = list(full_validator.iter_errors(target))
            for err in sorted(full_errors, key=lambda e: list(e.path)):
                location = ".".join(map(str, err.path)) or "<root>"
                errors.append(f"{rid}: full schema {location}: {err.message}")

            try:
                compact = compact_from_full(target)
            except Exception as exc:
                errors.append(f"{rid}: compact conversion failed: {exc}")
                continue
            compact_errors = list(compact_validator.iter_errors(compact))
            if compact_errors:
                for err in sorted(compact_errors, key=lambda e: list(e.path)):
                    location = ".".join(map(str, err.path)) or "<root>"
                    errors.append(f"{rid}: compact schema {location}: {err.message}")
            else:
                compact_schema_ok += 1

            compiled = compile_umdl(compact, str(target.get("mission_id", gid)))
            if compiled != target:
                errors.append(f"{rid}: full -> compact -> full roundtrip mismatch")
            else:
                roundtrip_ok += 1

    for gid, splits in sorted(group_splits.items()):
        if len(splits) != 1:
            errors.append(f"group leakage: {gid} appears in {sorted(splits)}")
    for gid, hashes in sorted(group_hashes.items()):
        if len(hashes) != 1:
            errors.append(f"target mismatch within group: {gid}")

    all_rows = read_jsonl(args.root / "raw" / "all.jsonl")
    split_total = sum(len(v) for v in split_rows.values())
    if len(all_rows) != split_total:
        errors.append(f"all.jsonl rows={len(all_rows)} but split total={split_total}")

    compact_chat_counts: dict[str, int] = {}
    for split, rows in split_rows.items():
        chat_path = args.root / "chat_compact" / f"{split}.jsonl"
        if not chat_path.exists():
            errors.append(f"missing compact chat file: {chat_path}")
            continue
        chat_rows = read_jsonl(chat_path)
        compact_chat_counts[split] = len(chat_rows)
        if len(chat_rows) != len(rows):
            errors.append(f"compact chat {split}: rows={len(chat_rows)} raw={len(rows)}")
        raw_by_id = {r["id"]: r for r in rows}
        for chat in chat_rows:
            rid = chat.get("id")
            if rid not in raw_by_id:
                errors.append(f"compact chat {split}: unknown id={rid}")
                continue
            messages = chat.get("messages")
            if not isinstance(messages, list) or len(messages) != 3:
                errors.append(f"{rid}: compact chat requires exactly 3 messages")
                continue
            try:
                assistant_target = json.loads(messages[2]["content"])
            except Exception as exc:
                errors.append(f"{rid}: invalid compact assistant JSON: {exc}")
                continue
            expected = compact_from_full(raw_by_id[rid]["target"])
            if assistant_target != expected:
                errors.append(f"{rid}: compact chat target mismatch")

    result = {
        "valid": not errors,
        "sample_counts": {k: len(v) for k, v in split_rows.items()},
        "sample_total": split_total,
        "group_count": len(group_splits),
        "id_count": len(all_ids),
        "compact_schema_valid_count": compact_schema_ok,
        "compact_roundtrip_exact_count": roundtrip_ok,
        "compact_chat_counts": compact_chat_counts,
        "error_count": len(errors),
        "errors": errors[:100],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
