#!/usr/bin/env python3
"""Collect benchmark metrics.json files into one comparison CSV."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

FIELDS = [
    "model", "run_tag", "split", "sample_count",
    "request_success_rate", "parse_rate", "generation_schema_valid_rate", "full_schema_valid_rate",
    "decision_accuracy", "intent_accuracy", "task_sequence_exact_match", "parameter_field_accuracy",
    "requirements_exact_accuracy", "clarification_accuracy", "full_exact_match",
    "latency_mean_ms", "latency_p50_ms", "latency_p95_ms"
]


def val(d: dict[str, Any], key: str) -> Any:
    return d.get(key)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--results-dir", type=Path, default=Path("/app/results"))
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    output = args.output or (args.results_dir / "benchmark_summary.csv")

    rows: list[dict[str, Any]] = []
    for path in sorted(args.results_dir.glob("*/metrics.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        run = doc.get("run", {})
        m = doc.get("metrics", {})
        lat = m.get("latency_ms", {}) or {}
        rows.append({
            "model": run.get("model"),
            "run_tag": run.get("run_tag"),
            "split": run.get("split"),
            "sample_count": run.get("sample_count"),
            "request_success_rate": val(m, "request_success_rate"),
            "parse_rate": val(m, "parse_rate"),
            "generation_schema_valid_rate": val(m, "generation_schema_valid_rate"),
            "full_schema_valid_rate": val(m, "full_schema_valid_rate"),
            "decision_accuracy": val(m, "decision_accuracy"),
            "intent_accuracy": val(m, "intent_accuracy"),
            "task_sequence_exact_match": val(m, "task_sequence_exact_match"),
            "parameter_field_accuracy": val(m, "parameter_field_accuracy"),
            "requirements_exact_accuracy": val(m, "requirements_exact_accuracy"),
            "clarification_accuracy": val(m, "clarification_accuracy"),
            "full_exact_match": val(m, "full_exact_match"),
            "latency_mean_ms": lat.get("mean"),
            "latency_p50_ms": lat.get("p50"),
            "latency_p95_ms": lat.get("p95"),
        })

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"runs={len(rows)}")
    print(f"saved={output}")
    for row in rows:
        print(
            f"{row['model']} [{row.get('run_tag') or 'default'}] | intent={row['intent_accuracy']} | tasks={row['task_sequence_exact_match']} "
            f"| params={row['parameter_field_accuracy']} | exact={row['full_exact_match']} "
            f"| p95_ms={row['latency_p95_ms']}"
        )


if __name__ == "__main__":
    main()
