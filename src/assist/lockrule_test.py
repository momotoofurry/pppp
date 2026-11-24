"""35.89: shelf lock rule while carrying (modes.py lock_rule), crowded scene of 35.87.
  room / intent: a full shelf (two objects 8 cm apart) is never locked, the hint says why
  intent: carried straight at a shelf, a stop locks it at once
  intent: a shelf only passed on the way (motion points past it) locks only after the 1 s stop
  none: as before, the passed shelf locks at once"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import modes as M  # noqa: E402

LOWER = [(0.72, y, 0.05) for y in (-0.25, 0.0, 0.25)]
SHELVES = np.array(LOWER + [(0.72, y, 0.25) for y in (-0.25, 0.0, 0.25)])
OBJ = np.array([(x, y + dy, z + 0.05) for (x, y, z) in LOWER for dy in (-0.04, 0.04)])
bad = 0


def check(ok, what):
    global bad
    bad += not ok
    print(f'  {"ok " if ok else "BAD"}  {what}')


def carrying(rule, x0):
    ma = M.ModeAssist(OBJ.copy(), SHELVES, rule='mix', lock_rule=rule)
    x = np.array([ma.x_travel, *x0], float)
    ma.held, ma.phase, ma.m, ma.armed = 0, 'out', 1, True
    ma.obj[0] = x
    return ma, x


def run(ma, x, cmds):
    for c in cmds:
        v = ma.step(c, x)
        x = x + v * M.DT
    return x


def move(ma, x, cmd, axis, to):
    """hold cmd until coordinate axis reaches to (the arm slows near the shelves)"""
    for _ in range(400):
        if abs(x[axis] - to) < 0.004:
            break
        x = run(ma, x, [cmd])
    return x


for rule in ('room', 'intent'):
    ma, x = carrying(rule, (-0.25, 0.14))
    x = move(ma, x, 'left', 1, 0.0)                    # to the lower middle shelf (full)
    x = run(ma, x, [None] * 15)                        # and a long stop
    check(ma.m == 1 and '沒有空位' in ma.msg, f'{rule}: full lower middle shelf not locked, hint "{ma.msg}"')

ma, x = carrying('intent', (-0.25, 0.20))
x = move(ma, x, 'up', 2, 0.34)                         # straight up to the upper left shelf
x = run(ma, x, [None] * 2)
check(ma.m == 2 and ma.shelf == 3, f'intent: carried straight at the upper left shelf, locked at once (shelf {ma.shelf})')

for rule, want_now in (('intent', False), ('none', True)):
    ma, x = carrying(rule, (-0.25, 0.34))
    x = move(ma, x, 'left', 1, 0.0)                    # past the upper left, stop at the upper middle on the way right
    x = run(ma, x, [None] * 3)
    check((ma.m == 2) == want_now, f'{rule}: passing the upper middle shelf, 0.3 s stop -> locked {ma.m == 2}')
    if not want_now:
        x = run(ma, x, [None] * 8)
        check(ma.m == 2 and ma.shelf == 4, f'{rule}: after a 1 s stop it locks (shelf {ma.shelf})')

print('ALL OK' if bad == 0 else 'FAILED')
sys.exit(bad > 0)
