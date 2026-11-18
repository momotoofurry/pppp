"""joint-limit margin of candidate start points (tool horizontal, forward), best over seeds, with the posture term"""
import sys
sys.path.insert(0, '/work/src/assist')
import numpy as np
import kin

RD = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float)
SEEDS = ([0, 15, 180, 230, 0, 55, 90], [0, 30, 0, 110, 0, 40, 90], [0, 40, 180, 250, 0, -60, 90],
         [30, 70, 280, 120, 0, -100, 70])
for x0 in (0.50, 0.55, 0.58):
    for z0 in (0.25, 0.30, 0.35, 0.40):
        p = np.array([x0, 0.0, z0])
        sols = [kin.solve(np.radians(s), p, RD, iters=1500, posture=True) for s in SEEDS]
        ok = [q for q in sols if np.linalg.norm(kin.fk(q)[:3, 3] - p) < 0.002
              and np.degrees(np.linalg.norm(kin.rot_err(kin.fk(q)[:3, :3], RD))) < 1.0]
        if not ok:
            print(p.tolist(), 'not reached')
            continue
        q = max(ok, key=kin.margin)
        print(p.tolist(), f'margin {np.degrees(kin.margin(q)):5.1f} deg', np.round(np.degrees(q)).tolist())
