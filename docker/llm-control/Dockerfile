# LLM HTTP 제어 + ROS 2 Jazzy (DDS로 Stonefish/다른 컨테이너와 통신)
# 빌드: docker build -f docker/llm-control/Dockerfile -t projectalpha:llm-control docker/llm-control

FROM ros:jazzy-ros-base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    ros-jazzy-rmw-fastrtps-cpp \
    ros-jazzy-rclpy \
    ros-jazzy-geometry-msgs \
    ros-jazzy-nav-msgs \
    ros-jazzy-std-msgs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY app ./app

EXPOSE 8080

CMD ["/bin/bash", "-lc", "source /opt/ros/jazzy/setup.bash && exec python3 -m app.main"]
