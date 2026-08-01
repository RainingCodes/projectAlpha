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

    schema_path = args.root / "schema" / "umdl-0.1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    split_rows: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    all_ids: set[str] = set()
    group_splits: dict[str, set[str]] = defaultdict(set)
    group_hashes: dict[str, set[str]] = defaultdict(set)

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
            group_hashes[gid].add(target_hash(row.get("target")))
            command = row.get("input", {}).get("command")
            if not isinstance(command, str) or not command.strip():
                errors.append(f"{rid}: empty command")
            for err in sorted(validator.iter_errors(row.get("target")), key=lambda e: list(e.path)):
                location = ".".join(map(str, err.path)) or "<root>"
                errors.append(f"{rid}: schema {location}: {err.message}")

    for gid, splits in sorted(group_splits.items()):
        if len(splits) != 1:
            errors.append(f"group leakage: {gid} appears in {sorted(splits)}")
    for gid, hashes in sorted(group_hashes.items()):
        if len(hashes) != 1:
            errors.append(f"target mismatch within group: {gid}")

    all_path = args.root / "raw" / "all.jsonl"
    all_rows = read_jsonl(all_path)
    split_total = sum(len(v) for v in split_rows.values())
    if len(all_rows) != split_total:
        errors.append(f"all.jsonl rows={len(all_rows)} but split total={split_total}")

    result = {
        "valid": not errors,
        "sample_counts": {k: len(v) for k, v in split_rows.items()},
        "sample_total": split_total,
        "group_count": len(group_splits),
        "id_count": len(all_ids),
        "error_count": len(errors),
        "errors": errors[:100],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
