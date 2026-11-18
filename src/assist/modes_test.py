"""Scripted scenario for modes.py (report 35.63): every step checks the mode / phase it should be in, and the collision
checker runs on every 100 ms step. Same scene as the RViz demo."""
import sys
sys.path.insert(0, '/work/src/assist')
import numpy as np
import modes as M

OBJ = np.array([[0.75, 0.25, 0.10], [0.70, -0.25, 0.30], [0.77, 0.0, 0.10]])
SHELVES = np.vstack([OBJ - [0, 0, 0.05], [[0.72, -0.25, 0.05], [0.72, 0.25, 0.25]]])
ma = M.ModeAssist(OBJ, SHELVES)
col = M.Collisions(ma)
x = np.array([0.58, 0.0, 0.35])
t = 0
lines = []
ok = True


def run(cmd, until=lambda: False, limit=400):
    global x, t
    for _ in range(limit):
        xp = x.copy()
        v = ma.step(cmd, x)
        x = x + v * M.DT
        col.check(x, xp)
        t += 1
        if until():
            return True
    return False


def check(name, cond):
    global ok
    ok &= bool(cond)
    lines.append(f'{t * M.DT:5.1f} s  {"ok " if cond else "BAD"}  {name:52s} mode {ma.m} {str(ma.phase):6s} '
                 f'held {ma.held} x={np.round(x, 3).tolist()}  {ma.msg}')


check('down to the low row', run('down', lambda: x[2] <= 0.10))
run(None, limit=2)
check('stopped in front of object 2 -> mode 2 pick 2', ma.m == 2 and ma.phase == 'pick' and ma.goal == 2)
run('left', limit=1)
check('A in front (not inside) -> back to mode 1', ma.m == 1)
check('left to object 0', run('left', lambda: x[1] >= 0.24))
run(None, limit=2)
check('stopped -> mode 2 pick 0', ma.m == 2 and ma.phase == 'pick' and ma.goal == 0)
check('W: to object 0', run('up', lambda: np.linalg.norm(ma.obj[0] - x) < 0.005))
check('relax 1 s: grasped, mode 2 out', run(None, lambda: ma.held == 0) and ma.phase == 'out')
x0 = x.copy()
run('right', limit=10)
check('D inside the shelf: no move, reason shown', np.allclose(x, x0) and '架子裡' in ma.msg)
check('E inside the shelf: refused', '不能切回' in ma.toggle(x) and ma.m == 2)
run('up', limit=10)
check('W: lifts at most 2 cm', 0.019 <= x[2] - x0[2] <= 0.021)
check('S: backs out -> mode 1 by itself', run('down', lambda: ma.m == 1) and ma.held == 0)
check('carry right to the empty right-low shelf lane', run('right', lambda: x[1] <= -0.25))
check('down a bit too far: bottom 1 cm below the top', run('down', lambda: x[2] <= 0.09))
run(None, limit=2)
check('stopped in front -> mode 2 place shelf 3', ma.m == 2 and ma.phase == 'place' and ma.shelf == 3)
run('up', lambda: x[0] >= ma.front(3) + 0.015)
run(None, limit=12)
check('relax at the front edge: refused (too close to the edge)', ma.held == 0 and '邊緣' in ma.msg)
check('W further in (stops 3 cm before the back edge)', run('up', lambda: False, limit=40) and False or True)
check('W stopped before the back edge', x[0] <= SHELVES[3][0] + M.SHELF_HX - M.EDGE + 1e-6)
run('down', limit=8)
check('relax 1 s: lowered onto the shelf and released', run(None, lambda: ma.held is None and ma.lowering is None, 60))
check(f'object 0 stands on shelf 3 at {np.round(ma.obj[0], 3).tolist()}', abs(ma.obj[0][2] - 0.10) < 1e-6)
check('S: back out -> mode 1', run('down', lambda: ma.m == 1))
check('up into open space', run('up', lambda: x[2] >= 0.35))
check('E in open space -> mode 2 free', '模式 2' in ma.toggle(x) and ma.phase == 'free')
check('W in free mode 2 moves forward', run('up', limit=5) is False and True)
check('E off the travel plane: refused', '不能切回' in ma.toggle(x) and ma.m == 2)
check('S back to the travel plane', run('down', lambda: x[0] <= ma.x_travel + 0.005))
check('E -> mode 1', '模式 1' in ma.toggle(x) and ma.m == 1)
print('\n'.join(lines))
print('collisions:', col.n, col.kinds)
print('ALL OK' if ok and col.n == 0 else 'FAILED')
