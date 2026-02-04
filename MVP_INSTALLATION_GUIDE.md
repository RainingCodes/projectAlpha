# MVP (Marine Vehicle Packages) Installation Guide for Girona500

This guide explains how to install and configure MVP control system for the Girona500 AUV in ROS2 Jazzy.

## Overview

MVP는 URI Ocean Robotics에서 개발한 오픈소스 AUV 제어 프레임워크입니다. 이 가이드는 Girona500 AUV에 MVP를 적용하는 방법을 설명합니다.

## 1. Prerequisites

### System Dependencies

```bash
# MVP 핵심 의존성
sudo apt-get update
sudo apt-get install -y libgsl-dev libyaml-cpp-dev

# ROS2 Jazzy 추가 패키지
sudo apt-get install -y \
  ros-jazzy-geographic-msgs \
  ros-jazzy-robot-localization
```

## 2. MVP Packages (Already Cloned)

다음 패키지들이 이미 `/home/foc/projectAlpha/src`에 클론되어 있습니다:

- `mvp_msgs` - MVP 메시지 정의
- `mvp_control` - 제어 시스템 (PID, thruster allocation)
- `mvp_mission` - 미션 관리 (behaviors, finite state machine)

## 3. Build MVP Packages

```bash
cd /home/foc/projectAlpha

# Source ROS2 environment
source /opt/ros/jazzy/setup.bash

# Build MVP packages in dependency order
colcon build --packages-select mvp_msgs
colcon build --packages-select mvp_control
colcon build --packages-select mvp_mission

# Or build all at once
colcon build --packages-up-to mvp_mission
```

## 4. Configuration Files Created

다음 설정 파일들이 생성되었습니다:

### Control Configuration
- **File**: `src/stonefish_ros2/config/girona500_mvp_control.yaml`
- **Purpose**: PID 게인 및 제어 모드 설정
- **Modes**: idle, teleop, flight, hold_dof

### Mission Configuration
- **File**: `src/stonefish_ros2/config/girona500_mvp_mission.yaml`
- **Purpose**: MVP Helm 기본 설정 (프레임 이름, 주파수)

### Helm FSM Configuration
- **File**: `src/stonefish_ros2/config/girona500_helm.yaml`
- **Purpose**: 유한 상태 기계 및 behavior 설정
- **States**: start, kill, teleop, survey
- **Behaviors**: teleoperation, depth tracking, path following

## 5. Launch File

**File**: `src/stonefish_ros2/launch/girona500_mvp.launch.py`

이 launch 파일은 다음을 실행합니다:
- Stonefish simulator
- MVP Control node (PID controller + thruster allocation)
- MVP Helm node (mission controller)
- Teleoperation node (keyboard control)
- Sensor monitor node

## 6. Running the System

```bash
cd /home/foc/projectAlpha
source install/setup.bash

# Launch Girona500 with MVP control
ros2 launch stonefish_ros2 girona500_mvp.launch.py
```

## 7. Girona500 Thruster Configuration

Girona500은 5개의 thruster를 가지고 있습니다:

1. **ThrusterSurgePort** - 좌측 전진 thruster (xyz: -0.3297, -0.2587, -0.021)
2. **ThrusterSurgeStarboard** - 우측 전진 thruster (xyz: -0.3297, 0.2587, -0.021)
3. **ThrusterHeaveBow** - 선수 수직 thruster (xyz: 0.5347, 0.0, -0.3137)
4. **ThrusterHeaveStern** - 선미 수직 thruster (xyz: -0.5827, 0.0, -0.3137)
5. **ThrusterSway** - 횡방향 thruster (xyz: -0.0627, 0.0307, -0.021)

MVP control은 이 thruster 구성을 자동으로 분석하여 최적의 thruster allocation matrix를 생성합니다.

## 8. Control Modes

### Idle Mode
- 모든 thruster 정지
- 안전 모드

### Teleop Mode
- 키보드를 통한 수동 제어
- surge, sway, yaw_rate, pitch_rate 제어

### Flight Mode
- 웨이포인트 추종
- surge, sway, depth, pitch, yaw 제어

### Hold DOF Mode
- 위치 유지 (station keeping)
- 모든 DOF 제어

## 9. Topic Remapping

MVP는 다음 토픽을 사용합니다:

**MVP Control Input:**
- `/GIRONA500/odometry/filtered` → `/GIRONA500/dynamics` (Stonefish odometry)

**MVP Control Output:**
- `/GIRONA500/mvp_control/thruster_command` → `/GIRONA500/thruster_setpoints`

**MVP Helm Input:**
- `/GIRONA500/odometry/filtered` → `/GIRONA500/dynamics`

**MVP Helm Output:**
- `/GIRONA500/helm/desired_pose` → MVP Control

## 10. Behavior System

MVP는 plugin 기반의 behavior 시스템을 사용합니다:

### Available Behaviors
1. **Teleoperation** - 원격 조종
2. **DepthTracking** - 특정 깊이 유지
3. **PathFollowing** - 경로 추종
4. **Surfacing** - 주기적 상승
5. **AltitudeTracking** - 고도 유지

각 behavior는 FSM state에 할당되며, priority에 따라 실행됩니다.

## 11. Tuning PID Gains

PID 게인은 `girona500_mvp_control.yaml`에서 조정할 수 있습니다:

```yaml
control_modes:
  flight:
    z:     {p: 20.0,  i: 2.0,  d: 5.0,  i_max: 30, i_min: -30}
    surge: {p: 50.0,  i: 10.0, d: 0.0,  i_max: 30, i_min: -30}
    # ... 등등
```

## 12. Troubleshooting

### Build Errors
- `geographic_msgs not found`: `sudo apt-get install ros-jazzy-geographic-msgs`
- `libgsl not found`: `sudo apt-get install libgsl-dev`
- `yaml-cpp not found`: `sudo apt-get install libyaml-cpp-dev`

### Runtime Errors
- **Thruster commands not working**: 토픽 remapping 확인
- **Control unstable**: PID 게인 조정 필요
- **State transition failed**: helm.yaml에서 FSM transitions 확인

## 13. Next Steps

1. 의존성 설치: `sudo apt-get install ros-jazzy-geographic-msgs libgsl-dev libyaml-cpp-dev`
2. 빌드: `colcon build --packages-up-to mvp_mission`
3. 실행: `ros2 launch stonefish_ros2 girona500_mvp.launch.py`
4. PID 튜닝 및 테스트

## References

- MVP GitHub: https://github.com/uri-ocean-robotics
- MVP Paper: OCEANS 2022 - "Working toward the development of a generic marine vehicle framework"
- Stonefish Simulator: https://github.com/patrykcieslak/stonefish