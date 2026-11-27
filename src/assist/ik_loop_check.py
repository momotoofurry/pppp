"""reproduce the RViz loop without ROS: ModeAssist + kin.ik_step with the position hold, as assist_ros.py; print the
distance to object 0 while W approaches and while relaxing to grasp"""
import sys
sys.path.insert(0, '/work/src/assist')
import numpy as np
import kin
import modes as M

RD = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float)
OBJ = np.array([[0.75, 0.25, 0.10], [0.70, -0.25, 0.30], [0.77, 0.0, 0.10]])
SHELVES = np.vstack([OBJ - [0, 0, 0.05], [[0.72, -0.25, 0.05], [0.72, 0.25, 0.25]]])
X0 = np.array([0.58, 0.0, 0.35])
SEEDS = ([0, 15, 180, 230, 0, 55, 90], [0, 30, 0, 110, 0, 40, 90], [0, 40, 180, 250, 0, -60, 90], [30, 70, 280, 120, 0, -100, 70])
sols = [kin.solve(np.radians(s), X0, RD, iters=1500, posture=True) for s in SEEDS]
good = [qq for qq in sols if np.linalg.norm(kin.fk(qq)[:3, 3] - X0) < 0.002]
q = max(good, key=kin.margin)
q_rest = q.copy()
ma = M.ModeAssist(OBJ, SHELVES)
xc = kin.fk(q)[:3, 3].copy()


def step(cmd):
    global q, xc
    x = kin.fk(q)[:3, 3]
    v = ma.step(cmd, x)
    xc = xc + v * M.DT
    q = kin.ik_step(q, v + 2.0 * (xc - kin.fk(q)[:3, 3]), RD, M.DT, posture=True, q_rest=q_rest)
    return x, v


for _ in range(60):
    x, v = step('down')
    if x[2] <= 0.10:
        break
for _ in range(80):
    x, v = step('left')
    if x[1] >= 0.24:
        break
for _ in range(3):
    step(None)
print('after lining up:', ma.state, ma.goal, np.round(kin.fk(q)[:3, 3], 3).tolist())
for i in range(60):
    x, v = step('up')
    if i % 5 == 0:
        print(f'W {i:2d}: x={np.round(x, 3).tolist()} v={np.round(v, 3).tolist()} dist={1000 * np.linalg.norm(OBJ[0] - x):.1f} mm '
              f'xc-x={1000 * np.linalg.norm(xc - x):.1f} mm')
for i in range(15):
    x, v = step(None)
    print(f'rest {i:2d}: dist={1000 * np.linalg.norm(ma.obj[0] - x):.1f} mm state={ma.state} held={ma.held}')
