"""Lossless Compact UMDL IR v0.2 codec.

The LLM emits a compact representation. This module converts the full UMDL
seed targets to that representation and deterministically compiles the IR back
to full UMDL. For the current seed dataset the round-trip is intentionally
lossless so training targets and runtime targets are identical.
"""
from __future__ import annotations

import copy
from typing import Any


COMPACT_SYSTEM_PROMPT = (
    "Convert the user instruction into one Compact UMDL IR v0.2 JSON object. "
    "Return JSON only. No markdown and no explanation. "
    "Do not invent keys. "
    "Use exactly this top-level structure: "
    '{"intent":"","priority":"","decision":"","required_capabilities":[],'
    '"preferred_sensor_roles":[],"tasks":[],'
    '"constraints_policy":"","contingency_policy":"",'
    '"requires_clarification":false,"missing_fields":[],'
    '"safe_fallback":"","reason_code":""}. '
    "For EXECUTE, tasks must contain task objects with exactly these keys: "
    '{"type":"","target_type":"","target_reference":"","pattern_type":"",'
    '"pattern_parameters":{},"parameters":{},'
    '"completion_condition":"","report_type":""}. '
    'Use "NONE" for unused scalar task fields and {} for unused parameter objects. '
    "Preserve numeric values and symbolic targets from the instruction. "
    "Use only capabilities listed in available_capabilities. "
    'For EXECUTE: requires_clarification=false, missing_fields=[], reason_code="NONE". '
    "For REQUEST_CLARIFICATION, REJECT, or UNSUPPORTED: tasks=[]. "
    "Never output task_list, task_id, decision_reason, waypoints, ROS topics, "
    "velocity commands, thruster commands, PWM, RPM, or controller gains."
)

DEFAULT_CONSTRAINTS: dict[str, Any] = {
    "collision_avoidance": {"enabled": True},
    "depth": {"mode": "WITHIN_PLATFORM_LIMITS"},
    "energy": {"reserve_policy": "PLATFORM_DEFAULT"},
}

SAFE_RETURN_CONSTRAINTS: dict[str, Any] = {
    "collision_avoidance": {"enabled": True},
    "depth": {"mode": "SAFE_RETURN_PROFILE"},
    "energy": {
        "mode": "MINIMIZE_CONSUMPTION",
        "reserve_policy": "PROTECT_SURFACING_RESERVE",
    },
}

CONTINGENCY_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "NONE": [],
    "BATTERY_BELOW_RESERVE_RETURN_SURFACE": [
        {
            "when": {"type": "BATTERY_BELOW_RESERVE"},
            "then": [{"type": "RETURN_HOME"}, {"type": "SURFACE"}],
        }
    ],
    "NAVIGATION_UNSTABLE_REPORT_SURFACE": [
        {
            "when": {"type": "NAVIGATION_UNSTABLE"},
            "then": [
                {"type": "REPORT", "report_type": "NAVIGATION_FAULT"},
                {"type": "SURFACE"},
            ],
        }
    ],
}

CLARIFICATION_QUESTIONS: dict[tuple[str, ...], str] = {
    ("target_region", "search_target"): "탐색할 구역과 찾을 대상을 지정해 주세요.",
    ("target_depth",): "변경할 목표 수심을 지정해 주세요.",
    ("hold_duration",): "현재 위치를 유지할 시간을 지정해 주세요.",
    ("inspection_target",): "점검할 대상이나 구조물을 지정해 주세요.",
    ("report_content",): "보고할 정보의 종류를 지정해 주세요.",
}


def _constraint_policy(constraints: dict[str, Any] | None) -> str:
    constraints = constraints or DEFAULT_CONSTRAINTS
    if constraints == SAFE_RETURN_CONSTRAINTS:
        return "SAFE_RETURN_PROFILE"
    if constraints == DEFAULT_CONSTRAINTS:
        return "PLATFORM_DEFAULT"
    raise ValueError(f"Unsupported constraints for Compact IR v0.2: {constraints!r}")


def _contingency_policy(contingencies: list[dict[str, Any]] | None) -> str:
    contingencies = contingencies or []
    for name, template in CONTINGENCY_TEMPLATES.items():
        if contingencies == template:
            return name
    raise ValueError(f"Unsupported contingencies for Compact IR v0.2: {contingencies!r}")


def compact_from_full(target: dict[str, Any]) -> dict[str, Any]:
    """Convert one full UMDL target to the lossless Compact IR v0.2."""
    compact_tasks: list[dict[str, Any]] = []
    for task in target.get("tasks", []):
        tgt = task.get("target") or {}
        pattern = task.get("pattern") or {}
        completion = task.get("completion") or {}
        pattern_parameters = {k: copy.deepcopy(v) for k, v in pattern.items() if k != "type"}
        compact_tasks.append(
            {
                "type": task.get("type", "WAIT"),
                "target_type": tgt.get("type", "NONE"),
                "target_reference": tgt.get("reference", "NONE"),
                "pattern_type": pattern.get("type", "NONE"),
                "pattern_parameters": pattern_parameters,
                "parameters": copy.deepcopy(task.get("parameters") or {}),
                "completion_condition": completion.get("condition", "NONE"),
                "report_type": task.get("report_type", "NONE"),
            }
        )

    requirements = target.get("requirements") or {}
    return {
        "intent": target.get("intent", "UNSPECIFIED"),
        "priority": target.get("priority", "LOW"),
        "decision": target.get("decision", "REQUEST_CLARIFICATION"),
        "required_capabilities": copy.deepcopy(requirements.get("required_capabilities", [])),
        "preferred_sensor_roles": copy.deepcopy(requirements.get("preferred_sensor_roles", [])),
        "tasks": compact_tasks,
        "constraints_policy": _constraint_policy(target.get("constraints")),
        "contingency_policy": _contingency_policy(target.get("contingencies")),
        "requires_clarification": bool(target.get("requires_clarification", False)),
        "missing_fields": copy.deepcopy(target.get("missing_fields", [])),
        "safe_fallback": target.get("safe_fallback") or "NONE",
        "reason_code": target.get("reason_code") or "NONE",
    }


def clarification_question(missing_fields: list[str]) -> str:
    key = tuple(missing_fields)
    if key in CLARIFICATION_QUESTIONS:
        return CLARIFICATION_QUESTIONS[key]
    if not missing_fields:
        return "임무 수행에 필요한 정보를 추가로 지정해 주세요."
    return "다음 정보를 지정해 주세요: " + ", ".join(missing_fields)


def compile_umdl(ir: dict[str, Any], mission_id: str) -> dict[str, Any]:
    """Compile Compact IR v0.2 into full UMDL 0.1."""
    tasks: list[dict[str, Any]] = []
    for index, item in enumerate(ir.get("tasks", []), 1):
        task: dict[str, Any] = {"id": f"task_{index}", "type": item["type"]}

        target_type = item.get("target_type", "NONE")
        target_reference = item.get("target_reference", "NONE")
        if target_type != "NONE" and target_reference != "NONE":
            task["target"] = {"type": target_type, "reference": target_reference}

        pattern_type = item.get("pattern_type", "NONE")
        pattern_parameters = copy.deepcopy(item.get("pattern_parameters") or {})
        if pattern_type != "NONE":
            task["pattern"] = {"type": pattern_type, **pattern_parameters}

        parameters = copy.deepcopy(item.get("parameters") or {})
        if parameters:
            task["parameters"] = parameters

        completion = item.get("completion_condition", "NONE")
        if completion != "NONE":
            task["completion"] = {"condition": completion}

        report_type = item.get("report_type", "NONE")
        if report_type != "NONE":
            task["report_type"] = report_type
        tasks.append(task)

    constraint_policy = ir.get("constraints_policy", "PLATFORM_DEFAULT")
    if constraint_policy == "SAFE_RETURN_PROFILE":
        constraints = copy.deepcopy(SAFE_RETURN_CONSTRAINTS)
    else:
        constraints = copy.deepcopy(DEFAULT_CONSTRAINTS)

    contingency_policy = ir.get("contingency_policy", "NONE")
    contingencies = copy.deepcopy(CONTINGENCY_TEMPLATES.get(contingency_policy, []))

    safe_fallback = ir.get("safe_fallback", "NONE")
    plan: dict[str, Any] = {
        "schema_version": "umdl/0.1",
        "mission_id": mission_id,
        "intent": ir["intent"],
        "priority": ir["priority"],
        "decision": ir["decision"],
        "requirements": {
            "required_capabilities": copy.deepcopy(ir.get("required_capabilities", [])),
            "preferred_sensor_roles": copy.deepcopy(ir.get("preferred_sensor_roles", [])),
        },
        "tasks": tasks,
        "constraints": constraints,
        "contingencies": contingencies,
        "requires_clarification": bool(ir.get("requires_clarification", False)),
        "missing_fields": copy.deepcopy(ir.get("missing_fields", [])),
        "safe_fallback": None if safe_fallback == "NONE" else safe_fallback,
    }

    if plan["decision"] == "REQUEST_CLARIFICATION":
        plan["clarification_question"] = clarification_question(plan["missing_fields"])

    reason_code = ir.get("reason_code", "NONE")
    if reason_code != "NONE":
        plan["reason_code"] = reason_code
    return plan


def full_roundtrip_equal(target: dict[str, Any]) -> bool:
    """True when full -> compact -> full reproduces the target exactly."""
    compact = compact_from_full(target)
    compiled = compile_umdl(compact, str(target.get("mission_id", "runtime_request")))
    return compiled == target
