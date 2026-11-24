#!/bin/bash
# 35.92: assist_ros.py board against the Kortex driver's own launch (kortex_bringup gen3.launch.py, fake hardware):
# the controllers / topics / gripper action of the real-arm launch. Fault injection: joint_trajectory_controller
# deactivated for 3 s during the session -> the tracking hold must trigger.
#   bash src/pc/s7_test/kortex_mock.sh <outdir>
HERE=$(dirname "$(readlink -f "$0")")
cd /home/momo1234/model-leaf || exit 1
OUT=${1:-/tmp/kortex_mock}
mkdir -p $OUT
LOG=$OUT/kortex.log
stop() {
  pkill -INT -f 'assist_ros.py board' || true
  pkill -INT -f 'gen3.launch.py' || true
  sleep 3
  for p in $(pgrep -f 'gen3.launch.py|ros2_control_node|robot_state_publisher|controller_manager/spawner|rviz2'); do kill -9 $p 2>/dev/null; done
  sleep 1
  if [ -z "$(pgrep -f '/opt/ros|ros2|rviz|assist_ros|gzserver')" ]; then rm -f /dev/shm/fastrtps_* /dev/shm/sem.fastrtps_*; fi
}
source /opt/ros/humble/setup.bash
stop
setsid bash src/pc/sim/gen3_sim.sh launch_rviz:=false > $LOG 2>&1 &
for i in $(seq 1 90); do grep -q 'Configured and activated.*joint_trajectory_controller' $LOG 2>/dev/null && break; sleep 1; done
grep -q 'Configured and activated.*joint_trajectory_controller' $LOG || { echo 'KORTEX NOT READY'; tail -20 $LOG; stop; exit 1; }
sleep 3
echo '== controllers' > $OUT/checks.txt
ros2 service call /controller_manager/list_controllers controller_manager_msgs/srv/ListControllers \
  | grep -oE "name='[a-z_]+', state='[a-z]+'" >> $OUT/checks.txt 2>&1
echo '== topics / actions used by assist_ros' >> $OUT/checks.txt
ros2 topic list | grep -E '^/joint_states$|^/joint_trajectory_controller/joint_trajectory$' >> $OUT/checks.txt
ros2 action list | grep -E 'robotiq_gripper_controller/gripper_cmd' >> $OUT/checks.txt
# pre-pose: joint 7 at -166 deg (the start pose has it at +92: the long way would be 258 deg, the short way 102)
python3 - >> $OUT/checks.txt 2>&1 <<'PY'
import time, rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from builtin_interfaces.msg import Duration
rclpy.init(); n = Node('prepose'); q = {}
n.create_subscription(JointState, '/joint_states', lambda m: q.update(dict(zip(m.name, m.position))), 10)
pub = n.create_publisher(JointTrajectory, '/joint_trajectory_controller/joint_trajectory', 10)
t = time.time()
while len(q) < 7 and time.time() - t < 5: rclpy.spin_once(n, timeout_sec=0.1)
J = [f'joint_{i}' for i in range(1, 8)]
tgt = [q[j] for j in J]; tgt[6] = -2.9
m = JointTrajectory(); m.joint_names = J
m.points = [JointTrajectoryPoint(positions=tgt, velocities=[0.0] * 7, time_from_start=Duration(sec=4))]
time.sleep(0.5); pub.publish(m)
t = time.time()
while time.time() - t < 5: rclpy.spin_once(n, timeout_sec=0.1)
print('pre-pose joint_7 = %.2f rad' % q['joint_7'])
PY
python3 - > $OUT/joint7.txt 2>&1 <<'PY' &
import time, rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
rclpy.init(); n = Node('j7watch'); v = []
n.create_subscription(JointState, '/joint_states', lambda m: v.append(dict(zip(m.name, m.position))['joint_7']), 10)
t = time.time()
while time.time() - t < 40: rclpy.spin_once(n, timeout_sec=0.05)
print('joint_7 in the first 40 s: first %.2f min %.2f max %.2f last %.2f rad' % (v[0], min(v), max(v), v[-1]))
PY
python3 src/pc/sim/assist_ros.py board --limit 90 --events $OUT/board_events.csv --log $OUT/assist_board.csv \
  --labels $OUT/assist_labels.csv > $OUT/assist_stdout.txt 2>&1 &
AR=$!
sleep 2
python3 $HERE/lock_driver.py $OUT/assist_board.csv $OUT/driver.txt 75 > $OUT/driver_stdout.txt 2>&1 &
DR=$!
sleep 30
echo "== fault: controller off at $(date +%T)" >> $OUT/checks.txt
ros2 service call /controller_manager/switch_controller controller_manager_msgs/srv/SwitchController "{deactivate_controllers: [joint_trajectory_controller], strictness: 1}" | grep -o "ok=[A-Za-z]*" >> $OUT/checks.txt 2>&1
sleep 3
ros2 service call /controller_manager/switch_controller controller_manager_msgs/srv/SwitchController "{activate_controllers: [joint_trajectory_controller], strictness: 1}" | grep -o "ok=[A-Za-z]*" >> $OUT/checks.txt 2>&1
echo "== controller back at $(date +%T)" >> $OUT/checks.txt
wait $DR
sleep 1
kill -INT $AR 2>/dev/null
sleep 3
stop
echo KORTEX_MOCK_DONE
