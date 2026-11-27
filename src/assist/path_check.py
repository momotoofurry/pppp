"""follow the travel plane x = 0.58 with the IK alone (as assist_ros.py): right to y -0.25, then down to z 0.10;
print the tool, its error to the commanded point and the joint margins every few steps"""
import sys
sys.path.insert(0, '/work/src/assist')
import numpy as np
import kin

RD = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float)
X0 = np.array([0.58, 0.0, 0.35])
SEEDS = ([0, 15, 180, 230, 0, 55, 90], [0, 30, 0, 110, 0, 40, 90], [0, 40, 180, 250, 0, -60, 90], [30, 70, 280, 120, 0, -100, 70])
sols = [kin.solve(np.radians(s), X0, RD, iters=1500, posture=True) for s in SEEDS]
good = [qq for qq in sols if np.linalg.norm(kin.fk(qq)[:3, 3] - X0) < 0.002]
q = max(good, key=kin.margin)
q_rest = q.copy()
xc = X0.copy()
for leg, v, n in (('right', np.array([0, -0.08, 0]), 32), ('down', np.array([0, 0, -0.08]), 32),
                  ('left', np.array([0, 0.08, 0]), 64), ('up', np.array([0, 0, 0.08]), 32)):
    for i in range(n):
        xc = xc + v * 0.1
        q = kin.ik_step(q, v, RD, 0.1, posture=True, q_rest=q_rest)
        if i % 8 == 7:
            x = kin.fk(q)[:3, 3]
            print(f'{leg:5s} {i + 1:2d}: tool {np.round(x, 3).tolist()} err {1000 * np.linalg.norm(x - xc):6.1f} mm '
                  f'margin {np.degrees(kin.margin(q)):5.1f} deg q {np.round(np.degrees(q)).tolist()}')
