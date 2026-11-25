"""35.101 Gazebo rehearsal of the real-arm trials: a scripted user in place of udp_tcp_relay.py (as lock_driver.py).
Waits for assist_ros.py's 'reset_done,<trial>' (sent when kinova_trials.py starts a trial), looks the target up in the
trial list, then: to the object, W in, relax (grasp), S out, carry to the target shelf, stop (lock), W in, relax (put
down), S out. A wrongly locked object / shelf is backed out of with S. Board lines: command events + 100 ms heartbeats.
  python3 trial_driver.py <assist log csv> <task events csv> <trial list csv> <scene> <out txt> [limit s]"""
import csv
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'assist'))
import scenes as SC  # noqa: E402

LOG, EVF, LIST, SCENE, OUT = sys.argv[1:6]
LIMIT = float(sys.argv[6]) if len(sys.argv) > 6 else 900
GEST = {'up': 'WristExt', 'down': 'WristFlex', 'left': 'RadialDev', 'right': 'UlnarDev', 'rest': 'Rest'}
OBJ, SHELVES = SC.load(SCENE)
AIM = SC.OBJ_H / 2 + 0.04                       # modes.SHELF_AIM: carry height above a shelf top
with open(LIST, encoding='utf-8') as f:
    PLAN = {r['trial']: (int(r['obj']), int(r['shelf'])) for r in csv.DictReader(f)}

c = None
for _ in range(100):
    try:
        c = socket.create_connection(('127.0.0.1', 50560))
        break
    except OSError:
        time.sleep(1)
if c is None:
    sys.exit('no assist_ros')
c.setblocking(False)
w, cur, n_err, n_stuck = 1000, None, 0, 0
REPRESS = [False]
out = open(OUT, 'w', encoding='utf-8')


def say(*a):
    m = ' '.join(str(x) for x in a)
    print(m, flush=True)
    out.write(m + '\n')
    out.flush()


def send(cmd):
    global w, cur, n_err
    w += 1
    g = GEST[cmd]
    if cmd != cur or REPRESS[0]:
        line = f'1,1,command,{w},0,{g},{"none" if cmd == "rest" else cmd},,1,,,'
        cur = cmd
        REPRESS[0] = False
    else:
        line = f'1,1,pred,{w},0,{g},,1,0,0,'
    try:
        c.sendall((line + '\n').encode())
    except OSError as e:
        n_err += 1
        say(f'  driver send error {e}')
    try:
        c.recv(65536)
    except (BlockingIOError, OSError):
        pass


class Row:
    pass


def last():
    try:
        lines = open(LOG, encoding='utf-8').read().splitlines()
    except OSError:
        return None
    if len(lines) < 2 or not lines[-1].count(',') == lines[0].count(','):
        return None
    r = Row()
    for k, v in zip(lines[0].split(','), lines[-1].split(',')):
        setattr(r, k, float(v) if k in ('x', 'y', 'z') else v)
    return r


ev_pos = 0


def new_trial():
    """-> the id of the latest reset_done since the last call, else None"""
    global ev_pos
    tid = None
    try:
        with open(EVF, encoding='utf-8') as f:
            f.seek(ev_pos)
            for line in f:
                if not line.endswith('\n'):
                    break
                ev_pos += len(line.encode('utf-8'))
                p = line.split(',')
                if len(p) > 3 and p[2] == 'reset_done':
                    tid = p[3]
    except OSError:
        pass
    return tid


def axis(dy, dz, tol=0.012):
    if abs(dy) < tol and abs(dz) < tol:
        return 'rest'
    if abs(dy) >= abs(dz):
        return 'left' if dy > 0 else 'right'
    return 'up' if dz > 0 else 'down'


phase, rest_until, t0, tgt = 'wait', 0.0, time.monotonic(), None
prev_state, last_pos, still = None, None, 0
while time.monotonic() - t0 < LIMIT:
    tick = time.monotonic()
    tid = new_trial()
    if tid is not None and tid in PLAN:
        # the helper's job: check where the last object really is, put every object back (gz_scene.py)
        args = [sys.executable, os.path.join(HERE, 'gz_scene.py'), SCENE] + ([str(tgt[0]), str(tgt[1])] if tgt else [])
        res = subprocess.run(args, capture_output=True, text=True, timeout=60)
        for line in res.stdout.splitlines():
            say(f'{time.monotonic() - t0:6.1f} s  {line}')
        tgt = PLAN[tid]
        phase, rest_until = 'to_obj', tick + 1.0
        say(f'{tick - t0:6.1f} s  trial {tid}: object {tgt[0]} -> shelf {tgt[1]}')
    r = last()
    if r is None or tgt is None:
        send('rest')
        time.sleep(0.1)
        continue
    o, s = OBJ[tgt[0]], SHELVES[tgt[1]]
    st, x, y, z = r.state, r.x, r.y, r.z
    if st != prev_state:
        say(f'{tick - t0:6.1f} s  {st:12s} goal {r.goal} shelf {r.shelf}  x=({x:.3f},{y:.3f},{z:.3f})  phase {phase}')
        prev_state = st
    if phase == 'wait' or tick < rest_until:
        cmd = 'rest'
    elif phase == 'to_obj':
        if st == 'mode2-pick':
            if r.goal == str(tgt[0]):
                phase, cmd = 'grasp', 'up'
            else:
                cmd = 'down'                                # wrong object locked: back out
        else:
            cmd = axis(o[1] - y, o[2] - z)
            if cmd == 'rest':
                rest_until = tick + 1.5                     # stop in front of it (locks)
    elif phase == 'grasp':
        if st == 'mode2-out':
            phase, cmd = 'out', 'down'
        elif ((x - o[0]) ** 2 + (y - o[1]) ** 2 + (z - o[2]) ** 2) ** 0.5 < 0.012:
            cmd = 'rest'
        else:
            cmd = 'up'
    elif phase == 'out':
        if st == 'mode1':
            phase, cmd, rest_until = 'carry', 'rest', tick + 0.6
        else:
            cmd = 'down'
    elif phase == 'carry':
        if st == 'mode2-place':
            if r.shelf == str(tgt[1]):
                phase, cmd = 'in', 'up'
            else:
                cmd = 'down'                                # wrong shelf: back out
        else:
            cmd = axis(s[1] - y, s[2] + AIM - z)
            if cmd == 'rest':
                rest_until = tick + 1.5
    elif phase == 'in':
        if st == 'mode2-out':
            phase, cmd = 'out2', 'down'
            say(f'{tick - t0:6.1f} s  put down')
        else:
            cmd = 'up' if x < s[0] else 'rest'
    elif phase == 'out2':
        if st == 'mode1':
            phase, cmd = 'wait', 'rest'
        else:
            cmd = 'down'
    pos = (round(x, 3), round(y, 3), round(z, 3))
    still = still + 1 if (cmd != 'rest' and cmd == cur and pos == last_pos) else 0
    last_pos = pos
    if still >= 8:                                          # a held direction and nothing moves: relax, again
        still, rest_until, n_stuck = 0, tick + 0.3, n_stuck + 1
        say(f'{tick - t0:6.1f} s  no motion on {cmd}: relax 0.3 s, then the gesture again')
        cmd = 'rest'
    send(cmd)
    time.sleep(max(0.0, 0.1 - (time.monotonic() - tick)))
say(f'DRIVER END stuck {n_stuck} send errors {n_err}')
c.close()
