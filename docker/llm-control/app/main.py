"""
HTTP LLM 제어 서버 + ROS 2 DDS 브리지.

Stonefish가 돌아가는 다른 컨테이너와 동일 ROS_DOMAIN_ID·RMW(CycloneDDS)·
CYCLONEDDS_URI(피어 디스커버리)로 /GIRONA500/dynamics 구독, /GIRONA500/cmd_vel 발행.

설정 우선순위: 환경 변수(비어 있지 않으면) → JSON 최상단 키 → JSON "model" 블록 → 기본값.
JSON 경로: LLM_CONFIG_PATH (기본 /app/llm_app_settings.json).

모델은 LLM_PROVIDER 로 선택: ollama | huggingface (별칭 hf).
  - Ollama: OLLAMA_HOST + OLLAMA_MODEL (태그 예: llama3.2:3b)
  - Hugging Face: HF_API_BASE 의 /v1/chat/completions (OpenAI 호환) 호출 + HUGGINGFACE_MODEL.
    - 원격: HF_API_BASE=https://router.huggingface.co/v1 → HF_TOKEN(또는 HUGGINGFACE_HUB_TOKEN) 필수.
    - 로컬: 호스트에서 TGI/vLLM 등으로 띄운 주소(예: http://host.docker.internal:8080/v1) → 토큰 없이 가능(서버가 요구하면 설정).
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
import os
import threading
import time
from typing import Any

import httpx
import rclpy
from fastapi import FastAPI, HTTPException
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from pydantic import BaseModel, ConfigDict, Field
from app.umdl_router import create_umdl_router
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

LOG = logging.getLogger("llm_control")
logging.basicConfig(level=logging.INFO)


def _load_json_config(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        LOG.info("LLM JSON 설정 없음: %s", path)
        return {}
    except json.JSONDecodeError as e:
        LOG.warning("LLM JSON 설정 파싱 실패 (%s): %s", path, e)
        return {}
    if not isinstance(data, dict):
        LOG.warning("LLM JSON 설정은 객체(dict)여야 함: %s", path)
        return {}
    return data


def _env_nonempty(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


LLM_CONFIG_PATH = os.environ.get("LLM_CONFIG_PATH", "/app/llm_app_settings.json")
_file_cfg = _load_json_config(LLM_CONFIG_PATH)
if _file_cfg:
    LOG.info("LLM JSON 설정 로드: %s keys=%s", LLM_CONFIG_PATH, sorted(_file_cfg.keys()))


def _model_block() -> dict[str, Any]:
    m = _file_cfg.get("model")
    return m if isinstance(m, dict) else {}


def _pick_str(env_key: str, default: str, *file_keys: str) -> str:
    """env → JSON flat → JSON model.* (file_keys 순서대로)."""
    ev = _env_nonempty(env_key)
    if ev is not None:
        return ev
    mb = _model_block()
    for fk in file_keys:
        if fk in _file_cfg:
            v = _file_cfg.get(fk)
            if v is not None and str(v).strip() != "":
                return str(v).strip()
    for fk in file_keys:
        if fk in mb:
            v = mb.get(fk)
            if v is not None and str(v).strip() != "":
                return str(v).strip()
    return default


def _pick_float(env_key: str, default: float, *file_keys: str) -> float:
    ev = _env_nonempty(env_key)
    if ev is not None:
        try:
            return float(ev)
        except ValueError:
            LOG.warning("실수가 아닌 환경 변수 %s=%r → 기본값 %s", env_key, ev, default)
    for fk in file_keys:
        if fk in _file_cfg:
            try:
                return float(_file_cfg[fk])
            except (TypeError, ValueError):
                pass
    mb = _model_block()
    for fk in file_keys:
        if fk in mb:
            try:
                return float(mb[fk])
            except (TypeError, ValueError):
                pass
    return default


def _pick_hf_model(default: str = "") -> str:
    for ek in ("HUGGINGFACE_MODEL", "HF_MODEL"):
        ev = _env_nonempty(ek)
        if ev is not None:
            return ev
    for fk in ("HUGGINGFACE_MODEL", "HF_MODEL", "huggingface_model", "hf_model"):
        if fk in _file_cfg:
            v = _file_cfg.get(fk)
            if v is not None and str(v).strip() != "":
                return str(v).strip()
    mb = _model_block()
    for fk in ("huggingface_model", "hf_model"):
        if fk in mb:
            v = mb.get(fk)
            if v is not None and str(v).strip() != "":
                return str(v).strip()
    return default


def _str_setting(name: str, default: str) -> str:
    return _pick_str(name, default, name)


def _int_setting(name: str, default: int) -> int:
    ev = _env_nonempty(name)
    if ev is not None:
        try:
            return int(ev)
        except ValueError:
            LOG.warning("정수가 아닌 환경 변수 %s=%r → 기본값 %s", name, ev, default)
    if name in _file_cfg:
        try:
            return int(_file_cfg[name])
        except (TypeError, ValueError):
            LOG.warning("정수가 아닌 JSON 키 %s=%r → 기본값 %s", name, _file_cfg.get(name), default)
    mb = _model_block()
    if name in mb:
        try:
            return int(mb[name])
        except (TypeError, ValueError):
            LOG.warning("정수가 아닌 model.%s=%r → 기본값 %s", name, mb.get(name), default)
    return default


def _bool_setting(name: str, default: bool) -> bool:
    ev = _env_nonempty(name)
    if ev is not None:
        return ev.lower() in ("1", "true", "yes", "on")
    if name in _file_cfg:
        fv = _file_cfg[name]
        if isinstance(fv, bool):
            return fv
        if fv is not None and str(fv).strip() != "":
            return str(fv).strip().lower() in ("1", "true", "yes", "on")
    mb = _model_block()
    if name in mb:
        fv = mb[name]
        if isinstance(fv, bool):
            return fv
        if fv is not None and str(fv).strip() != "":
            return str(fv).strip().lower() in ("1", "true", "yes", "on")
    return default


def _bool_dummy() -> bool:
    ev = _env_nonempty("LLM_DUMMY")
    if ev is not None:
        return ev.lower() in ("1", "true", "yes", "on")
    if "LLM_DUMMY" in _file_cfg:
        fv = _file_cfg["LLM_DUMMY"]
        if isinstance(fv, bool):
            return fv
        if fv is not None and str(fv).strip() != "":
            return str(fv).strip().lower() in ("1", "true", "yes", "on")
    mb = _model_block()
    if "LLM_DUMMY" in mb or "llm_dummy" in mb:
        fv = mb.get("LLM_DUMMY", mb.get("llm_dummy"))
        if isinstance(fv, bool):
            return fv
        if fv is not None and str(fv).strip() != "":
            return str(fv).strip().lower() in ("1", "true", "yes", "on")
    return False


ODOM_TOPIC = _str_setting("ODOM_TOPIC", "/GIRONA500/dynamics")
CMD_VEL_TOPIC = _str_setting("CMD_VEL_TOPIC", "/GIRONA500/cmd_vel")

LLM_PROVIDER = _pick_str("LLM_PROVIDER", "ollama", "LLM_PROVIDER", "provider").lower()
if LLM_PROVIDER in ("hf",):
    LLM_PROVIDER = "huggingface"
if LLM_PROVIDER not in ("ollama", "huggingface"):
    LOG.warning("알 수 없는 LLM_PROVIDER=%r → ollama 로 처리", LLM_PROVIDER)
    LLM_PROVIDER = "ollama"

OLLAMA_HOST = _pick_str("OLLAMA_HOST", "http://ollama:11434", "OLLAMA_HOST", "ollama_host").rstrip(
    "/"
)
OLLAMA_MODEL = _pick_str("OLLAMA_MODEL", "medgemma:4b", "OLLAMA_MODEL", "ollama_model")

HF_API_BASE = _pick_str(
    "HF_API_BASE",
    "https://router.huggingface.co/v1",
    "HF_API_BASE",
    "huggingface_api_base",
).rstrip("/")
HUGGINGFACE_MODEL = _pick_hf_model("")


def _hf_requires_hub_token() -> bool:
    """Hugging Face 클라우드 라우터/레거시 추론 API면 Hub 토큰이 필요하다."""
    u = HF_API_BASE.lower()
    return "router.huggingface.co" in u or "api-inference.huggingface.co" in u


LLM_TEMPERATURE = _pick_float("LLM_TEMPERATURE", 0.2, "LLM_TEMPERATURE", "temperature")
LLM_MAX_TOKENS = _int_setting("LLM_MAX_TOKENS", 64)
LLM_HTTP_TIMEOUT = _pick_float("LLM_HTTP_TIMEOUT", 120.0, "LLM_HTTP_TIMEOUT", "http_timeout")

LLM_DUMMY = _bool_dummy()
LLM_CONTROL_PORT = _int_setting("LLM_CONTROL_PORT", 8080)
UMDL_MAX_TOKENS = _int_setting("UMDL_MAX_TOKENS", 512)
UMDL_GUIDED_JSON = _bool_setting("UMDL_GUIDED_JSON", False)
UMDL_GUIDED_BACKEND = _str_setting("UMDL_GUIDED_BACKEND", "outlines")
UMDL_FEW_SHOT = _bool_setting("UMDL_FEW_SHOT", False)
UMDL_FAMILY_HINTS = _bool_setting("UMDL_FAMILY_HINTS", False)
UMDL_MAX_RETRIES = _int_setting("UMDL_MAX_RETRIES", 0)
UMDL_SAFETY_FAST_PATH = _bool_setting("UMDL_SAFETY_FAST_PATH", True)
UMDL_DATASET_ROOT = _str_setting("UMDL_DATASET_ROOT", "/app/dataset")
UMDL_SCHEMA_PATH = _str_setting("UMDL_SCHEMA_PATH", "/app/dataset/schema/umdl-0.1.schema.json")
UMDL_GENERATION_SCHEMA_PATH = _str_setting("UMDL_GENERATION_SCHEMA_PATH", "/app/dataset/schema/umdl-generation-0.2.schema.json")
LEGACY_DIRECT_CONTROL_ENABLED = _bool_setting("LEGACY_DIRECT_CONTROL_ENABLED", False)

LOG.info(
    "LLM backend provider=%s | ollama=%s@%s | huggingface model=%s @ %s "
    "(hub_token=%s, max_tokens=%s, timeout=%.1fs)",
    LLM_PROVIDER,
    OLLAMA_MODEL,
    OLLAMA_HOST,
    HUGGINGFACE_MODEL or "-",
    HF_API_BASE,
    "required" if _hf_requires_hub_token() else "optional(local)",
    LLM_MAX_TOKENS,
    LLM_HTTP_TIMEOUT,
)


class HighLevelCommand(BaseModel):
    instruction: str = Field(..., description="자연어 제어 목표 (예: 천천히 전진)")


class TwistOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    linear_x: float = 0.0
    linear_y: float = 0.0
    linear_z: float = 0.0
    angular_x: float = 0.0
    angular_y: float = 0.0
    angular_z: float = 0.0


class RosBridge(Node):
    def __init__(self) -> None:
        super().__init__("llm_control_bridge")
        self._lock = threading.Lock()
        self._odom: Odometry | None = None
        self._pub = self.create_publisher(Twist, CMD_VEL_TOPIC, 10)
        self.create_subscription(Odometry, ODOM_TOPIC, self._on_odom, 10)
        self.get_logger().info(
            f"bridge: subscribe {ODOM_TOPIC}, publish {CMD_VEL_TOPIC}"
        )

    def _on_odom(self, msg: Odometry) -> None:
        with self._lock:
            self._odom = msg

    def latest_odom_summary(self) -> dict[str, Any]:
        with self._lock:
            if self._odom is None:
                return {"available": False}
            p = self._odom.pose.pose.position
            o = self._odom.pose.pose.orientation
            return {
                "available": True,
                "position": {"x": p.x, "y": p.y, "z": p.z},
                "orientation": {"x": o.x, "y": o.y, "z": o.z, "w": o.w},
            }

    def publish_twist(self, t: TwistOut) -> None:
        msg = Twist()
        msg.linear.x = float(t.linear_x)
        msg.linear.y = float(t.linear_y)
        msg.linear.z = float(t.linear_z)
        msg.angular.x = float(t.angular_x)
        msg.angular.y = float(t.angular_y)
        msg.angular.z = float(t.angular_z)
        self._pub.publish(msg)
        self.get_logger().info(
            f"cmd_vel linear=({msg.linear.x:.3f},{msg.linear.y:.3f},{msg.linear.z:.3f}) "
            f"angular=({msg.angular.x:.3f},{msg.angular.y:.3f},{msg.angular.z:.3f})"
        )


_bridge: RosBridge | None = None
_executor: MultiThreadedExecutor | None = None
_ros_thread: threading.Thread | None = None


def _ros_spin() -> None:
    global _executor
    rclpy.init()
    node = RosBridge()
    global _bridge
    _bridge = node
    _executor = MultiThreadedExecutor()
    _executor.add_node(node)
    try:
        _executor.spin()
    finally:
        _executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


def start_ros_background() -> None:
    global _ros_thread
    if _ros_thread and _ros_thread.is_alive():
        return
    _ros_thread = threading.Thread(target=_ros_spin, daemon=True)
    _ros_thread.start()
    deadline = time.time() + 15.0
    while time.time() < deadline and _bridge is None:
        time.sleep(0.05)


def _dummy_twist(instruction: str) -> TwistOut:
    if "전진" in instruction or "forward" in instruction.lower():
        return TwistOut(linear_x=0.15)
    if "후진" in instruction or "back" in instruction.lower():
        return TwistOut(linear_x=-0.10)
    if "정지" in instruction or "멈" in instruction or "stop" in instruction.lower():
        return TwistOut()
    if "회전" in instruction or "turn" in instruction.lower():
        return TwistOut(angular_z=0.1)
    return TwistOut(linear_x=0.05)


def _is_stationary(t: TwistOut) -> bool:
    return (
        abs(t.linear_x) < 1e-5
        and abs(t.linear_y) < 1e-5
        and abs(t.linear_z) < 1e-5
        and abs(t.angular_x) < 1e-5
        and abs(t.angular_y) < 1e-5
        and abs(t.angular_z) < 1e-5
    )


def _twist_with_zero_fallback(t: TwistOut, instruction: str) -> TwistOut:
    """일부 소형 LLM이 JSON은 맞추지만 속도를 전부 0으로 내는 경우 보완."""
    if not _is_stationary(t):
        return t
    fb = _dummy_twist(instruction)
    if not _is_stationary(fb):
        LOG.info("LLM이 정지(0)만 반환 → 휴리스틱으로 대체")
        return fb
    return t


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _sanitize_twist(t: TwistOut) -> TwistOut:
    """LLM 출력이 안전 범위를 넘지 않도록 최종 클램프."""
    return TwistOut(
        linear_x=_clamp(t.linear_x, -0.5, 0.5),
        linear_y=_clamp(t.linear_y, -0.3, 0.3),
        linear_z=_clamp(t.linear_z, -0.3, 0.3),
        angular_x=_clamp(t.angular_x, -0.3, 0.3),
        angular_y=_clamp(t.angular_y, -0.3, 0.3),
        angular_z=_clamp(t.angular_z, -0.3, 0.3),
    )

TWIST_KEYS = {
    "linear_x",
    "linear_y",
    "linear_z",
    "angular_x",
    "angular_y",
    "angular_z",
}


def _twist_from_twist_dict(obj: dict[str, Any]) -> TwistOut:
    """
    linear_x 등 Twist 키가 들어 있는 dict를 TwistOut으로 변환한다.
    일부 키가 없어도 0.0으로 채운다.
    """
    vals = {k: obj.get(k, 0.0) for k in TWIST_KEYS}
    return _sanitize_twist(TwistOut(**vals))


def _infer_twist_from_text(text: str) -> TwistOut | None:
    """
    EXAONE이 position_follow/target/position 같은 다른 스키마를 반환했을 때,
    JSON 문자열 전체의 의미를 보고 보수적으로 Twist로 변환한다.
    """
    raw = text.lower()

    if "stop" in raw or "정지" in raw or "멈" in raw:
        return TwistOut()

    if "backward" in raw or "reverse" in raw or "back" in raw or "후진" in raw:
        return TwistOut(linear_x=-0.10)

    if "forward" in raw or "move" in raw or "전진" in raw:
        return TwistOut(linear_x=0.15)

    if "left" in raw or "좌회전" in raw or "왼쪽" in raw:
        return TwistOut(angular_z=0.10)

    if "right" in raw or "우회전" in raw or "오른쪽" in raw:
        return TwistOut(angular_z=-0.10)

    if "turn" in raw or "rotate" in raw or "회전" in raw:
        return TwistOut(angular_z=0.10)

    return None


def _find_twist_dict(obj: Any) -> dict[str, Any] | None:
    """
    중첩 dict/list 안에서 linear_x, angular_z 같은 Twist 키가 들어 있는 객체를 찾는다.
    예:
    - {"linear_x": 0.15, ...}
    - {"twist": {"linear_x": 0.15, ...}}
    - {"result": {"cmd_vel": {"linear_x": 0.15, ...}}}
    """
    if isinstance(obj, dict):
        if any(k in obj for k in TWIST_KEYS):
            return obj

        # 자주 나올 수 있는 wrapper key 우선 탐색
        for key in ("twist", "cmd_vel", "velocity", "control", "command", "output", "result"):
            inner = obj.get(key)
            found = _find_twist_dict(inner)
            if found is not None:
                return found

        # 그 외 모든 값 재귀 탐색
        for value in obj.values():
            found = _find_twist_dict(value)
            if found is not None:
                return found

    if isinstance(obj, list):
        for item in obj:
            found = _find_twist_dict(item)
            if found is not None:
                return found

    return None


def _twist_from_obj(obj: Any) -> TwistOut:
    """
    정상 Twist JSON 또는 EXAONE의 대체 JSON 스키마를 TwistOut으로 변환한다.
    """
    if not isinstance(obj, dict):
        raise ValueError("JSON 객체가 아닙니다.")

    # 1) 정상 Twist JSON 또는 중첩된 Twist JSON 처리
    twist_dict = _find_twist_dict(obj)
    if twist_dict is not None:
        return _twist_from_twist_dict(twist_dict)

    # 2) EXAONE이 position_follow/target/position 같은 임의 스키마로 반환한 경우
    #    예: {"position_follow": {"target": {"position": {"linear": "forward"}}}}
    raw = json.dumps(obj, ensure_ascii=False)
    inferred = _infer_twist_from_text(raw)
    if inferred is not None:
        LOG.info("Twist 키가 없는 LLM JSON을 의미 기반으로 변환: %s", raw[:300])
        return _sanitize_twist(inferred)

    raise ValueError(f"Twist 키가 없는 JSON 객체입니다. keys={list(obj.keys())}")


def _parse_twist_json(text: str) -> TwistOut:
    """
    LLM 응답에서 Twist JSON 객체를 최대한 견고하게 추출한다.

    허용 예:
    - {"linear_x":0.15,...}
    - "{\"linear_x\":0.15,...}" 처럼 JSON 문자열로 한 번 감싼 경우
    - ```json
      {"linear_x":0.15,...}
      ```
    - 설명 문장 뒤에 JSON이 섞여 있는 경우
    - {"twist": {"linear_x":0.15,...}} 처럼 한 번 감싼 경우
    - {"position_follow": {"target": {"position": {"linear": "forward"}}}} 같은 EXAONE 대체 스키마
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError("빈 응답입니다.")

    cleaned = raw

    # 흔한 마크다운 코드펜스 제거
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    decoder = json.JSONDecoder()

    # 1) 전체 문자열을 JSON으로 해석
    # json.loads(cleaned)가 dict가 아니라 str을 반환하는 경우도 한 번 더 해석한다.
    try:
        obj = json.loads(cleaned)

        if isinstance(obj, str):
            obj = json.loads(obj.strip())

        return _twist_from_obj(obj)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    # 2) 문자열 안의 첫 번째 JSON 객체부터 순차 탐색
    for i, ch in enumerate(cleaned):
        if ch != "{":
            continue

        try:
            obj, _ = decoder.raw_decode(cleaned[i:])

            if isinstance(obj, str):
                obj = json.loads(obj.strip())

            return _twist_from_obj(obj)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

    # 3) JSON이 아예 없더라도 텍스트 의미로 마지막 보정
    inferred = _infer_twist_from_text(cleaned)
    if inferred is not None:
        LOG.info("JSON 없는 LLM 응답을 의미 기반으로 변환: %s", cleaned[:300])
        return _sanitize_twist(inferred)

    raise ValueError(f"응답에서 JSON twist 객체를 찾지 못했습니다. raw={raw[:300]!r}")

def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


async def llm_to_twist(
    instruction: str, state: dict[str, Any]
) -> tuple[TwistOut, dict[str, float]]:
    """LLM 호출(Ollama / Hugging Face 로컬·원격) + 파싱까지 시간(ms) 반환."""
    system = (
        "You are a low-level velocity controller for an underwater AUV. "
        "You MUST output exactly one JSON object and nothing else. "
        "Do not output markdown, explanation, Korean sentences, code fences, or alternative schemas. "
        "Do not use keys such as instruction, position_follow, target, position, speed, direction, or command. "
        "The JSON object MUST contain exactly these six keys: "
        "linear_x, linear_y, linear_z, angular_x, angular_y, angular_z. "
        "All values must be numbers. "
        "Safety limits: -0.5 <= linear_x <= 0.5, -0.3 <= angular_z <= 0.3. "
        "For slow forward movement, output exactly: "
        "{\"linear_x\":0.15,\"linear_y\":0.0,\"linear_z\":0.0,"
        "\"angular_x\":0.0,\"angular_y\":0.0,\"angular_z\":0.0}. "
        "Return only the JSON object."
    )
    user = json.dumps(
        {
            "instruction": instruction,
            "robot_state": state,
            "output_rule": "JSON object only. No markdown. No explanation.",
        },
        ensure_ascii=False,
    )

    if LLM_DUMMY:
        t0 = time.perf_counter()
        twist = _dummy_twist(instruction)
        ms = _elapsed_ms(t0)
        LOG.info("LLM_DUMMY: 휴리스틱 cmd_vel (%.2f ms)", ms)
        return twist, {"llm_pipeline_ms": ms}

    if LLM_PROVIDER == "huggingface":
        if not (HUGGINGFACE_MODEL or "").strip():
            raise HTTPException(
                status_code=503,
                detail="Hugging Face: HUGGINGFACE_MODEL 또는 HF_MODEL 또는 "
                "model.huggingface_model 설정이 필요합니다.",
            )
        hf_token = _env_nonempty("HF_TOKEN") or _env_nonempty("HUGGINGFACE_HUB_TOKEN")
        if _hf_requires_hub_token() and not hf_token:
            raise HTTPException(
                status_code=503,
                detail="Hugging Face 클라우드 라우터에는 HF_TOKEN 또는 "
                "HUGGINGFACE_HUB_TOKEN 이 필요합니다(비밀은 JSON에 넣지 마세요). "
                "로컬 추론 서버만 쓰려면 HF_API_BASE를 호스트의 /v1 주소로 바꾸세요.",
            )
        url = f"{HF_API_BASE}/chat/completions"
        payload: dict[str, Any] = {
            "model": HUGGINGFACE_MODEL.strip(),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": LLM_TEMPERATURE,
            "max_tokens": LLM_MAX_TOKENS,
            "stream": False,
            "stop": ["[|endofturn|]"],
        }
        headers: dict[str, str] = (
            {"Authorization": f"Bearer {hf_token}"} if hf_token else {}
        )
        log_model = HUGGINGFACE_MODEL.strip()
        backend = "Hugging Face (hub)" if _hf_requires_hub_token() else "Hugging Face (local)"
    else:
        url = f"{OLLAMA_HOST}/v1/chat/completions"
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": LLM_TEMPERATURE,
            "max_tokens": LLM_MAX_TOKENS,
            "stream": False,
        }
        headers = {"Authorization": "Bearer ollama"}
        log_model = OLLAMA_MODEL
        backend = "Ollama"

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=LLM_HTTP_TIMEOUT) as client:
            r = await client.post(url, json=payload, headers=headers)
    except httpx.ConnectError as e:
        ms = _elapsed_ms(t0)
        LOG.warning("%s 연결 실패 (%.2f ms), 더미 명령 사용: %s", backend, ms, e)
        return _dummy_twist(instruction), {"llm_pipeline_ms": ms}
    except httpx.ReadTimeout as e:
        ms = _elapsed_ms(t0)
        LOG.warning("%s 응답 시간 초과 (%.2f ms), 더미 명령 사용: %s", backend, ms, e)
        return _dummy_twist(instruction), {"llm_pipeline_ms": ms}
    except httpx.HTTPError as e:
        ms = _elapsed_ms(t0)
        LOG.warning("%s HTTP 호출 실패 (%.2f ms), 더미 명령 사용: %s", backend, ms, e)
        return _dummy_twist(instruction), {"llm_pipeline_ms": ms}

    llm_http_ms = _elapsed_ms(t0)

    if r.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"{backend} chat API 오류 ({r.status_code}): {r.text[:500]}",
        )

    t_parse = time.perf_counter()
    body = r.json()
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise HTTPException(status_code=502, detail=f"{backend} 응답 형식 오류: {body}") from e

    LOG.info("%s raw content: %r", backend, str(content)[:1000])

    try:
        twist = _parse_twist_json(content)
    except ValueError as e:
        parse_ms = _elapsed_ms(t_parse)
        total_ms = llm_http_ms + parse_ms
        LOG.warning(
            "%s 응답 파싱 실패 (http=%.2f ms, parse_try=%.2f ms), 휴리스틱 사용: %s",
            backend,
            llm_http_ms,
            parse_ms,
            e,
        )
        return _dummy_twist(instruction), {
            "llm_http_ms": llm_http_ms,
            "llm_parse_ms": parse_ms,
            "llm_pipeline_ms": total_ms,
        }

    parse_ms = _elapsed_ms(t_parse)
    total_ms = llm_http_ms + parse_ms
    LOG.info(
        "%s chat.completions model=%s http=%.2f ms parse=%.2f ms total=%.2f ms",
        backend,
        log_model,
        llm_http_ms,
        parse_ms,
        total_ms,
    )
    return twist, {
        "llm_http_ms": llm_http_ms,
        "llm_parse_ms": parse_ms,
        "llm_pipeline_ms": total_ms,
    }


@asynccontextmanager
async def _lifespan(app: FastAPI):
    start_ros_background()
    yield


app = FastAPI(
    title="LLM control (ROS 2 DDS)",
    version="0.1.0",
    lifespan=_lifespan,
)

app.include_router(
    create_umdl_router(
        {
            "provider": LLM_PROVIDER,
            "hf_api_base": HF_API_BASE,
            "hf_model": HUGGINGFACE_MODEL,
            "ollama_host": OLLAMA_HOST,
            "ollama_model": OLLAMA_MODEL,
            "temperature": LLM_TEMPERATURE,
            "max_tokens": UMDL_MAX_TOKENS,
            "timeout_seconds": LLM_HTTP_TIMEOUT,
            "dataset_root": UMDL_DATASET_ROOT,
            "schema_path": UMDL_SCHEMA_PATH,
            "generation_schema_path": UMDL_GENERATION_SCHEMA_PATH,
            "guided_json": UMDL_GUIDED_JSON,
            "guided_decoding_backend": UMDL_GUIDED_BACKEND,
            "few_shot_enabled": UMDL_FEW_SHOT,
            "family_hints_enabled": UMDL_FAMILY_HINTS,
            "max_retries": UMDL_MAX_RETRIES,
            "safety_fast_path": UMDL_SAFETY_FAST_PATH,
        }
    )
)


@app.get("/health")
async def health() -> dict[str, Any]:
    hf_tok = _env_nonempty("HF_TOKEN") or _env_nonempty("HUGGINGFACE_HUB_TOKEN")
    return {
        "ros_bridge_ready": _bridge is not None,
        "odom_topic": ODOM_TOPIC,
        "cmd_vel_topic": CMD_VEL_TOPIC,
        "rmw": os.environ.get("RMW_IMPLEMENTATION", ""),
        "ros_domain_id": os.environ.get("ROS_DOMAIN_ID", ""),
        "llm_provider": LLM_PROVIDER,
        "ollama_host": OLLAMA_HOST,
        "ollama_model": OLLAMA_MODEL,
        "huggingface_api_base": HF_API_BASE,
        "huggingface_model": HUGGINGFACE_MODEL,
        "hf_hub_token_required": _hf_requires_hub_token(),
        "hf_token_configured": bool(hf_tok),
        "llm_temperature": LLM_TEMPERATURE,
        "llm_max_tokens": LLM_MAX_TOKENS,
        "llm_http_timeout": LLM_HTTP_TIMEOUT,
        "llm_dummy": LLM_DUMMY,
        "llm_config_path": LLM_CONFIG_PATH,
        "llm_config_json_keys": sorted(_file_cfg.keys()) if _file_cfg else [],
        "umdl_dataset_root": UMDL_DATASET_ROOT,
        "umdl_schema_path": UMDL_SCHEMA_PATH,
        "umdl_max_tokens": UMDL_MAX_TOKENS,
        "umdl_few_shot": UMDL_FEW_SHOT,
        "umdl_family_hints": UMDL_FAMILY_HINTS,
        "legacy_direct_control_enabled": LEGACY_DIRECT_CONTROL_ENABLED,
    }


@app.post("/control/high_level")
async def high_level(cmd: HighLevelCommand) -> dict[str, Any]:
    if not LEGACY_DIRECT_CONTROL_ENABLED:
        raise HTTPException(
            status_code=403,
            detail=(
                "Legacy direct LLM-to-Twist control is disabled. "
                "Use /mission/plan for UMDL experiments or set LEGACY_DIRECT_CONTROL_ENABLED=1 only for isolated low-level smoke tests."
            ),
        )
    if _bridge is None:
        raise HTTPException(status_code=503, detail="ROS 브리지가 아직 준비되지 않았습니다.")
    t_req = time.perf_counter()
    state = _bridge.latest_odom_summary()
    raw_twist, llm_timing = await llm_to_twist(cmd.instruction, state)
    twist = _twist_with_zero_fallback(raw_twist, cmd.instruction)
    _bridge.publish_twist(twist)
    total_ms = _elapsed_ms(t_req)
    timing_ms: dict[str, float] = {
        "request_total_ms": round(total_ms, 3),
        **{k: round(v, 3) for k, v in llm_timing.items()},
    }
    LOG.info("/control/high_level request_total=%.2f ms", total_ms)
    return {"applied": twist.model_dump(), "state": state, "timing_ms": timing_ms}


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=LLM_CONTROL_PORT, log_level="info")


if __name__ == "__main__":
    main()