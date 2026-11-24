#!/bin/bash
# report 35.82 (2026-11-24): the WSL side of rehearsal.ps1
# Rehearsal (report 35.82), WSL side: headless Gazebo (Gen3 + 2F-85, assist scene, simulated grasp) and
# assist_ros.py board listening for the board's commands (udp_tcp_relay.py on Windows). Waits for the session to end.
#   bash gz_board.sh <seconds> <outdir>
cd /home/momo1234/model-leaf || exit 1
LIM=${1:-330}
OUT=${2:-/tmp/gz_board}
mkdir -p $OUT
LOG=$OUT/gen3_gazebo.log
stop() {
  pkill -INT -f 'assist_ros.py board' || true
  pkill -INT -f 'gen3_gazebo[.]launch' || true
  sleep 4
  for p in $(pgrep -f 'gen3_gazebo[.]launch|robot_state_publisher.*launch_params|controller_manager/spawner|gzserver|gzclient|gz_attach[.]py|spawn_entity'); do
    kill -9 $p 2>/dev/null
  done
  sleep 1
  if [ -z "$(pgrep -f '/opt/ros|ros2|rviz|assist_ros|gzserver')" ]; then rm -f /dev/shm/fastrtps_* /dev/shm/sem.fastrtps_*; fi
}
source /opt/ros/humble/setup.bash
python3 src/pc/sim/make_world.py src/pc/sim/assist_world.world > /dev/null
stop
setsid bash src/pc/sim/gen3_gazebo.sh gui:=false > $LOG 2>&1 &
for i in $(seq 1 120); do grep -q 'Configured and activated.*joint_trajectory_controller' $LOG 2>/dev/null && break; sleep 1; done
grep -q 'Configured and activated.*joint_trajectory_controller' $LOG || { echo 'GAZEBO NOT READY'; stop; exit 1; }
sleep 5
echo '== objects at start' > $OUT/objects.txt; python3 src/pc/sim/gz_objects.py >> $OUT/objects.txt
python3 src/pc/sim/assist_ros.py board --limit $LIM --events $OUT/board_events.csv --log $OUT/assist_board.csv \
  --labels $OUT/assist_labels.csv > $OUT/assist_stdout.txt 2>&1
echo '== objects after' >> $OUT/objects.txt; python3 src/pc/sim/gz_objects.py >> $OUT/objects.txt
grep -a 'attached\|released' $LOG | sed 's/.*gz_attach\]: //' >> $OUT/objects.txt
stop
echo GZ_BOARD_DONE
