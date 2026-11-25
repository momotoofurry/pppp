#!/bin/bash
# report 35.101: Gazebo rehearsal of a real-arm session: kinova_trials.py (logger, --auto) + assist_ros.py board
# --scene <scene> --trial-port + trial_driver.py (scripted user). Usage: bash src/pc/s7_test/gz_trials.sh <scene> <n> <outdir>
SP=$(dirname "$(readlink -f "$0")")
cd /home/momo1234/model-leaf || exit 1
SCENE=$1
N=$2
OUT=$3
mkdir -p $OUT
LOG=$OUT/gen3_gazebo.log
if [ "$SCENE" = "crowded" ]; then export ASSIST_N_OBJ=6; else export ASSIST_N_OBJ=3; fi
stop() {
  pkill -INT -f 'assist_ros.py board' || true
  pkill -f 'trial_driver.py' || true
  pkill -INT -f 'gen3_gazebo[.]launch' || true
  sleep 4
  for p in $(pgrep -f 'gen3_gazebo[.]launch|robot_state_publisher.*launch_params|controller_manager/spawner|gzserver|gzclient|gz_attach[.]py|spawn_entity'); do
    kill -9 $p 2>/dev/null
  done
  sleep 1
  if [ -z "$(pgrep -f '/opt/ros|ros2|rviz|assist_ros|gzserver')" ]; then rm -f /dev/shm/fastrtps_* /dev/shm/sem.fastrtps_*; fi
}
source /opt/ros/humble/setup.bash
python3 src/pc/sim/make_world.py src/pc/sim/assist_world.world $SCENE
stop
setsid bash src/pc/sim/gen3_gazebo.sh gui:=false > $LOG 2>&1 &
for i in $(seq 1 120); do grep -q 'Configured and activated.*joint_trajectory_controller' $LOG 2>/dev/null && break; sleep 1; done
grep -q 'Configured and activated.*joint_trajectory_controller' $LOG || { echo 'GAZEBO NOT READY'; stop; exit 1; }
sleep 5
echo '== objects at start' > $OUT/objects.txt; python3 src/pc/sim/gz_objects.py >> $OUT/objects.txt
python3 src/pc/sim/kinova_trials.py make --scene $SCENE --n $N --practice 0 --seed 901 --out $OUT/trials.csv
python3 src/pc/sim/assist_ros.py board --scene $SCENE --limit 1500 --lock-rule intent --send-labels 0 --trial-port 50570 \
  --task-events $OUT/task_events.csv --events $OUT/board_events.csv --log $OUT/assist_board.csv --labels $OUT/assist_labels.csv \
  > $OUT/assist_stdout.txt 2>&1 &
AR=$!
sleep 2
python3 $SP/trial_driver.py $OUT/assist_board.csv $OUT/task_events.csv $OUT/trials.csv $SCENE $OUT/driver.txt 1400 \
  > $OUT/driver_stdout.txt 2>&1 &
DR=$!
sleep 25                                   # the start move (about 20 s)
python3 src/pc/sim/kinova_trials.py run --auto --scene $SCENE --list $OUT/trials.csv --events $OUT/task_events.csv \
  --out $OUT/trials_result.csv --limit 120 > $OUT/logger_stdout.txt 2>&1
sleep 2
echo '== objects after' >> $OUT/objects.txt; python3 src/pc/sim/gz_objects.py >> $OUT/objects.txt
grep -a 'attached\|released' $LOG | sed 's/.*gz_attach\]: //' >> $OUT/objects.txt
kill $DR 2>/dev/null
kill -INT $AR 2>/dev/null
sleep 3
stop
echo GZ_TRIALS_DONE
