#!/usr/bin/env python3
"""Evaluate JSONL predictions against a raw UMDL split.

Prediction format: one JSON object per line with at least {"id": ..., "prediction": {...}}.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:
    raise SystemExit("jsonschema is required: pip install jsonschema") from exc


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def task_signature(plan: dict[str, Any]) -> list[str]:
    return [str(t.get("type")) for t in plan.get("tasks", [])]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--gold", type=Path, required=True)
    p.add_argument("--pred", type=Path, required=True)
    p.add_argument("--schema", type=Path, required=True)
    args = p.parse_args()

    gold = {r["id"]: r["target"] for r in load_jsonl(args.gold)}
    pred_rows = load_jsonl(args.pred)
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    n = len(gold)
    found = 0
    json_valid = 0
    schema_valid = 0
    decision_ok = 0
    intent_ok = 0
    task_seq_ok = 0
    exact_ok = 0
    errors: list[str] = []

    for row in pred_rows:
        rid = row.get("id")
        if rid not in gold:
            errors.append(f"unknown id: {rid}")
            continue
        found += 1
        pred = row.get("prediction")
        if not isinstance(pred, dict):
            continue
        json_valid += 1
        if not list(validator.iter_errors(pred)):
            schema_valid += 1
        tgt = gold[rid]
        decision_ok += int(pred.get("decision") == tgt.get("decision"))
        intent_ok += int(pred.get("intent") == tgt.get("intent"))
        task_seq_ok += int(task_signature(pred) == task_signature(tgt))
        exact_ok += int(pred == tgt)

    denom = max(1, n)
    result = {
        "gold_count": n,
        "prediction_rows": len(pred_rows),
        "matched_ids": found,
        "coverage": found / denom,
        "json_object_rate": json_valid / denom,
        "schema_valid_rate": schema_valid / denom,
        "decision_accuracy": decision_ok / denom,
        "intent_accuracy": intent_ok / denom,
        "task_sequence_exact_match": task_seq_ok / denom,
        "full_exact_match": exact_ok / denom,
        "errors": errors[:50],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
