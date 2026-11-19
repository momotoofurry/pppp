#!/bin/bash
# Gazebo check of the two-mode keys control (report 35.64), WSL:  bash src/pc/sim/gz_test.sh [runs]
# Each run: fresh headless world (gen3_gazebo.launch.py, simulated grasp on), the 20-step key test (modes_keytest.py),
# then the object positions (gz_objects.py) and the grasp log. Does nothing while a keys session is running.
# Summary -> /tmp/gz_test.txt
cd "$(dirname "$0")/../../.."
RUNS=${1:-5}
OUT=/tmp/gz_test.txt
LOG=/tmp/gen3_gazebo.log
if pgrep -f 'assist_ros.py keys' > /dev/null; then echo 'a keys session is running, not testing'; exit 1; fi

stop() {
  pkill -INT -f 'gen3_gazebo[.]launch' || true
  sleep 4
  for p in $(pgrep -f 'gen3_gazebo[.]launch|robot_state_publisher.*launch_params|controller_manager/spawner|gzserver|gzclient|gz_attach[.]py|spawn_entity'); do
    kill -9 $p 2>/dev/null
  done
  sleep 1
  # killed ROS processes leave Fast DDS shared-memory locks; with them spawn_entity can wait forever. Remove them only
  # when no ROS process is left at all.
  if [ -z "$(pgrep -f '/opt/ros|ros2|rviz|assist_ros|gzserver')" ]; then rm -f /dev/shm/fastrtps_* /dev/shm/sem.fastrtps_*; fi
}

source /opt/ros/humble/setup.bash
python3 src/pc/sim/make_world.py src/pc/sim/assist_world.world > /dev/null
: > $OUT
for r in $(seq 1 $RUNS); do
  stop
  setsid bash src/pc/sim/gen3_gazebo.sh gui:=false > $LOG 2>&1 &
  for i in $(seq 1 90); do grep -q 'Configured and activated.*joint_trajectory_controller' $LOG 2>/dev/null && break; sleep 1; done
  sleep 5
  echo "=== run $r" | tee -a $OUT
  echo '== at start' | tee -a $OUT; python3 src/pc/sim/gz_objects.py | tee -a $OUT
  python3 src/pc/sim/modes_keytest.py 2>&1 | grep -E 'steps ok|timeout|max diff' | tee -a $OUT
  echo '== after the key test' | tee -a $OUT; python3 src/pc/sim/gz_objects.py | tee -a $OUT
  grep -a 'attached\|released' $LOG | sed 's/.*gz_attach\]: //' | tee -a $OUT
done
stop
