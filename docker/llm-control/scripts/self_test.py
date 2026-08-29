#!/usr/bin/env python3
"""Offline self-test; does not require vLLM, ROS traffic, or Stonefish."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from app.umdl_codec import compact_from_full, compile_umdl
from app.umdl_router import MissionPlanRequest, _generation_rule_errors, _infer_family
from evaluation_metrics import evaluate_rows


def main() -> None:
    root = PROJECT_ROOT / "dataset"
    rows = [json.loads(x) for x in (root / "raw" / "all.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    compact_schema = json.loads((root / "schema" / "umdl-generation-0.2.schema.json").read_text(encoding="utf-8"))
    full_schema = json.loads((root / "schema" / "umdl-0.1.schema.json").read_text(encoding="utf-8"))
    compact_validator = Draft202012Validator(compact_schema)

    for row in rows:
        ir = compact_from_full(row["target"])
        assert not list(compact_validator.iter_errors(ir)), row["id"]
        assert compile_umdl(ir, row["target"]["mission_id"]) == row["target"], row["id"]
        req = MissionPlanRequest(
            instruction=row["input"]["command"],
            runtime_context=row["input"].get("runtime_context", {}),
            available_capabilities=row["input"].get("available_capabilities", []),
            mission_id=row["target"]["mission_id"],
            force_llm=True,
        )
        assert not _generation_rule_errors(ir, req, False), row["id"]

    hint_rows = [r for r in rows if r.get("metadata", {}).get("canonical_family") not in {"reject", "ambiguous"}]
    family_hint_ok = sum(
        _infer_family(r["input"]["command"]) == r["metadata"]["canonical_family"] for r in hint_rows
    )
    assert family_hint_ok == len(hint_rows), (family_hint_ok, len(hint_rows))

    test_rows = [r for r in rows if r["split"] == "test"]
    perfect = [
        {
            "id": r["id"],
            "request_success": True,
            "parse_ok": True,
            "generation_schema_ok": True,
            "prediction": r["target"],
            "timing_ms": {"llm_http_ms": 1.0},
        }
        for r in test_rows
    ]
    metrics = evaluate_rows(test_rows, perfect, full_schema)
    for key in (
        "coverage", "request_success_rate", "parse_rate", "generation_schema_valid_rate",
        "full_schema_valid_rate", "decision_accuracy", "intent_accuracy",
        "task_sequence_exact_match", "full_exact_match"
    ):
        assert metrics[key] == 1.0, (key, metrics[key])

    print(json.dumps({
        "ok": True,
        "sample_total": len(rows),
        "compact_schema_valid": len(rows),
        "compact_roundtrip_exact": len(rows),
        "runtime_rule_valid_without_family_hints": len(rows),
        "family_hint_seed_exec_accuracy": f"{family_hint_ok}/{len(hint_rows)}",
        "perfect_evaluator_test_count": len(test_rows)
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
