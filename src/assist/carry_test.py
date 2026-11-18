"""offline check of keep=True (no ROS): pick object 0, carry it to the empty right-low shelf, put it down, pick
object 2. A scripted user with feedback (like the pty test): steer until the phase changes."""
import sys
sys.path.insert(0, '/work/src/assist')
import numpy as np
import assist as A

OBJ = np.array([[0.75, 0.25, 0.10], [0.70, -0.25, 0.30], [0.77, 0.0, 0.10]])
SHELVES = np.vstack([OBJ - [0, 0, 0.05], [[0.72, -0.25, 0.05], [0.72, 0.25, 0.25]]])
sa = A.Assist(OBJ, mode='blend', keep=True, shelves=SHELVES)
x = np.array([0.50, 0.0, 0.30])
t = 0
events = []


def run(cmd, until, limit=400):
    global x, t
    for _ in range(limit):
        v = sa.step(cmd, x)
        x = x + v * A.DT
        t += 1
        if until():
            return True
    return False


def note(s):
    events.append(f'{t * A.DT:5.1f} s  {s}  x={np.round(x, 3).tolist()} state={sa.state} goal={sa.goal}')


ok = run('down', lambda: x[2] <= 0.11); note('down to the low row')
ok &= run('left', lambda: sa.state == 'final'); note('left until final')
ok &= run('left', lambda: np.linalg.norm(sa.obj[sa.goal] - x) < 0.005); note('held left: in at the object')
ok &= run(None, lambda: sa.state == 'grasped'); note('relaxed: grasped')
run(None, lambda: False, limit=20); note('kept relaxing 2 s after the grasp: must still hold')
ok &= sa.state == 'grasped'
ok &= run('up', lambda: x[2] >= 0.18); note('lift')
run(None, lambda: False, limit=20); note('relaxed in the air 2 s: still holding (not over a shelf)')
ok &= sa.state == 'grasped'
ok &= run('right', lambda: x[1] <= -0.25); note('carried right')
ok &= run('down', lambda: sa.place_ok(x) is not None); note('down over the empty shelf')
ok &= run(None, lambda: sa.state == 'steer'); note('relaxed: put down')
held = 0
ok &= (np.linalg.norm(sa.obj[0][:2] - x[:2]) < 0.01 and abs(sa.obj[0][2] - 0.10) < 1e-9 and sa.grip == 0.0)
note(f'object 0 now at {np.round(sa.obj[0], 3).tolist()} (on the shelf top 0.05 + 0.05)')
ok &= run('left', lambda: sa.state == 'final' and sa.goal == 2, limit=300); note('left toward object 2 until final')
ok &= run('left', lambda: np.linalg.norm(sa.obj[2] - x) < 0.005); note('held left: in at object 2')
ok &= run(None, lambda: sa.state == 'grasped'); note('relaxed: grasped object 2')
print('\n'.join(events))
print('ALL OK' if ok and sa.goal == 2 else 'FAILED')
