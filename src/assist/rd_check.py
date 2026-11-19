"""finger direction of the two candidate tool orientations, and joint margins along the task with the new one (35.64).
The 2F-85 fingers open along the gripper's x axis (robotiq_85_left / right knuckle at +/- x)."""
import sys
sys.path.insert(0, '/work/src/assist')
import numpy as np
import kin

RD_OLD = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float)     # columns: tool x, y, z
RD_NEW = np.array([[0, 0, 1], [-1, 0, 0], [0, -1, 0]], float)    # tool x = -y (horizontal), y = -z, z = +x (forward)
for name, R in (('old', RD_OLD), ('new', RD_NEW)):
    print(name, 'fingers open along', R[:, 0].tolist(), 'approach along', R[:, 2].tolist(), 'det', round(np.linalg.det(R), 3))
RD = RD_NEW
SEEDS = ([0, 15, 180, 230, 0, 55, 90], [0, 30, 0, 110, 0, 40, 90], [0, 40, 180, 250, 0, -60, 90],
         [30, 70, 280, 120, 0, -100, 70], [30, 70, 280, 120, 0, -100, 160], [0, 40, 180, 250, 0, -60, 180])
for x0 in ((0.58, 0.0, 0.35),):
    p = np.array(x0)
    sols = [kin.solve(np.radians(s), p, RD, iters=1500, posture=True) for s in SEEDS]
    ok = [q for q in sols if np.linalg.norm(kin.fk(q)[:3, 3] - p) < 0.002
          and np.degrees(np.linalg.norm(kin.rot_err(kin.fk(q)[:3, :3], RD))) < 1.0]
    q = max(ok, key=kin.margin)
    print('start', x0, f'margin {np.degrees(kin.margin(q)):.1f} deg', np.round(np.degrees(q)).tolist())
q_rest = q.copy()
OBJ = np.array([[0.75, 0.25, 0.10], [0.70, -0.25, 0.30], [0.77, 0.0, 0.10]])
path = []
for o in OBJ:
    path += [np.array([0.58, o[1], o[2]]), o, np.array([0.58, o[1], o[2]]), np.array([0.58, 0, 0.35])]
path += [np.array([0.58, -0.25, 0.10]), np.array([0.76, -0.25, 0.10]), np.array([0.58, -0.25, 0.10]),
         np.array([0.58, 0.25, 0.30]), np.array([0.76, 0.25, 0.30]), np.array([0.58, 0, 0.35])]
worst, err = 1e9, 0
for tgt in path:
    for _ in range(300):
        d = tgt - kin.fk(q)[:3, 3]
        if np.linalg.norm(d) < 0.002:
            break
        q = kin.ik_step(q, min(0.08, np.linalg.norm(d) / 0.1) * d / np.linalg.norm(d), RD, 0.1, posture=True, q_rest=q_rest)
        worst = min(worst, kin.margin(q))
    err = max(err, np.linalg.norm(tgt - kin.fk(q)[:3, 3]), np.degrees(np.linalg.norm(kin.rot_err(kin.fk(q)[:3, :3], RD))) / 1000)
print(f'whole path: worst margin {np.degrees(worst):.1f} deg, largest end error {1000 * err:.1f} mm')
