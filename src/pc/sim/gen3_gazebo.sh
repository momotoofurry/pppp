#!/bin/bash
# Gen3 + 2F-85 in Gazebo Classic with the assist scene (report 35.64). Same robotiq_description overlay as gen3_sim.sh.
#   bash src/pc/sim/gen3_gazebo.sh [gui:=false]
set -e
source /opt/ros/humble/setup.bash
OV="$HOME/.cache/kinova_sim_overlay"
[ -d "$OV" ] && export AMENT_PREFIX_PATH="$OV:$AMENT_PREFIX_PATH"
source /usr/share/gazebo/setup.sh 2>/dev/null || true
D="$(cd "$(dirname "$0")" && pwd)"
exec ros2 launch "$D/gen3_gazebo.launch.py" "$@"
