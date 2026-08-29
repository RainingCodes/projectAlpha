"""UMDL dataset inspection and platform-independent mission-planning API.

The LLM produces a compact, tightly constrained generation IR. The server then
compiles that IR into the full UMDL document and validates the final document.
The /mission/plan endpoint never publishes ROS commands.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

from app.umdl_codec import COMPACT_SYSTEM_PROMPT, compact_from_full, compile_umdl

LOG = logging.getLogger("llm_control.umdl")


class MissionPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(..., min_length=1)
    runtime_context: dict[str, Any] = Field(default_factory=dict)
    available_capabilities: list[str] = Field(default_factory=list)
    mission_id: str = Field(default="runtime_request", min_length=1)
    force_llm: bool = False


class UMDLSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    hf_api_base: str
    hf_model: str
    ollama_host: str
    ollama_model: str
    temperature: float = 0.0
    max_tokens: int = 512
    timeout_seconds: float = 120.0
    dataset_root: str = "/app/dataset"
    schema_path: str = "/app/dataset/schema/umdl-0.1.schema.json"
    generation_schema_path: str = "/app/dataset/schema/umdl-generation-0.2.schema.json"
    guided_json: bool = False
    guided_decoding_backend: str = "outlines"
    few_shot_enabled: bool = False
    family_hints_enabled: bool = False
    max_retries: int = 0
    safety_fast_path: bool = True


FAMILY_HINTS: dict[str, dict[str, str]] = {
    "obstacle": {
        "expected_intent": "EMERGENCY_RESPONSE",
        "required_task": "AVOID_OBSTACLE",
    },
    "return": {
        "expected_intent": "RETURN_TO_HOME",
        "required_task": "RETURN_HOME",
    },
    "pipeline": {
        "expected_intent": "PIPELINE_INSPECTION",
        "required_task": "INSPECT",
    },
    "sar": {
        "expected_intent": "SEARCH_AND_RESCUE",
        "required_task": "SEARCH",
    },
    "station": {
        "expected_intent": "STATION_KEEPING",
        "required_task": "HOLD_POSITION",
    },
    "area_survey": {
        "expected_intent": "AREA_SURVEY",
        "required_task": "SURVEY",
    },
    "target_search": {
        "expected_intent": "TARGET_SEARCH",
        "required_task": "SEARCH",
    },
    "target_inspection": {
        "expected_intent": "TARGET_INSPECTION",
        "required_task": "INSPECT",
    },
    "environment": {
        "expected_intent": "ENVIRONMENT_MONITORING",
        "required_task": "SAMPLE",
    },
    "navigation": {
        "expected_intent": "NAVIGATION",
        "required_task": "NAVIGATE",
    },
}

FAMILY_POLICIES: dict[str, dict[str, Any]] = {
    "obstacle": {
        "allowed_tasks": ["AVOID_OBSTACLE", "HOLD_POSITION", "REPORT"],
        "first_task": "AVOID_OBSTACLE",
        "safe_fallback": "STOP_AND_HOLD",
        "avoidance_completion": "SAFE_CLEARANCE_ESTABLISHED",
        "hold_completion": "LOCAL_SAFETY_CONFIRMED",
        "report_type": "AVOIDANCE_RESULT",
    },
}




def _deterministic_ir_for_request(req: MissionPlanRequest) -> dict[str, Any] | None:
    """Return a deterministic safety plan for recognized emergency families.

    Immediate obstacle avoidance must not wait for an LLM. The LLM path remains
    available by setting force_llm=true in the request.
    """
    family = _infer_family(req.instruction)
    if family != "obstacle":
        return None

    obstacle_ref = "FRONT_OBSTACLE"
    obstacles = req.runtime_context.get("obstacles")
    if isinstance(obstacles, list) and obstacles:
        first = obstacles[0]
        if isinstance(first, dict):
            raw_id = str(first.get("id") or "").strip().upper()
            normalized = "".join(ch if ch.isalnum() or ch in "_./:-" else "_" for ch in raw_id)
            if normalized:
                obstacle_ref = normalized[:64]

    required = [cap for cap in ("OBSTACLE_AVOIDANCE", "DATA_LOGGING") if cap in req.available_capabilities]
    if "OBSTACLE_AVOIDANCE" not in required:
        required.insert(0, "OBSTACLE_AVOIDANCE")

    return {
        "intent": "EMERGENCY_RESPONSE",
        "priority": "CRITICAL",
        "decision": "EXECUTE",
        "required_capabilities": required,
        "preferred_sensor_roles": ["FORWARD_TARGET_DETECTION"],
        "tasks": [
            {
                "type": "AVOID_OBSTACLE",
                "target_type": "DETECTED_OBSTACLE",
                "target_reference": obstacle_ref,
                "pattern_type": "NONE",
                "pattern_parameters": {},
                "parameters": {},
                "completion_condition": "SAFE_CLEARANCE_ESTABLISHED",
                "report_type": "NONE",
            },
            {
                "type": "HOLD_POSITION",
                "target_type": "CURRENT_POSITION",
                "target_reference": "POST_AVOIDANCE_POSITION",
                "pattern_type": "NONE",
                "pattern_parameters": {},
                "parameters": {},
                "completion_condition": "LOCAL_SAFETY_CONFIRMED",
                "report_type": "NONE",
            },
            {
                "type": "REPORT",
                "target_type": "NONE",
                "target_reference": "NONE",
                "pattern_type": "NONE",
                "pattern_parameters": {},
                "parameters": {},
                "completion_condition": "REPORT_STORED",
                "report_type": "AVOIDANCE_RESULT",
            },
        ],
        "constraints_policy": "PLATFORM_DEFAULT",
        "contingency_policy": "NONE",
        "requires_clarification": False,
        "missing_fields": [],
        "safe_fallback": "STOP_AND_HOLD",
        "reason_code": "NONE",
    }

def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise HTTPException(status_code=503, detail=f"Dataset file not found: {path}")
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Invalid JSONL at {path}:{line_no}: {exc}",
                ) from exc
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _infer_family(instruction: str) -> str | None:
    """Best-effort family hint for retrieval and emergency routing only.

    Benchmark generation does not use this hint unless UMDL_FAMILY_HINTS=1.
    Rules are ordered from safety/specific mission phrases to generic verbs so
    words such as "inspection" do not override "pipeline".
    """
    text = instruction.lower()

    def has(*terms: str) -> bool:
        return any(term.lower() in text for term in terms)

    if has("장애물", "회피", "충돌", "obstacle", "avoid", "clearance"):
        return "obstacle"
    if has("귀환", "복귀", "return home", "return-to-home"):
        return "return"
    if has("파이프라인", "pipeline", " 라인 ", "누수 흔적", "부식 흔적", "라인 쭉 따라"):
        return "pipeline"
    if has("요구조자", "생존자", "search-and-rescue", "rescue", "survivor", "sar search"):
        return "sar"
    if has(
        "수온", "탁도", "염도", "염분", "용존 산소", "수압", "수중 소음", "유속", "산도",
        "전도도", "형광", "water temperature", "turbidity", "salinity", "dissolved oxygen",
        "water pressure", "underwater noise", "current speed", "conductivity", "fluorescence",
        "sampling", "measure "
    ):
        return "environment"
    if has("station keep", "station keeping", "hold the current position", "버티고") or (
        has("현재 위치") and has("유지")
    ):
        return "station"
    if has(
        "전수 조사", "전 구역", "빈 구역 없이", "lawnmower", "survey region", "survey 해",
        "다각형 패턴", "다각형 경로", "나선형 패턴", "나선형 경로", "경계 추종 패턴", "경계 추종 경로",
        "polygon pattern", "spiral pattern", "perimeter"
    ) or (has("구역") and has("간격") and has("조사")):
        return "area_survey"
    if has("수색", "찾아", "탐지되면", "좌표 남겨", "target search", "search region", "detected location"):
        return "target_search"
    if has("정밀 점검", "가까이서 확인", "손상 있으면", "close inspection", "inspect the", "inspection", "anomaly"):
        return "target_inspection"
    if has("이동", "방위", "미터 전진", "navigate", "bearing", "meters on bearing"):
        return "navigation"
    return None


def _select_few_shot(
    dataset_root: Path,
    instruction: str,
) -> dict[str, Any] | None:
    """Select one same-family Compact IR v0.2 few-shot example."""

    family = _infer_family(instruction)
    if family is None:
        return None

    raw_path = dataset_root / "raw" / "train.jsonl"
    compact_path = dataset_root / "chat_compact" / "train.jsonl"

    if not raw_path.exists() or not compact_path.exists():
        return None

    try:
        raw_rows = _load_jsonl(raw_path)
        compact_rows = _load_jsonl(compact_path)
    except HTTPException:
        return None

    # raw dataset에는 canonical_family metadata가 있으므로
    # 여기서 같은 family의 대표 sample ID를 선택한다.
    selected_id: str | None = None

    for row in raw_rows:
        if (
            row.get("metadata", {}).get("canonical_family")
            == family
        ):
            selected_id = row.get("id")
            break

    if not selected_id:
        return None

    # 같은 ID의 Compact IR training example을 찾는다.
    for row in compact_rows:
        if row.get("id") == selected_id:
            return {
                "id": selected_id,
                "family": family,
                "messages": row.get("messages", []),
            }

    return None

def _few_shot_messages(
    example: dict[str, Any],
    family_hints_enabled: bool = False,
) -> list[dict[str, str]]:
    """Build one user/assistant Compact IR v0.2 few-shot pair."""

    messages = example.get("messages", [])

    if not isinstance(messages, list):
        return []

    result: list[dict[str, str]] = []

    family = example.get("family")
    planner_hint = (
        FAMILY_HINTS.get(family)
        if family_hints_enabled and family
        else None
    )

    for message in messages:
        if not isinstance(message, dict):
            continue

        role = message.get("role")
        content = message.get("content")

        # Runtime에는 이미 현재 _system_prompt()가 있으므로
        # dataset의 system message를 다시 넣지 않는다.
        if role not in {"user", "assistant"}:
            continue

        if not isinstance(content, str):
            continue

        # Family hint 실험이 켜진 경우
        # few-shot user payload에도 동일 조건을 적용한다.
        if role == "user" and planner_hint:
            try:
                payload = json.loads(content)

                if isinstance(payload, dict):
                    payload["planner_hint"] = planner_hint

                    content = json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
            except json.JSONDecodeError:
                # Dataset 검증에서 JSON이어야 하지만
                # runtime에서는 안전하게 원본을 유지한다.
                pass

        result.append(
            {
                "role": role,
                "content": content,
            }
        )

    # 정상적인 few-shot은 user + assistant 한 쌍이어야 한다.
    roles = [m["role"] for m in result]

    if roles != ["user", "assistant"]:
        return []

    return result


def _extract_json_object(text: str) -> dict[str, Any]:
    """Parse only the complete model response; never salvage an inner object."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty model response")

    cleaned = raw
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Complete response is not valid JSON: {exc}; preview={raw[:300]!r}"
        ) from exc

    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except json.JSONDecodeError as exc:
            raise ValueError("Model returned a JSON string containing invalid JSON") from exc
    if not isinstance(obj, dict):
        raise ValueError(f"UMDL generation response must be an object, got {type(obj).__name__}")
    return obj


def _system_prompt() -> str:
    return COMPACT_SYSTEM_PROMPT


def _compact_from_full(target: dict[str, Any]) -> dict[str, Any]:
    return compact_from_full(target)


def _compile_umdl(ir: dict[str, Any], req: MissionPlanRequest) -> dict[str, Any]:
    return compile_umdl(ir, req.mission_id)


def _schema_errors(validator: Draft202012Validator, obj: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for error in sorted(validator.iter_errors(obj), key=lambda e: list(e.path)):
        location = ".".join(map(str, error.path)) or "<root>"
        errors.append(f"{location}: {error.message}")
    return errors


def _generation_schema_for_request(
    base_schema: dict[str, Any],
    req: MissionPlanRequest,
    family_hints_enabled: bool,
) -> dict[str, Any]:
    """Optionally narrow guided JSON using a best-effort family hint."""
    schema = copy.deepcopy(base_schema)
    if not family_hints_enabled:
        return schema
    family = _infer_family(req.instruction)
    hint = FAMILY_HINTS.get(family or "")
    policy = FAMILY_POLICIES.get(family or "")
    if not hint:
        return schema

    properties = schema.get("properties", {})
    properties.get("intent", {})["enum"] = [hint["expected_intent"]]
    properties.get("decision", {})["enum"] = ["EXECUTE"]
    properties["requires_clarification"] = {"type": "boolean", "const": False}
    properties.get("missing_fields", {})["maxItems"] = 0
    properties.get("reason_code", {})["enum"] = ["NONE"]

    available = set(req.available_capabilities)
    cap_items = properties.get("required_capabilities", {}).get("items", {})
    supported = cap_items.get("enum", [])
    narrowed = [item for item in supported if item in available]
    if narrowed:
        cap_items["enum"] = narrowed

    if policy:
        task_schema = properties.get("tasks", {})
        task_schema["minItems"] = 1
        task_schema["maxItems"] = len(policy["allowed_tasks"])
        task_type = task_schema.get("items", {}).get("properties", {}).get("type", {})
        task_type["enum"] = list(policy["allowed_tasks"])
        properties.get("safe_fallback", {})["enum"] = [policy["safe_fallback"]]

    return schema

def _make_guided_schema(_: dict[str, Any]) -> dict[str, Any]:
    """Lightweight structural schema for Outlines guided decoding.

    This schema only constrains the JSON structure.
    The original Compact UMDL schema remains responsible for strict
    semantic validation after generation.
    """

    return {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
            },
            "priority": {
                "type": "string",
            },
            "decision": {
                "type": "string",
                "enum": [
                    "EXECUTE",
                    "REQUEST_CLARIFICATION",
                    "REJECT",
                    "UNSUPPORTED",
                ],
            },

            "required_capabilities": {
                "type": "array",
                "items": {
                    "type": "string",
                },
                "maxItems": 8,
            },

            "preferred_sensor_roles": {
                "type": "array",
                "items": {
                    "type": "string",
                },
                "maxItems": 4,
            },

            "tasks": {
                "type": "array",
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                        },
                        "target_type": {
                            "type": "string",
                        },
                        "target_reference": {
                            "type": "string",
                        },
                        "pattern_type": {
                            "type": "string",
                        },

                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },

                        "pattern_parameters": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },

                        "completion_condition": {
                            "type": "string",
                        },
                        "report_type": {
                            "type": "string",
                        },
                    },
                    "required": [
                        "type",
                        "target_type",
                        "target_reference",
                        "pattern_type",
                        "parameters",
                        "pattern_parameters",
                        "completion_condition",
                        "report_type",
                    ],
                    "additionalProperties": False,
                },
            },

            "constraints_policy": {
                "type": "string",
            },
            "contingency_policy": {
                "type": "string",
            },
            "requires_clarification": {
                "type": "boolean",
            },

            "missing_fields": {
                "type": "array",
                "items": {
                    "type": "string",
                },
                "maxItems": 8,
            },

            "safe_fallback": {
                "type": "string",
            },
            "reason_code": {
                "type": "string",
            },
        },

        "required": [
            "intent",
            "priority",
            "decision",
            "required_capabilities",
            "preferred_sensor_roles",
            "tasks",
            "constraints_policy",
            "contingency_policy",
            "requires_clarification",
            "missing_fields",
            "safe_fallback",
            "reason_code",
        ],

        "additionalProperties": False,
    }

def _generation_rule_errors(ir: dict[str, Any], req: MissionPlanRequest, family_hints_enabled: bool) -> list[str]:
    errors: list[str] = []
    decision = ir.get("decision")
    tasks = ir.get("tasks", [])
    required = ir.get("required_capabilities", [])
    requires_clarification = bool(ir.get("requires_clarification", False))
    missing_fields = ir.get("missing_fields", [])
    reason_code = ir.get("reason_code", "NONE")

    missing_caps = sorted(set(required) - set(req.available_capabilities))
    if missing_caps:
        errors.append(f"required capabilities unavailable: {missing_caps}")

    if decision == "EXECUTE":
        if not tasks:
            errors.append("EXECUTE requires at least one task")
        if requires_clarification:
            errors.append("EXECUTE requires requires_clarification=false")
        if missing_fields:
            errors.append("EXECUTE requires missing_fields=[]")
        if reason_code != "NONE":
            errors.append("EXECUTE requires reason_code=NONE")
    elif decision == "REQUEST_CLARIFICATION":
        if tasks:
            errors.append("REQUEST_CLARIFICATION must have an empty tasks list")
        if not requires_clarification:
            errors.append("REQUEST_CLARIFICATION requires requires_clarification=true")
        if not missing_fields:
            errors.append("REQUEST_CLARIFICATION requires at least one missing field")
    elif decision in {"REJECT", "UNSUPPORTED"}:
        if tasks:
            errors.append(f"{decision} must have an empty tasks list")
        if requires_clarification:
            errors.append(f"{decision} requires requires_clarification=false")
        if reason_code == "NONE":
            errors.append(f"{decision} requires a non-NONE reason_code")
    else:
        errors.append(f"unknown decision: {decision!r}")

    family = _infer_family(req.instruction) if family_hints_enabled else None
    hint = FAMILY_HINTS.get(family or "")
    policy = FAMILY_POLICIES.get(family or "")
    if hint and decision == "EXECUTE":
        if ir.get("intent") != hint["expected_intent"]:
            errors.append(f"{family} requires intent={hint['expected_intent']}")
        task_types = [task.get("type") for task in tasks if isinstance(task, dict)]
        if hint["required_task"] not in task_types:
            errors.append(f"{family} requires task={hint['required_task']}")

    if policy and decision == "EXECUTE":
        task_types = [task.get("type") for task in tasks if isinstance(task, dict)]
        disallowed = [t for t in task_types if t not in set(policy["allowed_tasks"])]
        if disallowed:
            errors.append(f"{family} contains disallowed tasks: {disallowed}")
        if not task_types or task_types[0] != policy["first_task"]:
            errors.append(f"{family} first task must be {policy['first_task']}")
        if len(task_types) != len(set(task_types)):
            errors.append(f"{family} must not contain duplicate task types")
        if ir.get("safe_fallback") != policy["safe_fallback"]:
            errors.append(f"{family} requires safe_fallback={policy['safe_fallback']}")

        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_type = task.get("type")
            if task_type == "AVOID_OBSTACLE":
                if task.get("target_type") != "DETECTED_OBSTACLE":
                    errors.append("AVOID_OBSTACLE requires target_type=DETECTED_OBSTACLE")
                if task.get("completion_condition") != policy["avoidance_completion"]:
                    errors.append(
                        "AVOID_OBSTACLE requires completion_condition="
                        + policy["avoidance_completion"]
                    )
            elif task_type == "HOLD_POSITION":
                if task.get("target_type") != "CURRENT_POSITION":
                    errors.append("HOLD_POSITION requires target_type=CURRENT_POSITION")
                if task.get("completion_condition") != policy["hold_completion"]:
                    errors.append(
                        "HOLD_POSITION requires completion_condition="
                        + policy["hold_completion"]
                    )
            elif task_type == "REPORT":
                if task.get("report_type") != policy["report_type"]:
                    errors.append("REPORT requires report_type=" + policy["report_type"] )

    return errors


def _final_rule_errors(plan: dict[str, Any], available_capabilities: list[str]) -> list[str]:
    errors: list[str] = []
    decision = plan.get("decision")
    tasks = plan.get("tasks")
    required = plan.get("requirements", {}).get("required_capabilities", [])
    if decision == "EXECUTE":
        if not isinstance(tasks, list) or not tasks:
            errors.append("EXECUTE requires at least one task")
        missing_caps = sorted(set(required) - set(available_capabilities))
        if missing_caps:
            errors.append(f"required capabilities unavailable: {missing_caps}")
    elif decision == "REQUEST_CLARIFICATION":
        if plan.get("requires_clarification") is not True:
            errors.append("REQUEST_CLARIFICATION requires requires_clarification=true")
        if tasks:
            errors.append("REQUEST_CLARIFICATION must not contain tasks")
    elif decision in {"REJECT", "UNSUPPORTED"}:
        if tasks:
            errors.append(f"{decision} must not contain tasks")
        if not plan.get("reason_code"):
            errors.append(f"{decision} requires reason_code")
    else:
        errors.append(f"unknown decision: {decision!r}")
    return errors


async def _call_model(
    settings: UMDLSettings,
    req: MissionPlanRequest,
    generation_schema: dict[str, Any],
    few_shot: dict[str, Any] | None = None,
    correction: str | None = None,
) -> tuple[str, dict[str, Any]]:
    provider = settings.provider.lower()
    if provider == "hf":
        provider = "huggingface"

    messages: list[dict[str, str]] = [{"role": "system", "content": _system_prompt()}]
    if settings.few_shot_enabled and few_shot is not None:
        messages.extend(_few_shot_messages(few_shot, settings.family_hints_enabled))

    family = _infer_family(req.instruction) if settings.family_hints_enabled else None
    current_payload: dict[str, Any] = {
        "instruction": req.instruction,
        "runtime_context": req.runtime_context,
        "available_capabilities": req.available_capabilities,
    }
    if family is not None:
        current_payload["planner_hint"] = FAMILY_HINTS.get(family, {})
    if correction:
        current_payload["correction"] = correction
    messages.append({"role": "user", "content": json.dumps(current_payload, ensure_ascii=False, separators=(",", ":"))})

    if provider == "huggingface":
        if not settings.hf_model.strip():
            raise HTTPException(status_code=503, detail="HUGGINGFACE_MODEL is not configured")
        url = f"{settings.hf_api_base.rstrip('/')}/chat/completions"
        headers: dict[str, str] = {}
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request_payload: dict[str, Any] = {
            "model": settings.hf_model.strip(),
            "messages": messages,
            "temperature": settings.temperature,
            "max_tokens": settings.max_tokens,
            "stream": False,
        }
        if settings.guided_json:
            request_payload["guided_json"] = generation_schema
            request_payload["guided_decoding_backend"] = settings.guided_decoding_backend
        else:
            request_payload["response_format"] = {
                "type": "json_object"
            }
    elif provider == "ollama":
        url = f"{settings.ollama_host.rstrip('/')}/v1/chat/completions"
        headers = {"Authorization": "Bearer ollama"}
        request_payload = {
            "model": settings.ollama_model,
            "messages": messages,
            "temperature": settings.temperature,
            "max_tokens": settings.max_tokens,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
    else:
        raise HTTPException(status_code=503, detail=f"Unsupported LLM provider: {settings.provider}")

    started = time.perf_counter()
    try:
        timeout = httpx.Timeout(
            connect=min(15.0, settings.timeout_seconds),
            read=settings.timeout_seconds,
            write=min(30.0, settings.timeout_seconds),
            pool=min(15.0, settings.timeout_seconds),
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=request_payload, headers=headers)
    except httpx.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        raise HTTPException(
            status_code=502,
            detail={
                "message": "UMDL model call failed",
                "exception_type": type(exc).__name__,
                "exception_repr": repr(exc),
                "url": url,
                "timeout_seconds": settings.timeout_seconds,
                "elapsed_ms": round(elapsed_ms, 3),
            },
        ) from exc
    http_ms = (time.perf_counter() - started) * 1000.0
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"UMDL model API error {response.status_code}: {response.text[:1000]}")
    body = response.json()
    try:
        choice = body["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=502, detail=f"Unexpected UMDL model response: {body}") from exc
    return str(content), {
        "llm_http_ms": round(http_ms, 3),
        "finish_reason": choice.get("finish_reason"),
        "usage": body.get("usage"),
    }

def _select_fixed_few_shot(
    dataset_root: Path,
    example_id: str = "nav_004_02",
) -> dict[str, Any] | None:
    compact_path = dataset_root / "chat_compact" / "train.jsonl"

    if not compact_path.exists():
        return None

    try:
        rows = _load_jsonl(compact_path)
    except HTTPException:
        return None

    for row in rows:
        if row.get("id") == example_id:
            return {
                "id": example_id,
                "family": None,
                "messages": row.get("messages", []),
            }

    return None

def create_umdl_router(settings_dict: dict[str, Any]) -> APIRouter:
    settings = UMDLSettings(**settings_dict)
    router = APIRouter(tags=["UMDL"])
    dataset_root = Path(settings.dataset_root)
    schema_path = Path(settings.schema_path)
    generation_schema_path = Path(settings.generation_schema_path)

    try:
        full_schema = json.loads(schema_path.read_text(encoding="utf-8"))
        generation_schema = json.loads(generation_schema_path.read_text(encoding="utf-8"))
        full_validator = Draft202012Validator(full_schema)
        generation_validator = Draft202012Validator(generation_schema)
        schema_error: str | None = None
    except Exception as exc:
        full_schema = {}
        generation_schema = {}
        full_validator = None
        generation_validator = None
        schema_error = str(exc)
        LOG.exception("Failed to load UMDL schemas")

    @router.get("/umdl/health")
    async def umdl_health() -> dict[str, Any]:
        files = {}
        for split in ("train", "validation", "test"):
            path = dataset_root / "raw" / f"{split}.jsonl"
            files[split] = {"path": str(path), "exists": path.exists()}
        return {
            "schema_path": str(schema_path),
            "schema_ready": full_validator is not None,
            "generation_schema_path": str(generation_schema_path),
            "generation_schema_ready": generation_validator is not None,
            "schema_error": schema_error,
            "dataset_root": str(dataset_root),
            "dataset_files": files,
            "planner_publishes_ros_commands": False,
            "planner_max_tokens": settings.max_tokens,
            "guided_json": settings.guided_json,
            "guided_decoding_backend": settings.guided_decoding_backend,
            "few_shot_enabled": settings.few_shot_enabled,
            "family_hints_enabled": settings.family_hints_enabled,
            "max_retries": settings.max_retries,
            "planner_timeout_seconds": settings.timeout_seconds,
            "safety_fast_path": settings.safety_fast_path,
            "generation_mode": "compact_ir_v0.2_then_compile",
        }

    @router.get("/dataset/stats")
    async def dataset_stats() -> dict[str, Any]:
        rows = _load_jsonl(dataset_root / "raw" / "all.jsonl")
        return {
            "sample_count": len(rows),
            "group_count": len({r.get("group_id") for r in rows}),
            "split": dict(sorted(Counter(r.get("split") for r in rows).items())),
            "family": dict(sorted(Counter(r.get("metadata", {}).get("canonical_family") for r in rows).items())),
            "decision": dict(sorted(Counter(r.get("target", {}).get("decision") for r in rows).items())),
            "language": dict(sorted(Counter(r.get("metadata", {}).get("language") for r in rows).items())),
        }

    @router.get("/dataset/sample")
    async def dataset_sample(
        split: str = Query(default="test", pattern="^(train|validation|test)$"),
        index: int = Query(default=0, ge=0),
        group_id: str | None = None,
    ) -> dict[str, Any]:
        rows = _load_jsonl(dataset_root / "raw" / f"{split}.jsonl")
        if group_id:
            selected = [r for r in rows if r.get("group_id") == group_id]
            if not selected:
                raise HTTPException(status_code=404, detail=f"group_id not found in {split}: {group_id}")
            return {"split": split, "group_id": group_id, "samples": selected}
        if index >= len(rows):
            raise HTTPException(status_code=404, detail=f"index out of range; sample_count={len(rows)}")
        return rows[index]

    @router.post("/mission/plan")
    async def mission_plan(req: MissionPlanRequest) -> dict[str, Any]:
        if full_validator is None or generation_validator is None:
            raise HTTPException(status_code=503, detail=f"UMDL schemas unavailable: {schema_error}")

        if settings.safety_fast_path and not req.force_llm:
            deterministic_ir = _deterministic_ir_for_request(req)
            if deterministic_ir is not None:
                generation_schema_errors = _schema_errors(generation_validator, deterministic_ir)
                generation_rule_errors = _generation_rule_errors(deterministic_ir, req, settings.family_hints_enabled)
                deterministic_plan = _compile_umdl(deterministic_ir, req)
                final_schema_errors = _schema_errors(full_validator, deterministic_plan)
                final_rule_errors = _final_rule_errors(deterministic_plan, req.available_capabilities)
                all_errors = (
                    generation_schema_errors
                    + generation_rule_errors
                    + final_schema_errors
                    + final_rule_errors
                )
                if all_errors:
                    raise HTTPException(
                        status_code=500,
                        detail={
                            "message": "Deterministic safety plan failed validation",
                            "errors": all_errors,
                        },
                    )
                return {
                    "valid": True,
                    "plan": deterministic_plan,
                    "validation": {
                        "schema_errors": [],
                        "rule_errors": [],
                        "attempts": [],
                    },
                    "generation": {
                        "mode": "deterministic_safety_fast_path",
                        "ir": deterministic_ir,
                        "few_shot_family": None,
                        "guided_json": False,
                        "guided_decoding_backend": None,
                        "schema_scope": "family_constrained",
                        "semantic_policy": "obstacle",
                    },
                    "timing_ms": {"llm_http_ms": 0.0},
                    "execution": {
                        "ros_command_published": False,
                        "next_step": "Send the validated safety plan to the platform safety adapter/compiler.",
                    },
                }

        few_shot = (
            _select_fixed_few_shot(dataset_root)
            if settings.few_shot_enabled
            else None
        )
        request_generation_schema = _generation_schema_for_request(
            generation_schema, req, settings.family_hints_enabled
        )
        request_generation_validator = Draft202012Validator(request_generation_schema)
        guided_generation_schema = (
            _make_guided_schema(request_generation_schema)
            if settings.guided_json
            else request_generation_schema
        )
        attempts: list[dict[str, Any]] = []
        correction: str | None = None
        final_ir: dict[str, Any] | None = None
        final_plan: dict[str, Any] | None = None
        final_errors: list[str] = []
        total_http_ms = 0.0
        last_raw_preview = ""

        for attempt_no in range(settings.max_retries + 1):
            try:
                content, model_meta = await _call_model(
                    settings,
                    req,
                    guided_generation_schema,
                    few_shot=few_shot,
                    correction=correction,
                )
            except HTTPException as exc:
                attempts.append(
                    {
                        "attempt": attempt_no + 1,
                        "model_error": exc.detail,
                    }
                )
                raise HTTPException(
                    status_code=502,
                    detail={
                        "message": "The model call failed before a mission plan was produced.",
                        "attempts": attempts,
                        "guided_json": settings.guided_json,
                    },
                ) from exc
            total_http_ms += float(model_meta["llm_http_ms"])
            last_raw_preview = content[:500]
            attempt: dict[str, Any] = {
                "attempt": attempt_no + 1,
                "finish_reason": model_meta.get("finish_reason"),
                "usage": model_meta.get("usage"),
            }
            try:
                ir = _extract_json_object(content)
            except ValueError as exc:
                attempt["parse_error"] = str(exc)
                attempts.append(attempt)
                correction = (
                    "The previous output was incomplete or invalid. Return one complete compact JSON object. "
                    "Keep tasks to at most 3 unless absolutely necessary."
                )
                continue

            generation_schema_errors = _schema_errors(request_generation_validator, ir)
            generation_rule_errors = _generation_rule_errors(ir, req, settings.family_hints_enabled)
            attempt["generation_schema_error_count"] = len(generation_schema_errors)
            attempt["generation_rule_error_count"] = len(generation_rule_errors)
            if generation_schema_errors or generation_rule_errors:
                attempts.append(attempt)
                correction = "Fix these errors and regenerate the full compact object: " + json.dumps(
                    generation_schema_errors + generation_rule_errors, ensure_ascii=False
                )
                final_ir = ir
                final_errors = generation_schema_errors + generation_rule_errors
                continue

            plan = _compile_umdl(ir, req)
            final_schema_errors = _schema_errors(full_validator, plan)
            final_rule_errors = _final_rule_errors(plan, req.available_capabilities)
            attempt["final_schema_error_count"] = len(final_schema_errors)
            attempt["final_rule_error_count"] = len(final_rule_errors)
            attempts.append(attempt)
            final_ir = ir
            final_plan = plan
            final_errors = final_schema_errors + final_rule_errors
            if not final_errors:
                break
            correction = "Fix these final validation errors and regenerate the compact object: " + json.dumps(
                final_errors, ensure_ascii=False
            )

        if final_plan is None or final_errors:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "The model failed to produce a valid compact mission plan.",
                    "attempts": attempts,
                    "generation_ir": final_ir,
                    "raw_preview": last_raw_preview,
                    "guided_json": settings.guided_json,
                },
            )

        return {
            "valid": True,
            "plan": final_plan,
            "validation": {"schema_errors": [], "rule_errors": [], "attempts": attempts},
            "generation": {
                "mode": "compact_ir_v0.2_then_compile",
                "ir": final_ir,
                "few_shot_family": _infer_family(req.instruction) if few_shot else None,
                "guided_json": settings.guided_json,
                "guided_decoding_backend": settings.guided_decoding_backend if settings.guided_json else None,
                "schema_scope": (
                    "family_constrained"
                    if settings.family_hints_enabled and _infer_family(req.instruction) in FAMILY_POLICIES
                    else "base"
                ),
                "semantic_policy": (
                    _infer_family(req.instruction)
                    if settings.family_hints_enabled and _infer_family(req.instruction) in FAMILY_POLICIES
                    else None
                ),
            },
            "timing_ms": {"llm_http_ms": round(total_http_ms, 3)},
            "execution": {
                "ros_command_published": False,
                "next_step": "Pass the validated UMDL plan to a platform adapter/compiler.",
            },
        }

    return router
