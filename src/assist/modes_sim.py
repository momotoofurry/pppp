"""Pick-and-place with the two-mode control (modes.py) under classifier errors (report 35.63).

Task per trial: pick a random object and put it on a random free shelf, then back out to the travel plane (mode 1).
Scene: the RViz demo's 3 objects and 5 shelves. Decoder: assist_sim.Decoder over the 5 classes (4 directions + rest)
with window error e, K = 3 (the board's rule); errors independent between windows. The simulated user sees the arm
REACT = 3 steps late but reads the mode / phase at once (as on the screen); it lets go of a direction LEAD early.
User policy: mode 1 -> align (y, z) in front of the target (or the target shelf's height band), stop; mode 2 pick ->
W to the object, relax to grasp; out -> S; place -> W to the shelf centre, relax; refused spot -> W a little more;
wrong lock -> S. Limit 90 s.
Measured: success (object on the target shelf at a valid spot, arm back in mode 1), time, collision steps by kind
(modes.Collisions), commands refused (A / D inside a shelf), refused put-downs, wrong locks.

usage: python src/assist/modes_sim.py [--trials 300] [--out results/assist]
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assist_sim as S  # noqa: E402
import modes as M  # noqa: E402

OBJ = np.array([[0.75, 0.25, 0.10], [0.70, -0.25, 0.30], [0.77, 0.0, 0.10]])
SHELVES = np.vstack([OBJ - [0, 0, 0.05], [[0.72, -0.25, 0.05], [0.72, 0.25, 0.25]]])
X0 = np.array([0.58, 0.0, 0.35])
T_MAX = 900
LEAD = M.V_MAX * M.DT * (S.REACT + S.K) * 0.6


def axis_toward(d):
    i = 1 if abs(d[1]) >= abs(d[2]) else 2
    return S.axis_cmd(d, (i,)), i


def user(ma, seen, t_obj, t_shelf, est):
    if ma.lowering is not None:
        return 'rest'
    if ma.m == 2:
        if ma.phase == 'pick':
            if ma.goal != t_obj:
                return 'down'
            return 'rest' if np.linalg.norm(ma.obj[t_obj] - seen) < M.GRASP_TOL else 'up'
        if ma.phase == 'out':
            return 'down'
        if ma.phase == 'place':
            if ma.shelf != t_shelf:
                return 'down'
            if '邊緣' in ma.msg or seen[0] < SHELVES[t_shelf][0] - 0.01:
                return 'up'
            return 'rest'
        return 'down'
    # mode 1: line up (y, z) in the travel plane
    if ma.held is None:
        tgt = ma.obj[t_obj]
        tol = M.LOCK_ALIGN * 0.6
    else:
        tgt = np.array([0, SHELVES[t_shelf][1], SHELVES[t_shelf][2] + M.OBJ_H / 2 + 0.04])
        tol = 0.02
    d = tgt - seen
    d[0] = 0.0
    if np.abs(d[1:]).max() < tol:
        return 'rest'
    want, i = axis_toward(d)
    if abs(d[i]) < LEAD and est not in (None, 'rest'):
        return 'rest'                                  # let go early; stopped short: nudge again next step
    return want


def trial(e, rng):
    ma = M.ModeAssist(OBJ, SHELVES)
    col = M.Collisions(ma)
    t_obj = int(rng.integers(3))
    free = [k for k in range(len(SHELVES))
            if all(np.linalg.norm(o[:2] - SHELVES[k][:2]) > 0.06 or abs(o[2] - (SHELVES[k][2] + M.OBJ_H / 2)) > 0.03
                   for o in OBJ)]
    t_shelf = int(rng.choice(free))
    dec = S.Decoder(S.SET5, e, rng)
    x = X0.copy()
    hist = [x.copy()] * (S.REACT + 1)
    refused = wrong_lock = bad_spot = 0
    last_lock = None
    for t in range(T_MAX):
        want = user(ma, hist[-1 - S.REACT], t_obj, t_shelf, dec.est)
        cmd = dec(want)
        xp = x.copy()
        v = ma.step(cmd if cmd != 'rest' else None, x)
        if '不能動' in ma.msg:
            refused += 1
        if ('邊緣' in ma.msg or '太靠近' in ma.msg) and ma.armed is False:
            bad_spot += 1
            ma.msg = ''
            ma.armed = True
        lock = (ma.phase, ma.goal, ma.shelf) if ma.m == 2 else None
        if lock != last_lock and lock is not None and lock[0] in ('pick', 'place'):
            if (lock[0] == 'pick' and lock[1] != t_obj) or (lock[0] == 'place' and lock[2] != t_shelf):
                wrong_lock += 1
        last_lock = lock
        x = x + v * M.DT
        col.check(x, xp)
        hist.append(x.copy())
        on = (ma.held is None and abs(ma.obj[t_obj][2] - (SHELVES[t_shelf][2] + M.OBJ_H / 2)) < 1e-6
              and ma.spot_ok(ma.obj[t_obj], t_shelf)[0] if False else
              ma.held is None and abs(ma.obj[t_obj][2] - (SHELVES[t_shelf][2] + M.OBJ_H / 2)) < 1e-6
              and abs(ma.obj[t_obj][0] - SHELVES[t_shelf][0]) <= M.SHELF_HX - M.EDGE + 1e-6
              and abs(ma.obj[t_obj][1] - SHELVES[t_shelf][1]) <= M.SHELF_HY - M.EDGE + 1e-6)
        if on and ma.m == 1:
            return True, (t + 1) * M.DT, col, refused, wrong_lock, bad_spot
    return False, T_MAX * M.DT, col, refused, wrong_lock, bad_spot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--trials', type=int, default=300)
    ap.add_argument('--out')
    a = ap.parse_args()
    E = S.window_errors()
    lines = []

    def p(s=''):
        print(s, flush=True)
        lines.append(s)

    p(f'two-mode pick-and-place (modes.py), {a.trials} trials per row, limit {T_MAX * M.DT:.0f} s')
    p('  e      success   time median (quartiles) s   collision steps (trials with any)   refused A/D per trial   '
      'refused put-downs   wrong locks per trial')
    kinds_all = {}
    for j, e in enumerate((0.0, 0.1, E['G5'], 0.2, E['G9'], 0.3)):
        rng = np.random.default_rng(5000 + j)
        res = [trial(e, rng) for _ in range(a.trials)]
        okk = np.array([r[0] for r in res])
        tm = np.array([r[1] for r in res if r[0]])
        cols = np.array([r[2].n for r in res])
        for r in res:
            for k_, v_ in r[2].kinds.items():
                kinds_all[(round(e, 3), k_)] = kinds_all.get((round(e, 3), k_), 0) + v_
        p(f'  {e:5.3f}  {100 * okk.mean():5.1f} %   {np.median(tm):5.1f} ({np.percentile(tm, 25):.1f}-{np.percentile(tm, 75):.1f})'
          f'              {cols.sum():5d} ({int((cols > 0).sum())})'
          f'                     {np.mean([r[3] for r in res]):5.2f}                 {np.mean([r[5] for r in res]):5.2f}'
          f'             {np.mean([r[4] for r in res]):5.2f}')
    p('collision steps by kind: ' + (str(kinds_all) if kinds_all else 'none'))
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, 'modes_sim.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
