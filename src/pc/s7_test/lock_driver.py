"""35.89 Gazebo rehearsal: a scripted closed-loop user in place of udp_tcp_relay.py. Reads the tool position and mode
from assist_ros.py's log, sends board lines (command events + 100 ms heartbeats) over TCP.
Task: pick object 0 (y +0.25, low), carry it to the empty lower shelf 3 (y -0.25) along the lower row, with a 0.4 s
hesitation in front of shelf 2 (y 0, holds object 2) on the way. A wrongly locked shelf is backed out of with S.
  python3 lock_driver.py <assist log csv> <out txt> [limit s]"""
import socket
import sys
import time


LOG, OUT = sys.argv[1], sys.argv[2]
LIMIT = float(sys.argv[3]) if len(sys.argv) > 3 else 150
GEST = {'up': 'WristExt', 'down': 'WristFlex', 'left': 'RadialDev', 'right': 'UlnarDev', 'rest': 'Rest'}
OBJ0 = (0.75, 0.25, 0.10)
TARGET_SHELF, TARGET_Y, PASS_Y = 3, -0.25, 0.0

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
w = 1000
cur = None
t_send, n_err = None, 0
REPRESS = [False]           # a stop seen while a direction is held: send the gesture again (as a user would)
out = open(OUT, 'w', encoding='utf-8')


def say(*a):
    m = ' '.join(str(x) for x in a)
    print(m, flush=True)
    out.write(m + '\n')
    out.flush()


def send(cmd):
    global w, cur, t_send, n_err
    w += 1
    g = GEST[cmd]
    now = time.time()
    if t_send is not None and now - t_send > 0.3:
        say(f'  driver send gap {now - t_send:.2f} s (window {w})')
    t_send = now
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
        c.recv(65536)                                   # drain acks / labels
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


def axis(dy, dz, tol=0.012):
    if abs(dy) < tol and abs(dz) < tol:
        return 'rest'
    if abs(dy) >= abs(dz):
        return 'left' if dy > 0 else 'right'
    return 'up' if dz > 0 else 'down'


phase, rest_until, paused, t0 = 'to_obj', 0.0, False, time.time()
wrong, locks, prev_state = 0, [], None
still, last_pos = 0, None
while time.time() - t0 < LIMIT:
    tick = time.time()
    r = last()
    if r is None:
        send('rest'); time.sleep(0.1); continue
    st, x, y, z, sh = r.state, r.x, r.y, r.z, r.shelf
    if st != prev_state:
        say(f'{tick - t0:6.1f} s  {st:12s} shelf {sh}  x=({x:.3f},{y:.3f},{z:.3f})  phase {phase}')
        if st == 'mode2-place':
            locks.append(str(sh))
            if str(sh) != str(TARGET_SHELF):
                wrong += 1
        prev_state = st
    if tick < rest_until:
        cmd = 'rest'
    elif phase == 'to_obj':
        if st == 'mode2-pick':
            phase = 'grasp'; cmd = 'up'
        else:
            cmd = axis(OBJ0[1] - y, OBJ0[2] - z)
    elif phase == 'grasp':
        if st == 'mode2-out':
            phase = 'out'; cmd = 'down'
        elif ((x - OBJ0[0]) ** 2 + (y - OBJ0[1]) ** 2 + (z - OBJ0[2]) ** 2) ** 0.5 < 0.012:
            cmd = 'rest'
        else:
            cmd = 'up'
    elif phase == 'out':
        if st == 'mode1':
            phase = 'carry'; cmd = 'rest'; rest_until = tick + 0.6
        else:
            cmd = 'down'
    elif phase == 'carry':
        if st == 'mode2-place':
            if str(sh) == str(TARGET_SHELF):
                phase = 'in'; cmd = 'up'
            else:
                cmd = 'down'                                # wrong shelf: back out
        elif not paused and y <= PASS_Y + 0.004:
            paused = True; rest_until = tick + 0.4; cmd = 'rest'
            say(f'{tick - t0:6.1f} s  hesitate 0.4 s in front of shelf 2 (y {y:.3f})')
        else:
            cmd = axis(TARGET_Y - y, 0.0)
            if cmd == 'rest':
                rest_until = tick + 1.5                     # at the target: stop (a long stop locks in any rule)
    elif phase == 'in':
        if st == 'mode2-out' or st == 'mode1':
            say(f'{tick - t0:6.1f} s  put down -> {st}')
            break
        cmd = 'up' if x < 0.72 else 'rest'
    pos = (round(x, 3), round(y, 3), round(z, 3))
    still = still + 1 if (cmd != 'rest' and cmd == cur and pos == last_pos) else 0
    last_pos = pos
    if still >= 8:                                          # held a direction 0.8 s and nothing moves: relax, again
        still, rest_until = 0, tick + 0.3
        n_stuck = globals().get('n_stuck', 0) + 1
        say(f'{tick - t0:6.1f} s  no motion on {cmd}: relax 0.3 s, then the gesture again')
        cmd = 'rest'
    send(cmd)
    time.sleep(max(0.0, 0.1 - (time.time() - tick)))
say(f'RESULT locks {locks} wrong {wrong} time {time.time() - t0:.1f} s phase {phase} '
    f'stuck {globals().get("n_stuck", 0)} send errors {n_err}')
for _ in range(20):
    send('rest'); time.sleep(0.1)
c.close()
