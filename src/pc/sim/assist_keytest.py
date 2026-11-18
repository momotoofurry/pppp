"""Usage (WSL, sim up, no other keys / demo session running): python3 src/pc/sim/assist_keytest.py
keys mode (35.62 W / S lock) through a pseudo-terminal, waiting on what the program prints and on the logged tool
position (like a person watching): down, stop in front of object 2 -> locked, S cancels; left to object 0, stop ->
locked, W in, space grasps; lift, pause in the air; carry right, lower onto the empty shelf, space puts it down; left to
object 2, stop -> locked, W in, space grasps"""
import os
import pty
import select
import time

pid, fd = pty.fork()
if pid == 0:
    os.execvp('python3', ['python3', 'src/pc/sim/assist_ros.py', 'keys', '--log', '/tmp/assist_keytest.csv'])
out = b''


def pump(sec):
    global out
    t = time.time()
    while time.time() - t < sec:
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                out += os.read(fd, 4096)
            except OSError:
                return


def key(k):
    os.write(fd, k)


def wait_for(text, limit=20):
    n0 = len(out)
    t = time.time()
    while time.time() - t < limit:
        pump(0.1)
        if text.encode() in out[n0:]:
            return True
    print(f'!! timeout waiting for {text!r}')
    return False


def pos():
    try:
        last = open('/tmp/assist_keytest.csv', encoding='utf-8').read().strip().splitlines()[-1].split(',')
        return float(last[-3]), float(last[-2]), float(last[-1])
    except (OSError, IndexError, ValueError):
        return None


def wait_pos(cond, limit=20):
    t = time.time()
    while time.time() - t < limit:
        pump(0.1)
        p_ = pos()
        if p_ and cond(*p_):
            return True
    print('!! timeout waiting for a position, at', pos())
    return False


steps = []
wait_for('ready', 60)
key(b's'); steps.append(wait_pos(lambda x, y, z: z <= 0.11))
key(b' '); steps.append(wait_for('final, goal object 2'))          # stopped in front of object 2: locked
key(b's'); steps.append(wait_for('assist: steer'))                  # S cancels
key(b'a'); steps.append(wait_pos(lambda x, y, z: y >= 0.235))
key(b' '); steps.append(wait_for('final, goal object 0'))          # locked object 0
key(b'w'); steps.append(wait_for('到了物體 0'))                       # W in
key(b' '); steps.append(wait_for('grasped, goal object 0'))        # grasp
key(b'w'); pump(1.0)                                               # lift
key(b' '); pump(2.0)                                               # pause in the air
steps.append(b'assist: steer' not in out[-300:])
key(b'd'); steps.append(wait_pos(lambda x, y, z: y <= -0.248))
key(b's'); steps.append(wait_for('在架子上方'))
key(b' '); steps.append(wait_for('assist: steer'))                  # put down
key(b'a'); steps.append(wait_pos(lambda x, y, z: y >= -0.01))
key(b' '); steps.append(wait_for('final, goal object 2'))
key(b'w'); steps.append(wait_for('到了物體 2'))
key(b' '); steps.append(wait_for('grasped, goal object 2'))
key(b'q'); pump(3)
print(out.decode(errors='replace'))
print('steps ok:', steps)
