#!/bin/bash
# Simulated Kinova Gen3 (7 DoF) + Robotiq 2F-85 in RViz, ros2_control mock hardware (no robot), ROS 2 Humble on WSL.
#   one-time: sudo apt install ros-humble-kortex-bringup ros-humble-kortex-description ros-humble-kortex-driver \
#             ros-humble-kinova-gen3-7dof-robotiq-2f-85-moveit-config ros-humble-ros2-controllers \
#             ros-humble-controller-manager ros-humble-robotiq-description
#   run:      bash src/pc/sim/gen3_sim.sh            (then: kinova_bridge.py run --ros)
# Fix for the apt versions (kortex 0.2.3 + robotiq_description 0.0.1): kortex passes isaac_joint_commands /
# isaac_joint_states to the Robotiq macro, which does not declare them, so xacro fails. A private overlay copy of
# robotiq_description (in ~/.cache/kinova_sim_overlay, nothing under /opt is changed) declares the two parameters
# (unused, defaults only). Found ahead of /opt/ros through AMENT_PREFIX_PATH.
set -e
source /opt/ros/humble/setup.bash
OV="$HOME/.cache/kinova_sim_overlay"
SRC=/opt/ros/humble/share/robotiq_description
MAC="$OV/share/robotiq_description/urdf/robotiq_2f_85_macro.urdf.xacro"
if ! grep -q isaac_joint_commands "$SRC/urdf/robotiq_2f_85_macro.urdf.xacro" && [ ! -f "$MAC" ]; then
  mkdir -p "$OV/share" "$OV/share/ament_index/resource_index/packages"
  cp -r "$SRC" "$OV/share/"
  touch "$OV/share/ament_index/resource_index/packages/robotiq_description"
  sed -i 's|        sim_isaac:=false|        sim_isaac:=false\n        isaac_joint_commands:=/isaac_joint_commands\n        isaac_joint_states:=/isaac_joint_states|' "$MAC"
  echo "overlay made: $OV"
fi
[ -f "$MAC" ] && export AMENT_PREFIX_PATH="$OV:$AMENT_PREFIX_PATH"
exec ros2 launch kortex_bringup gen3.launch.py robot_ip:=yyy.yyy.yyy.yyy use_fake_hardware:=true \
  gripper:=robotiq_2f_85 dof:=7 launch_rviz:=true "$@"
