#!/bin/bash
# report 35.90 (2026-11-25). Usage: bash src/pc/s7_test/gz_lock.sh none|room|intent <outdir>
# 35.89: Gazebo rehearsal of the shelf lock rule. bash gz_lock.sh <rule> <outdir>
SP=$(dirname "$(readlink -f "$0")")   # lock_driver.py lives next to this script
cd /home/momo1234/model-leaf || exit 1
RULE=$1
OUT=$2
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
python3 src/pc/sim/assist_ros.py board --limit 200 --lock-rule $RULE --send-labels 0 --events $OUT/board_events.csv \
  --log $OUT/assist_board.csv --labels $OUT/assist_labels.csv > $OUT/assist_stdout.txt 2>&1 &
AR=$!
sleep 2
python3 $SP/lock_driver.py $OUT/assist_board.csv $OUT/driver.txt 170 > $OUT/driver_stdout.txt 2>&1
sleep 2
echo '== objects after' >> $OUT/objects.txt; python3 src/pc/sim/gz_objects.py >> $OUT/objects.txt
grep -a 'attached\|released' $LOG | sed 's/.*gz_attach\]: //' >> $OUT/objects.txt
kill -INT $AR 2>/dev/null
stop
echo GZ_LOCK_DONE
