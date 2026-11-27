"""Task scenes for the arm (report 35.101): object centres and shelf-top centres in the robot base frame (m).

  3obj     35.59 / modes_sim.py: 3 objects, one shelf under each + 2 empty shelves
  crowded  35.87 / closed_loop_fw.py --scene crowded: 3 lower shelves with 2 objects side by side (centres 8 cm apart),
           3 empty upper shelves to put down on
  <file>.json  {"objects": [[x, y, z], ...], "shelves": [[x, y, z], ...]}: the real lab layout after the scene
           calibration (SOP_Kinova section 5); spacing chosen after measuring the 2F-85 fingers
Objects are cylinders r 3 cm, h 10 cm (modes.py OBJ_R, OBJ_H); the object z is its centre."""
import json

import numpy as np

OBJ_3 = np.array([[0.75, 0.25, 0.10], [0.70, -0.25, 0.30], [0.77, 0.0, 0.10]])
SHELVES_3 = np.vstack([OBJ_3 - [0, 0, 0.05], [[0.72, -0.25, 0.05], [0.72, 0.25, 0.25]]])

CROWD_LOWER = [(0.72, y, 0.05) for y in (-0.25, 0.0, 0.25)]
SHELVES_C = np.array(CROWD_LOWER + [(0.72, y, 0.25) for y in (-0.25, 0.0, 0.25)])
OBJ_C = np.array([(x, y + dy, z + 0.05) for (x, y, z) in CROWD_LOWER for dy in (-0.04, 0.04)])
# 12 cm centre spacing (6 cm clear gap between 6 cm cylinders) for 2F-85 finger clearance
CROWD12_LOWER = [(0.72, y, 0.05) for y in (-0.28, 0.0, 0.28)]
SHELVES_C12 = np.array(CROWD12_LOWER + [(0.72, y, 0.25) for y in (-0.28, 0.0, 0.28)])
OBJ_C12 = np.array([(x, y + dy, z + 0.05) for (x, y, z) in CROWD12_LOWER for dy in (-0.06, 0.06)])

OBJ_H = 0.10


def load(name):
    """-> (objects, shelves) as new float arrays"""
    if name == '3obj':
        return OBJ_3.copy(), SHELVES_3.copy()
    if name == 'crowded':
        return OBJ_C.copy(), SHELVES_C.copy()
    if name == 'crowded12':
        return OBJ_C12.copy(), SHELVES_C12.copy()
    with open(name, encoding='utf-8') as f:
        d = json.load(f)
    o, s = np.array(d['objects'], float), np.array(d['shelves'], float)
    assert o.ndim == 2 and o.shape[1] == 3 and s.ndim == 2 and s.shape[1] == 3, 'objects / shelves must be lists of [x, y, z]'
    return o, s


def free_shelves(objects, shelves):
    """shelves with no object standing on them at the start (the put-down targets; closed_loop_fw's rule)"""
    return [k for k in range(len(shelves))
            if all(np.linalg.norm(o[:2] - shelves[k][:2]) > 0.06 or abs(o[2] - (shelves[k][2] + OBJ_H / 2)) > 0.03
                   for o in objects)]


def shelf_of(p, shelves, half=(0.10, 0.08)):
    """index of the shelf an object centre p stands on (inside the board, bottom within 3 cm of the top), else None"""
    for k, s in enumerate(shelves):
        if abs(p[0] - s[0]) <= half[0] and abs(p[1] - s[1]) <= half[1] and abs(p[2] - OBJ_H / 2 - s[2]) < 0.03:
            return k
    return None


def names(objects, shelves):
    """Chinese names as the user sees the scene from behind the arm (+y = left, higher z = upper)"""
    def side(y, ys):
        if len(set(np.round(ys, 2))) == 1:
            return ''
        return '左' if y > np.median(ys) + 0.1 else '右' if y < np.median(ys) - 0.1 else '中'
    zs = shelves[:, 2]
    mid = (zs.max() + zs.min()) / 2
    lvl = lambda z: '' if zs.max() - zs.min() < 0.05 else '上層' if z > mid else '下層'   # noqa: E731
    sn = [f'{lvl(s[2])}{side(s[1], shelves[:, 1])}架子' for s in shelves]
    on = [shelf_of(o, shelves) for o in objects]
    on_names = []
    for i, o in enumerate(objects):
        k = on[i]
        mates = [j for j in range(len(objects)) if on[j] == k and k is not None]
        if len(mates) > 1:
            pos = '左邊' if o[1] == max(objects[j][1] for j in mates) else '右邊'
            on_names.append(f'{sn[k]}的{pos}那個')
        else:
            on_names.append(sn[k] if k is not None else f'物體 {i}')
    return on_names, sn
