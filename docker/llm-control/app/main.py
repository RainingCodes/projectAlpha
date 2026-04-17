"""
HTTP LLM 제어 서버 + ROS 2 DDS 브리지.

Stonefish가 돌아가는 다른 컨테이너와 동일 ROS_DOMAIN_ID·RMW(CycloneDDS)·
CYCLONEDDS_URI(피어 디스커버리)로 /GIRONA500/dynamics 구독, /GIRONA500/cmd_vel 발행.
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
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

LOG = logging.getLogger("llm_control")
logging.basicConfig(level=logging.INFO)

ODOM_TOPIC = os.environ.get("ODOM_TOPIC", "/GIRONA500/dynamics")
CMD_VEL_TOPIC = os.environ.get("CMD_VEL_TOPIC", "/GIRONA500/cmd_vel")
# Ollama OpenAI 호환 API: http://호스트:11434/v1/chat/completions
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://ollama:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "medgemma:4b")
# LLM_DUMMY=1 이면 Ollama를 호출하지 않고 휴리스틱만 사용
LLM_DUMMY = os.environ.get("LLM_DUMMY", "").strip().lower() in ("1", "true", "yes", "on")


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


def _parse_twist_json(text: str) -> TwistOut:
    text = text.strip()
    try:
        return TwistOut(**json.loads(text))
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return TwistOut(**json.loads(text[start : end + 1]))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    raise ValueError("응답에서 JSON twist 객체를 찾지 못했습니다.")


async def llm_to_twist(instruction: str, state: dict[str, Any]) -> TwistOut:
    system = (
        "당신은 수중 AUV의 저수준 속도 명령을 내는 조종 보조입니다. "
        "반드시 JSON 한 개만 출력하세요. 키: "
        "linear_x, linear_y, linear_z, angular_x, angular_y, angular_z (실수, m/s 및 rad/s 스케일). "
        "안전을 위해 |linear_x|<=0.5, |angular_z|<=0.3 을 넘기지 마세요."
    )
    user = json.dumps({"instruction": instruction, "robot_state": state}, ensure_ascii=False)

    if LLM_DUMMY:
        LOG.info("LLM_DUMMY 활성화: 휴리스틱 cmd_vel")
        return _dummy_twist(instruction)

    url = f"{OLLAMA_HOST}/v1/chat/completions"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
    }
    # Ollama OpenAI 호환 엔드포인트는 Bearer 값이 있으면 됨(로컬 검증용)
    headers = {"Authorization": "Bearer ollama"}
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, json=payload, headers=headers)
    except httpx.ConnectError as e:
        LOG.warning("Ollama 연결 실패, 더미 명령 사용: %s", e)
        return _dummy_twist(instruction)
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Ollama API 오류: {r.text[:500]}")
    body = r.json()
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise HTTPException(status_code=502, detail=f"Ollama 응답 형식 오류: {body}") from e
    try:
        return _parse_twist_json(content)
    except ValueError as e:
        LOG.warning("Ollama 응답 파싱 실패, 휴리스틱 사용: %s", e)
        return _dummy_twist(instruction)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    start_ros_background()
    yield


app = FastAPI(
    title="LLM control (ROS 2 DDS)",
    version="0.1.0",
    lifespan=_lifespan,
)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ros_bridge_ready": _bridge is not None,
        "odom_topic": ODOM_TOPIC,
        "cmd_vel_topic": CMD_VEL_TOPIC,
        "rmw": os.environ.get("RMW_IMPLEMENTATION", ""),
        "ros_domain_id": os.environ.get("ROS_DOMAIN_ID", ""),
        "ollama_host": OLLAMA_HOST,
        "ollama_model": OLLAMA_MODEL,
        "llm_dummy": LLM_DUMMY,
    }


@app.post("/control/high_level")
async def high_level(cmd: HighLevelCommand) -> dict[str, Any]:
    if _bridge is None:
        raise HTTPException(status_code=503, detail="ROS 브리지가 아직 준비되지 않았습니다.")
    state = _bridge.latest_odom_summary()
    twist = _twist_with_zero_fallback(await llm_to_twist(cmd.instruction, state), cmd.instruction)
    _bridge.publish_twist(twist)
    return {"applied": twist.model_dump(), "state": state}


def main() -> None:
    import uvicorn

    port = int(os.environ.get("LLM_CONTROL_PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
