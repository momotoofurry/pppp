"""offline check of the blend mode with keep=True and the W / S lock (35.62), no ROS:
lock object 2 by stopping in front of it, cancel with S; lock object 0, W in, grasp; relax in the air (keeps holding);
carry it to the empty right-low shelf, put it down; lock object 2 again, W in, grasp."""
import sys
sys.path.insert(0, '/work/src/assist')
import numpy as np
import assist as A

OBJ = np.array([[0.75, 0.25, 0.10], [0.70, -0.25, 0.30], [0.77, 0.0, 0.10]])
SHELVES = np.vstack([OBJ - [0, 0, 0.05], [[0.72, -0.25, 0.05], [0.72, 0.25, 0.25]]])
sa = A.Assist(OBJ, mode='blend', keep=True, shelves=SHELVES, zone=0.12)
x = np.array([0.58, 0.0, 0.35])
t = 0
events = []
ok = True


def run(cmd, until, limit=400):
    global x, t
    for _ in range(limit):
        v = sa.step(cmd, x)
        x = x + v * A.DT
        t += 1
        if until():
            return True
    return False


def check(name, cond):
    global ok
    ok &= bool(cond)
    events.append(f'{t * A.DT:5.1f} s  {"ok " if cond else "BAD"} {name}  x={np.round(x, 3).tolist()} state={sa.state} '
                  f'goal={sa.goal}')


check('down to the low row', run('down', lambda: x[2] <= 0.10))
run(None, lambda: False, limit=3)
check('stopped in front of object 2: locked', sa.state == 'final' and sa.goal == 2)
check('S backs out and cancels', run('down', lambda: sa.state == 'steer') and sa.goal is None)
check('left until in front of object 0', run('left', lambda: x[1] >= 0.24))
run(None, lambda: False, limit=3)
check('stopped: object 0 locked', sa.state == 'final' and sa.goal == 0)
check('W: approach to the object', run('up', lambda: np.linalg.norm(sa.obj[0] - x) < 0.005))
check('relaxed: grasped', run(None, lambda: sa.state == 'grasped') and sa.goal == 0)
run(None, lambda: False, limit=20)
check('kept relaxing 2 s after the grasp: still holding', sa.state == 'grasped')
check('lift', run('up', lambda: x[2] >= 0.18))
run(None, lambda: False, limit=20)
check('relaxed in the air 2 s: still holding', sa.state == 'grasped')
check('carried right', run('right', lambda: x[1] <= -0.25))
check('down over the empty shelf', run('down', lambda: sa.place_ok(x) is not None))
check('relaxed: put down', run(None, lambda: sa.state == 'steer'))
check(f'object 0 on the shelf at {np.round(sa.obj[0], 3).tolist()}', abs(sa.obj[0][2] - 0.10) < 1e-9 and sa.grip == 0.0)
check('left until in front of object 2', run('left', lambda: x[1] >= -0.01))
run(None, lambda: False, limit=3)
check('stopped: object 2 locked', sa.state == 'final' and sa.goal == 2)
check('W: approach object 2', run('up', lambda: np.linalg.norm(sa.obj[2] - x) < 0.005))
check('relaxed: grasped object 2', run(None, lambda: sa.state == 'grasped') and sa.goal == 2)
print('\n'.join(events))
print('ALL OK' if ok else 'FAILED')
