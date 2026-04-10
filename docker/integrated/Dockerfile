# syntax=docker/dockerfile:1.4
# ROS 2 Jazzy — integrated image: Stonefish + full src/ colcon (MVP, EROAS, stonefish_ros2, …).
#
# Build from repository root (stonefish submodule populated):
#   docker buildx build \
#     -f docker/integrated/Dockerfile \
#     --build-context stonefish=./stonefish \
#     -t projectalpha:jazzy-integrated \
#     --load \
#     .
#
# Run (GUI needs DISPLAY + X11):
#   docker run --rm -it --network host -e DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix \
#     projectalpha:jazzy-integrated bash
#   source /ws/install/setup.bash
#   ros2 launch eroas_navigation girona500_waypoint_test.launch.py
#
# See docker/README.md.

FROM osrf/ros:jazzy-desktop-full AS stonefish-install

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    pkg-config \
    libglm-dev \
    libsdl2-dev \
    libfreetype6-dev \
    libgl1-mesa-dev \
    libomp-dev \
    && rm -rf /var/lib/apt/lists/*

RUN for f in /usr/lib/*/cmake/SDL2/sdl2-config.cmake; do \
        if [ -f "$f" ]; then sed -i 's/-lSDL2 /-lSDL2/g' "$f"; fi; \
    done

WORKDIR /sf
COPY --from=stonefish . .

RUN cmake -S . -B build \
        -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_TESTS=OFF \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
    && cmake --build build -j"$(nproc)" \
    && cmake --install build

FROM osrf/ros:jazzy-desktop-full

ENV DEBIAN_FRONTEND=noninteractive
ENV CMAKE_PREFIX_PATH=/opt/ros/jazzy:/usr/local
ENV LD_LIBRARY_PATH=/usr/local/lib

COPY --from=stonefish-install /usr/local /usr/local

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    python3-colcon-common-extensions \
    python3-opencv \
    python3-numpy \
    python3-pip \
    python3-rosdep \
    libgsl-dev \
    libpcl-dev \
    libglm-dev \
    libsdl2-dev \
    libfreetype6-dev \
    libgl1-mesa-dev \
    libomp-dev \
    ros-jazzy-pcl-conversions \
    ros-jazzy-cv-bridge \
    ros-jazzy-image-transport \
    ros-jazzy-tf2-tools \
    ros-jazzy-visualization-msgs \
    ros-jazzy-geographic-msgs \
    ros-jazzy-action-msgs \
    ros-jazzy-robot-localization \
    xterm \
    && rm -rf /var/lib/apt/lists/*

ENV SDL_AUDIODRIVER=dummy

RUN rosdep init 2>/dev/null || true \
    && rosdep update

RUN for f in /usr/lib/*/cmake/SDL2/sdl2-config.cmake; do \
        if [ -f "$f" ]; then sed -i 's/-lSDL2 /-lSDL2/g' "$f"; fi; \
    done

WORKDIR /ws
COPY src ./src

COPY --from=stonefish Tests/Data /ws/_sf_tests_data
RUN bash -c 'set -e; shopt -s nullglob; \
    find /ws/src/stonefish_ros2/data -maxdepth 1 -type l -delete; \
    for f in /ws/_sf_tests_data/*.obj /ws/_sf_tests_data/*.stl /ws/_sf_tests_data/*.png; do \
      [ -f "$f" ] && cp --remove-destination "$f" /ws/src/stonefish_ros2/data/; \
    done; \
    cp --remove-destination /ws/_sf_tests_data/girona500auv_console.scn /ws/src/stonefish_ros2/data/'

RUN bash -lc "source /opt/ros/jazzy/setup.bash \
    && rosdep install --from-paths /ws/src --ignore-src -r -y --rosdistro jazzy \
    && colcon build \
        --cmake-args -DCMAKE_BUILD_TYPE=Release"

RUN bash -lc "grep -q 'source /ws/install/setup.bash' /root/.bashrc || echo 'source /ws/install/setup.bash' >> /root/.bashrc"

WORKDIR /ws
SHELL ["/bin/bash", "-lc"]

CMD ["bash", "-lc", "source /ws/install/setup.bash && echo 'Image: projectalpha:jazzy-integrated' && echo 'Examples:' && echo '  ros2 launch eroas_navigation girona500_waypoint_test.launch.py' && echo '  ros2 launch stonefish_ros2 girona500_mvp.launch.py' && bash"]
