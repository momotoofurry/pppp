#!/bin/bash
# Task-label chain on the simulated Gen3 in RViz (report 35.27). WSL, from the repository root:
#   bash src/pc/sim/task_label_ros.sh
# Starts gen3_sim.sh (with RViz) and ros_relay.py, puts the arm at home with the gripper open (ros_home.py), then runs
# src/pc/test_task_labels.py --ros in the rf-emg container. Docker Desktop containers cannot reach the WSL loopback,
# so tcp_fwd.py exposes the relay on the WSL address (port 50558). Log: results/logs/test_task_labels_ros.log
H=src/pc/sim
mkdir -p /tmp/rossim
( bash $H/gen3_sim.sh > /tmp/rossim/launch.log 2>&1 ) &
LP=$!
source /opt/ros/humble/setup.bash
( python3 -u $H/ros_relay.py > /tmp/rossim/relay.log 2>&1 ) &
RP=$!
for i in $(seq 1 60); do
  sleep 2
  if ss -ltn | grep -q ':50557 '; then echo "relay listening after $((i*2)) s"; break; fi
done
timeout 60 python3 $H/ros_home.py $H/poses_sim.json
IP=$(hostname -I | awk '{print $1}')
( python3 -u $H/tcp_fwd.py "$IP" 50558 50557 > /tmp/rossim/fwd.log 2>&1 ) &
FP=$!
sleep 1
docker run --rm --user 1000:1000 -e HOME=/tmp -v "$PWD":/work -v "$PWD/../model/external":/work/external -w /work rf-emg \
  python src/pc/test_task_labels.py --ros "$IP:50558" 2>&1 | tee results/logs/test_task_labels_ros.log
kill $FP $RP 2>/dev/null
pkill -f kortex_bringup; pkill -f ros2_control_node; pkill -f robot_state_publisher; pkill -f gen3.launch; pkill -f rviz2
kill $LP 2>/dev/null
