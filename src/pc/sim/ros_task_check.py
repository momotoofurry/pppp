"""Replay the robot actions of one simulated session (results/task_sim_trace.csv, src/task_sim.py) on the simulated
Kinova Gen3 (src/pc/sim/gen3_sim.sh: ros2_kortex with mock hardware) through ros_relay.py, one action at a time,
and compare the measured duration of every action with the duration the task simulation assumed (report 35.17).
Standard library only; talks TCP to the relay as kinova_bridge.py does.
Usage (WSL, after gen3_sim.sh and ros_relay.py are up):
  python3 src/pc/sim/ros_task_check.py results/task_sim_trace.csv results/task_sim_ros.csv [--port 50557]
"""
import argparse
import csv
import json
import os
import socket
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SPEED = 20.0                       # deg/s, as task_sim.py
GRIP = {'grip': 0.8, 'release': 0.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('trace')
    ap.add_argument('out')
    ap.add_argument('--port', type=int, default=50557)
    args = ap.parse_args()
    poses = json.load(open(os.path.join(HERE, 'poses_sim.json')))
    rows = list(csv.DictReader(open(args.trace)))
    s = socket.create_connection(('127.0.0.1', args.port), timeout=10)
    f = s.makefile('r', encoding='utf-8')

    def act(i, msg):
        t0 = time.time()
        s.sendall((json.dumps(dict(id=i, **msg)) + '\n').encode())
        s.settimeout(30)
        while True:
            r = json.loads(f.readline())
            if r.get('id') == i:
                return r['event'], r.get('note', ''), time.time() - t0

    # start from home, as the simulation
    print('to home:', act(0, dict(kind='joints', target=poses['home'], speed=SPEED)))
    print('gripper open:', act(1, dict(kind='gripper', target=0.0)))
    out = []
    for i, r in enumerate(rows, start=2):
        c = r['command']
        msg = dict(kind='gripper', target=GRIP[c]) if c in GRIP else dict(kind='joints', target=poses[c], speed=SPEED)
        ev, note, dt = act(i, msg)
        out.append(dict(step=i - 2, command=c, intended=r['intended'], sim_dur_s=float(r['dur_s']), ros_dur_s=round(dt, 3),
                        event=ev, note=note))
        print(out[-1])
    with open(args.out, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    ok = sum(o['event'] == 'end' for o in out)
    arm = [o for o in out if o['command'] not in GRIP]
    print(f'{ok} of {len(out)} actions ended normally; arm moves: largest |ros - sim| = '
          f"{max(abs(o['ros_dur_s'] - o['sim_dur_s']) for o in arm):.2f} s; "
          f"gripper: ros mean {sum(o['ros_dur_s'] for o in out if o['command'] in GRIP) / max(1, len(out) - len(arm)):.2f} s (sim assumes 1.0 s)")


if __name__ == '__main__':
    main()
