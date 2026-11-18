"""Usage (WSL, sim up, no other keys / demo session running): python3 src/pc/sim/modes_keytest.py
Two-mode keys control (35.63) through a pseudo-terminal, waiting on what the program prints and on the logged tool
position: lock object 2 then A back to mode 1; lock object 0, W in, grasp; D inside (refused), E inside (refused);
W lifts, S back out -> mode 1; carry right, down, stop -> mode 2 place; W in, put down, S out -> mode 1; H to the
start; E -> mode 2, E -> mode 1."""
import os
import pty
import select
import time

LOG = '/tmp/modes_keytest.csv'
pid, fd = pty.fork()
if pid == 0:
    os.execvp('python3', ['python3', 'src/pc/sim/assist_ros.py', 'keys', '--log', LOG])
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
        last = open(LOG, encoding='utf-8').read().strip().splitlines()[-1].split(',')
        return float(last[-3]), float(last[-2]), float(last[-1])
    except (OSError, IndexError, ValueError):
        return None


def wait_pos(cond, limit=25):
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
key(b's'); steps.append(wait_pos(lambda x, y, z: z <= 0.10))
key(b' '); steps.append(wait_for('mode2-pick, goal object 2'))
key(b'a'); steps.append(wait_for('assist: mode1'))
steps.append(wait_pos(lambda x, y, z: y >= 0.24))
key(b' '); steps.append(wait_for('mode2-pick, goal object 0'))
key(b'w'); steps.append(wait_for('到了物體 0'))
key(b' '); steps.append(wait_for('mode2-out'))
key(b'd'); steps.append(wait_for('A／D 不能動'))
key(b'e'); steps.append(wait_for('不能切回'))
key(b'w'); pump(1.0)
key(b's'); steps.append(wait_for('assist: mode1'))
key(b'd'); steps.append(wait_pos(lambda x, y, z: y <= -0.25))
key(b's'); steps.append(wait_pos(lambda x, y, z: z <= 0.11))
key(b' '); steps.append(wait_for('mode2-place'))
key(b'w'); steps.append(wait_pos(lambda x, y, z: x >= 0.70))
key(b' '); steps.append(wait_for('正在把物體放到架面上'))
steps.append(wait_for('退回前方平面'))
key(b's'); steps.append(wait_for('assist: mode1'))
key(b'h'); steps.append(wait_for('回到起點'))
pump(3.5)
key(b'e'); steps.append(wait_for('切到模式 2'))
key(b'e'); steps.append(wait_for('切到模式 1'))
key(b'q'); pump(3)
print(out.decode(errors='replace'))
print('steps ok:', steps)
