#!/usr/bin/env bash
# girona500_mvp_sim_only + LLM용 cmd_vel → 추력 변환 (mvp_sim_only 런치에는 후자가 없음)
# -u(nounset) 금지: /ws/install/setup.bash 가 COLCON_TRACE 등 미설정 변수를 쓰면 즉시 종료됨
set -eo pipefail
mkdir -p /tmp/xdg-stonefish
chmod 700 /tmp/xdg-stonefish
source /ws/install/setup.bash

# 스케일은 노드 기본값(surge/sway/heave 30, yaw 20) 사용 — surge_scale=1.0 이면
# cmd_vel 0.05 가 추력 0.05 로만 가서 시뮬에서 거의 안 움직일 수 있음.
ros2 run eroas_navigation cmd_vel_to_thrusters --ros-args \
  -p namespace:=GIRONA500 &

exec ros2 launch stonefish_ros2 girona500_mvp_sim_only.launch.py
