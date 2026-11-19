"""Checks of the 35.67 mode-1 steering (modes.py rule 'mix' and the assist exit), in a scene built for each case.

1 one object up-left in its zone             -> help toward it (as 'lead')
2 two objects up-left / up-right, equal P     -> 'mix' helps only upward (what they share); 'lead' picks one side
3 two objects up / down, equal P              -> 'mix' gives no help (they cancel)
4 the user pushes away from every candidate   -> the assist switches off after MISMATCH_STEPS, a relax brings it back
5 at an object's pre-grasp point, W up        -> the arm moves up (no pull back)
usage: python src/assist/modes_assist_test.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import modes as M  # noqa: E402

SHELF_FAR = [[1.5, 0.0, 0.0]]          # a shelf far away (unused; ModeAssist needs one)
ok_all = True
RULE = 'mix'


def check(name, cond, extra=''):
    """only the new rule must pass; the old one ('lead', 35.63) is printed for comparison"""
    global ok_all
    if RULE == 'mix':
        ok_all &= bool(cond)
        print(f'  {"ok " if cond else "BAD"}  {name}  {extra}')
    else:
        print(f'  {"(yes)" if cond else "(no) "}  {name}  {extra}')


def ma_for(objs, rule):
    ma = M.ModeAssist(np.array(objs, float), SHELF_FAR, rule=rule)
    ma.x_travel = 0.58
    return ma


def push(ma, cmd, x, n):
    vs = []
    for _ in range(n):
        v = ma.step(cmd, x)
        vs.append(v)
    return vs


x0 = np.array([0.58, 0.0, 0.30])
# objects' pre-grasp points are 10 cm in front (PRE): put the objects at x 0.68 so the pre points are in the plane
for rule in ('mix', 'lead'):
    RULE = rule
    print(f'rule {rule}' + ('' if rule == 'mix' else ' (35.63, for comparison: not required to pass)'))
    # 1
    ma = ma_for([[0.68, 0.06, 0.36]], rule)
    v = push(ma, 'up', x0, 8)[-1]
    check('1 one object up-left: bends toward it (y > 0)', v[1] > 0.005, np.round(v, 3).tolist())
    # 2
    ma = ma_for([[0.68, 0.06, 0.38], [0.68, -0.06, 0.38]], rule)
    v = push(ma, 'up', x0, 8)[-1]
    if rule == 'mix':
        check('2 two objects up-left / up-right: straight up, no sideways', abs(v[1]) < 0.002 and v[2] > 0.07,
              np.round(v, 3).tolist())
    else:
        print(f'       2 (lead) two objects up-left / up-right: v = {np.round(v, 3).tolist()}')
    # 3
    ma = ma_for([[0.68, 0.0, 0.38], [0.68, 0.0, 0.22]], rule)
    ma.base.s[:] = 0.0
    v = ma.step('left', x0)
    if rule == 'mix':
        check('3 two objects straight up / down, user goes left: no help (a = 0)', ma.a_last < 1e-6,
              f'a {ma.a_last:.3f}, v {np.round(v, 3).tolist()}')
    else:
        print(f'       3 (lead) objects up / down, user goes left: a = {ma.a_last:.3f}')
    # 4: the user goes up past an object slightly to the left (wants something higher): once past it, every command
    #    points away from it while it is still in its zone -> the assist must let go
    ma = ma_for([[0.68, 0.03, 0.34]], rule)
    x = x0.copy()
    off_at, a_max = None, 0.0
    for i in range(40):
        v = ma.step('up', x)
        x = x + v * M.DT
        a_max = max(a_max, ma.a_last)
        if ma.assist_off and off_at is None:
            off_at = (i, x.copy(), ma.describe(x))
    dz = np.linalg.norm((ma.obj[0] + M.PRE - off_at[1])[1:]) if off_at else None
    check('4 going up past an object: the assist switches off while still in its zone',
          off_at is not None and dz < 0.12, f'(max share {a_max:.2f}; off after {off_at[0] + 1 if off_at else "-"} steps, '
          f'{100 * dz:.1f} cm from it)' if off_at else f'(max share {a_max:.2f})')
    check('4 the hint says so', off_at is not None and off_at[2][0] == 'off', off_at[2][2] if off_at else '')
    check('4 after that the arm goes straight up', abs(x[1] - (off_at[1][1] if off_at else 9)) < 1e-6)
    ma.step(None, x)
    check('4 a relax brings it back', not ma.assist_off)
    # 5
    ma = ma_for([[0.68, 0.0, 0.30]], rule)
    push(ma, 'left', x0 + [0, -0.03, 0], 3)
    x = x0.copy()
    zs = []
    for _ in range(10):
        v = ma.step('up', x)
        x = x + v * M.DT
        zs.append(x[2])
    check('5 at the pre-grasp point, W moves up steadily', all(b > a for a, b in zip(zs, zs[1:])) and zs[-1] - x0[2] > 0.05,
          f'z {zs[0]:.3f} -> {zs[-1]:.3f}')
print('ALL OK' if ok_all else 'FAILED')
