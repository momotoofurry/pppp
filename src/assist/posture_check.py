"""joint angles and joint-limit margins of the IK along the demo task (start, every pre-grasp and grasp point, the
empty shelves), and how much the joints move per 100 ms step (jerk): with and without the posture term"""
import sys
sys.path.insert(0, '/work/src/assist')
import numpy as np
import kin

RD = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float)
X0 = np.array([0.58, 0.0, 0.35] if len(sys.argv) > 2 else [0.50, 0.0, 0.30])
OBJ = np.array([[0.75, 0.25, 0.10], [0.70, -0.25, 0.30], [0.77, 0.0, 0.10]])
PRE = np.array([-0.10, 0, 0])
SEEDS = ([0, 15, 180, 230, 0, 55, 90], [0, 30, 0, 110, 0, 40, 90], [0, 40, 180, 250, 0, -60, 90],
         [30, 70, 280, 120, 0, -100, 70])
posture = len(sys.argv) > 1 and sys.argv[1] == 'posture'


def margin(q):
    return min(kin.LIMITS[i] - abs(q[i]) for i in kin.LIMITS)


def step(q, v):
    return kin.ik_step(q, v, RD, 0.1, posture=True, q_rest=Q_REST) if posture else kin.ik_step(q, v, RD, 0.1)


sols = [kin.solve(np.radians(s), X0, RD, iters=1200, **({'posture': True} if posture else {})) for s in SEEDS]
ok = [qq for qq in sols if np.linalg.norm(kin.fk(qq)[:3, 3] - X0) < 0.002]
q = max(ok, key=margin) if posture else min(sols, key=lambda qq: np.linalg.norm(kin.fk(qq)[:3, 3] - X0))
Q_REST = q.copy()
print('posture term' if posture else 'no posture term')
print('start    q deg', np.round(np.degrees(q)).tolist(), ' min margin to a limit', round(np.degrees(margin(q)), 1), 'deg')
path = [X0]
for o in OBJ:
    path += [o + PRE, o, o + PRE, X0]
path += [np.array([0.72, -0.25, 0.10]), X0, np.array([0.72, 0.25, 0.30]), X0]
worst, jump, perr = 1e9, 0, 0
x = X0.copy()
for tgt in path[1:]:
    for _ in range(200):
        d = tgt - kin.fk(q)[:3, 3]
        if np.linalg.norm(d) < 0.002:
            break
        v = min(0.08, np.linalg.norm(d) / 0.1) * d / np.linalg.norm(d)
        qn = step(q, v)
        jump = max(jump, np.degrees(np.abs(qn - q)).max())
        q = qn
        worst = min(worst, margin(q))
    perr = max(perr, np.linalg.norm(tgt - kin.fk(q)[:3, 3]))
    print(f'  at {np.round(tgt, 2).tolist()}: q deg {np.round(np.degrees(q)).tolist()}, margin {np.degrees(margin(q)):.1f} deg')
print(f'wrist twist (joints 5, 7) range over the path: see the q lists; worst margin on the whole path {np.degrees(worst):.1f} deg; largest joint change in one 100 ms step {jump:.1f} deg; '
      f'largest end error {1000 * perr:.1f} mm')
