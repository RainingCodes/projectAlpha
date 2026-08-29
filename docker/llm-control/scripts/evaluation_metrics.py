"""UMDL prediction metrics shared by offline and HTTP benchmark scripts."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _task_types(plan: dict[str, Any]) -> list[str]:
    return [str(t.get("type")) for t in plan.get("tasks", []) if isinstance(t, dict)]


def _task_field_exact(gold: dict[str, Any], pred: dict[str, Any], field: str) -> tuple[int, int]:
    g_tasks = gold.get("tasks", []) if isinstance(gold.get("tasks"), list) else []
    p_tasks = pred.get("tasks", []) if isinstance(pred.get("tasks"), list) else []
    ok = 0
    total = 0
    for idx, g in enumerate(g_tasks):
        if not isinstance(g, dict) or field not in g:
            continue
        total += 1
        p = p_tasks[idx] if idx < len(p_tasks) and isinstance(p_tasks[idx], dict) else {}
        ok += int(p.get(field) == g.get(field))
    return ok, total


def _parameter_field_score(gold: dict[str, Any], pred: dict[str, Any]) -> tuple[int, int]:
    g_tasks = gold.get("tasks", []) if isinstance(gold.get("tasks"), list) else []
    p_tasks = pred.get("tasks", []) if isinstance(pred.get("tasks"), list) else []
    ok = 0
    total = 0
    for idx, g in enumerate(g_tasks):
        if not isinstance(g, dict):
            continue
        gp = g.get("parameters")
        if not isinstance(gp, dict):
            continue
        pp = {}
        if idx < len(p_tasks) and isinstance(p_tasks[idx], dict):
            pp = p_tasks[idx].get("parameters") or {}
        if not isinstance(pp, dict):
            pp = {}
        for key, value in gp.items():
            total += 1
            ok += int(pp.get(key) == value)
    return ok, total


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    rank = (len(xs) - 1) * p
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (rank - lo)


def _safe_rate(num: int, den: int) -> float | None:
    return None if den == 0 else num / den


def evaluate_rows(
    gold_rows: list[dict[str, Any]],
    pred_rows: list[dict[str, Any]],
    schema: dict[str, Any],
) -> dict[str, Any]:
    validator = Draft202012Validator(schema)
    gold_by_id = {r["id"]: r for r in gold_rows}
    pred_by_id = {r.get("id"): r for r in pred_rows if r.get("id") in gold_by_id}

    counters: dict[str, int] = defaultdict(int)
    param_ok = param_total = 0
    target_ok = target_total = 0
    pattern_ok = pattern_total = 0
    completion_ok = completion_total = 0
    report_ok = report_total = 0
    latencies: list[float] = []
    prompt_tokens: list[int] = []
    completion_tokens: list[int] = []
    total_tokens: list[int] = []

    family_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for rid, gold_row in gold_by_id.items():
        family = str(gold_row.get("metadata", {}).get("canonical_family", "unknown"))
        pred_row = pred_by_id.get(rid, {})
        pred = pred_row.get("prediction")
        gold = gold_row["target"]

        counters["gold_count"] += 1
        counters["matched"] += int(bool(pred_row))
        counters["request_success"] += int(pred_row.get("request_success") is True or isinstance(pred, dict))
        counters["parse_ok"] += int(pred_row.get("parse_ok") is True or isinstance(pred, dict))
        counters["generation_schema_ok"] += int(pred_row.get("generation_schema_ok") is True or isinstance(pred, dict))

        if isinstance(pred, dict):
            counters["json_object"] += 1
            counters["schema_valid"] += int(not list(validator.iter_errors(pred)))
            counters["decision_ok"] += int(pred.get("decision") == gold.get("decision"))
            counters["intent_ok"] += int(pred.get("intent") == gold.get("intent"))
            counters["priority_ok"] += int(pred.get("priority") == gold.get("priority"))
            counters["task_seq_ok"] += int(_task_types(pred) == _task_types(gold))
            counters["requirements_ok"] += int(pred.get("requirements") == gold.get("requirements"))
            counters["constraints_ok"] += int(pred.get("constraints") == gold.get("constraints"))
            counters["contingencies_ok"] += int(pred.get("contingencies") == gold.get("contingencies"))
            counters["safe_fallback_ok"] += int(pred.get("safe_fallback") == gold.get("safe_fallback"))
            counters["clarification_ok"] += int(
                pred.get("requires_clarification") == gold.get("requires_clarification")
                and pred.get("missing_fields") == gold.get("missing_fields")
                and pred.get("clarification_question") == gold.get("clarification_question")
            )
            counters["exact_ok"] += int(pred == gold)

            a, b = _parameter_field_score(gold, pred)
            param_ok += a; param_total += b
            for field, names in (
                ("target", ("target_ok", "target_total")),
                ("pattern", ("pattern_ok", "pattern_total")),
                ("completion", ("completion_ok", "completion_total")),
                ("report_type", ("report_ok", "report_total")),
            ):
                a, b = _task_field_exact(gold, pred, field)
                if field == "target": target_ok += a; target_total += b
                elif field == "pattern": pattern_ok += a; pattern_total += b
                elif field == "completion": completion_ok += a; completion_total += b
                else: report_ok += a; report_total += b

        timing = pred_row.get("timing_ms") or {}
        if isinstance(timing, dict):
            value = timing.get("llm_http_ms") or timing.get("request_total_ms")
            if isinstance(value, (int, float)):
                latencies.append(float(value))
        usage = pred_row.get("usage") or {}
        if isinstance(usage, dict):
            for key, target_list in (
                ("prompt_tokens", prompt_tokens),
                ("completion_tokens", completion_tokens),
                ("total_tokens", total_tokens),
            ):
                value = usage.get(key)
                if isinstance(value, int):
                    target_list.append(value)

        family_buckets[family].append(pred_row)

    n = counters["gold_count"]
    result: dict[str, Any] = {
        "gold_count": n,
        "prediction_rows": len(pred_rows),
        "matched_ids": counters["matched"],
        "coverage": _safe_rate(counters["matched"], n),
        "request_success_rate": _safe_rate(counters["request_success"], n),
        "parse_rate": _safe_rate(counters["parse_ok"], n),
        "generation_schema_valid_rate": _safe_rate(counters["generation_schema_ok"], n),
        "full_schema_valid_rate": _safe_rate(counters["schema_valid"], n),
        "decision_accuracy": _safe_rate(counters["decision_ok"], n),
        "intent_accuracy": _safe_rate(counters["intent_ok"], n),
        "priority_accuracy": _safe_rate(counters["priority_ok"], n),
        "task_sequence_exact_match": _safe_rate(counters["task_seq_ok"], n),
        "target_exact_accuracy": _safe_rate(target_ok, target_total),
        "pattern_exact_accuracy": _safe_rate(pattern_ok, pattern_total),
        "parameter_field_accuracy": _safe_rate(param_ok, param_total),
        "completion_exact_accuracy": _safe_rate(completion_ok, completion_total),
        "report_type_exact_accuracy": _safe_rate(report_ok, report_total),
        "requirements_exact_accuracy": _safe_rate(counters["requirements_ok"], n),
        "constraints_exact_accuracy": _safe_rate(counters["constraints_ok"], n),
        "contingencies_exact_accuracy": _safe_rate(counters["contingencies_ok"], n),
        "safe_fallback_accuracy": _safe_rate(counters["safe_fallback_ok"], n),
        "clarification_accuracy": _safe_rate(counters["clarification_ok"], n),
        "full_exact_match": _safe_rate(counters["exact_ok"], n),
        "parameter_field_count": param_total,
        "latency_ms": {
            "count": len(latencies),
            "mean": (sum(latencies) / len(latencies)) if latencies else None,
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": max(latencies) if latencies else None,
        },
        "tokens": {
            "prompt_mean": (sum(prompt_tokens) / len(prompt_tokens)) if prompt_tokens else None,
            "completion_mean": (sum(completion_tokens) / len(completion_tokens)) if completion_tokens else None,
            "total_mean": (sum(total_tokens) / len(total_tokens)) if total_tokens else None,
        },
    }

    per_family: dict[str, Any] = {}
    for family in sorted(family_buckets):
        family_gold = [r for r in gold_rows if str(r.get("metadata", {}).get("canonical_family", "unknown")) == family]
        family_result = evaluate_rows_without_family(family_gold, family_buckets[family], schema)
        per_family[family] = family_result
    result["per_family"] = per_family
    return result


def evaluate_rows_without_family(gold_rows: list[dict[str, Any]], pred_rows: list[dict[str, Any]], schema: dict[str, Any]) -> dict[str, Any]:
    """Reduced recursion-free family metrics."""
    validator = Draft202012Validator(schema)
    pred_by_id = {r.get("id"): r for r in pred_rows}
    n = len(gold_rows)
    c = defaultdict(int)
    p_ok = p_total = 0
    latencies: list[float] = []
    for g_row in gold_rows:
        r = pred_by_id.get(g_row["id"], {})
        pred = r.get("prediction")
        gold = g_row["target"]
        c["request"] += int(r.get("request_success") is True or isinstance(pred, dict))
        if not isinstance(pred, dict):
            continue
        c["schema"] += int(not list(validator.iter_errors(pred)))
        c["decision"] += int(pred.get("decision") == gold.get("decision"))
        c["intent"] += int(pred.get("intent") == gold.get("intent"))
        c["tasks"] += int(_task_types(pred) == _task_types(gold))
        c["exact"] += int(pred == gold)
        a,b = _parameter_field_score(gold,pred); p_ok += a; p_total += b
        timing=r.get("timing_ms") or {}
        if isinstance(timing,dict):
            v=timing.get("llm_http_ms") or timing.get("request_total_ms")
            if isinstance(v,(int,float)): latencies.append(float(v))
    return {
        "count": n,
        "request_success_rate": _safe_rate(c["request"], n),
        "full_schema_valid_rate": _safe_rate(c["schema"], n),
        "decision_accuracy": _safe_rate(c["decision"], n),
        "intent_accuracy": _safe_rate(c["intent"], n),
        "task_sequence_exact_match": _safe_rate(c["tasks"], n),
        "parameter_field_accuracy": _safe_rate(p_ok,p_total),
        "full_exact_match": _safe_rate(c["exact"], n),
        "latency_ms_mean": (sum(latencies)/len(latencies)) if latencies else None,
    }
