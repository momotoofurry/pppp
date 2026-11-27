import sys; sys.path.insert(0, '/work/src/assist')
import numpy as np, kin
RD = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float)
seed = np.radians([0, 15, 180, 230, 0, 55, 90])
def best(p):
    r = []
    for s in ([0, 15, 180, 230, 0, 55, 90], [0, 30, 0, 110, 0, 40, 90], [0, 40, 180, 250, 0, -60, 90]):
        q = kin.solve(np.radians(s), np.array(p), RD, iters=1200)
        T = kin.fk(q)
        r.append((1000*np.linalg.norm(T[:3,3]-p), np.degrees(np.linalg.norm(kin.rot_err(T[:3,:3], RD))), q))
    return min(r, key=lambda z: z[0] + z[1])
for p in [(0.40,0,0.30),(0.45,0,0.30),(0.45,0,0.40),(0.50,0,0.35)]:
    e, a, q = best(p); print('start', p, round(e,1), 'mm', round(a,1), 'deg')
for x in (0.60, 0.70, 0.80):
    for y in (-0.25, 0, 0.25):
        for z in (0.10, 0.30):
            e, a, q = best((x, y, z)); print('obj', (x, y, z), round(e,1), 'mm', round(a,1), 'deg')
