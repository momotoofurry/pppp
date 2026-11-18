"""Does the assist help when the classifier makes mistakes? A simulated user picks one of 3 objects on a table
(report 35.57, 2026-11-18). No arm kinematics: the tool point moves with the commanded velocity (the arm controller's
job); 100 ms steps.

Decoder (per 100 ms window): the user's intended class is decoded correctly with probability 1 - e, otherwise as one
of the other classes of the set (Rest included) at random. The board's decision: a class is established after K = 3
equal windows and stays until another class is established (continuous control: hold = move, Rest = stop).
Window error e from our GrabMyo cross-day results (report 35.51, 4 sensors, full system acc_soft, mean of days 8 and
29): e9 = 1 - acc(G9), e5 = 1 - acc(G5). The errors are independent between windows (real errors come in runs, which
the K = 3 rule filters less well): optimistic for both conditions alike.

Simulated user (reacts to what it saw REACT steps ago):
  direct (A, 9 classes: 6 directions + gripper open / close + Rest): align y, z with the object (largest axis
     first), then forward / back, then the close gesture at the object, then up.
  assist (C, 5 classes + assist.py): push toward the object in y, z (largest axis); after the system locks a goal,
     keep holding; if the lock is on the wrong object, hold the opposite gesture to cancel; after the grasp, up.
Layout per trial: 3 objects at 3 different cells of y in {-0.25, 0, 0.25} m x z in {0.10, 0.30} m (the cell in line
with the start point, y 0 / z 0.30, is left out: there the user has no direction to show), depth x 0.65-0.80 m.
Start: tool at (0.50, 0, 0.30) (all reachable with the tool horizontal, checked with kin.py). Time limit 60 s.
Outcome: success (target grasped and lifted), wrong (another object grasped), timeout. Time = to the lift.

usage: python src/assist/assist_sim.py [--trials 300] [--out results/assist]
"""
import argparse
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assist as A  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
K, REACT, T_MAX = 3, 3, 600
SET9 = ['up', 'down', 'left', 'right', 'forward', 'back', 'grip_open', 'grip_close', 'rest']
SET5 = ['up', 'down', 'left', 'right', 'rest']
CELLS = [(y, z) for y in (-0.25, 0.0, 0.25) for z in (0.10, 0.30) if not (y == 0.0 and z == 0.30)]
X0 = np.array([0.50, 0.0, 0.30])
TOL = 0.015                                    # the user's "close enough" per axis, m
LEAD = A.V_MAX * A.DT * (REACT + K) * 0.6     # where the user lets go before the end of an axis, m


def window_errors():
    txt = open(os.path.join(ROOT, 'results', 'grabmyo', 'combined.txt'), encoding='utf-8').read()
    e = {}
    for s in ('G9', 'G5'):
        m = re.search(rf'^4ch\s+{s} \(n \d+\): .*?\n(?:.*\n)*?\s+acc_soft\s+[\d.]+ /\s+([\d.]+) /\s+([\d.]+)', txt, re.M)
        e[s] = 1 - (float(m.group(1)) + float(m.group(2))) / 200
    return e


class Decoder:
    def __init__(self, classes, e, rng):
        self.classes, self.e, self.rng = classes, e, rng
        self.run_c, self.run_n, self.est = None, 0, 'rest'

    def __call__(self, intended):
        c = intended
        if self.rng.random() < self.e:
            c = self.rng.choice([x for x in self.classes if x != intended])
        if c == self.run_c:
            self.run_n += 1
        else:
            self.run_c, self.run_n = c, 1
        if self.run_n >= K:
            self.est = c
        return self.est


def axis_cmd(d, axes):
    """largest component of d among the given axes (0 x, 1 y, 2 z) -> direction name"""
    i = max(axes, key=lambda a: abs(d[a]))
    names = {0: ('forward', 'back'), 1: ('left', 'right'), 2: ('up', 'down')}[i]
    return names[0] if d[i] > 0 else names[1]


def user_assist(sa, obj, tgt, seen, held):
    """the simulated user with the assist (also drives the RViz demo, assist_ros.py) -> (wanted class, held)"""
    if sa.state == 'grasped':
        want = 'up'
    elif sa.state == 'approach':
        if sa.goal != tgt:
            # the arm heads for the wrong object: push the way that separates the target from it
            d = obj[tgt] - obj[sa.goal]
            want = axis_cmd(d, (1, 2)) if np.abs(d[1:]).max() > 0.01 else \
                {'up': 'down', 'down': 'up', 'left': 'right', 'right': 'left'}[sa.lock_cmd]
        else:
            want = held if held != 'rest' else sa.lock_cmd
    else:
        d = obj[tgt] + A.PRE - seen
        want = axis_cmd(d, (1, 2)) if np.linalg.norm(d[1:]) > 0.01 else (held if held != 'rest' else 'up')
    if want in ('up', 'down', 'left', 'right') and sa.state != 'approach':
        held = want
    return want, held


def trial(cond, e, rng, log=None):
    cells = rng.choice(len(CELLS), 3, replace=False)
    obj = np.array([[rng.uniform(0.65, 0.80), CELLS[c][0], CELLS[c][1]] for c in cells])
    tgt = int(rng.integers(3))
    x = X0.copy()
    hist = [x.copy()] * (REACT + 1)
    if cond == 'direct':
        dec = Decoder(SET9, e, rng)
        grip, lift_from, last = 0.0, None, 'rest'
        for t in range(T_MAX):
            seen = hist[-1 - REACT]
            d = obj[tgt] - seen
            # the user anticipates the stopping distance (their own delay + the K-window decision): lets go of the
            # gesture LEAD before the axis is done
            if lift_from is not None:
                want = 'up'
            elif np.abs(d).max() <= TOL:
                # stop first, then close (closing while the arm still slides misses the object)
                want = 'grip_close' if dec.est in ('rest', 'grip_close', 'grip_open') else 'rest'
            else:
                axes = (1, 2) if np.abs(d[1:]).max() > TOL else (0,)
                i = max(axes, key=lambda a_: abs(d[a_]))
                want = axis_cmd(d, axes) if abs(d[i]) > LEAD else 'rest'
                if want == 'rest' and dec.est == 'rest':
                    want = axis_cmd(d, axes)          # stopped short: nudge again
            cmd = dec(want)
            if log is not None:
                log.append((t, want, cmd, np.round(x, 3).tolist(), np.round(obj[tgt], 3).tolist()))
            if cmd == 'grip_close' and grip == 0.0:
                near = np.linalg.norm(obj - x, axis=1)
                k = int(np.argmin(near))
                if near[k] < 0.03:                   # closing away from every object = a missed grasp (stays open)
                    grip = 1.0
                    if k != tgt:
                        return 'wrong', (t + 1) * A.DT
                    lift_from = x[2]
            elif cmd == 'grip_open':
                grip, lift_from = 0.0, None
            v = A.V_MAX * np.array(A.DIRS[cmd], float) if cmd in A.DIRS else np.zeros(3)
            x = x + v * A.DT
            hist.append(x.copy())
            if lift_from is not None and x[2] - lift_from >= A.LIFT:
                return 'success', (t + 1) * A.DT
        return 'timeout', T_MAX * A.DT
    dec = Decoder(SET5, e, rng)
    sa = A.Assist(obj, assist=True)
    held = 'rest'
    for t in range(T_MAX):
        seen = hist[-1 - REACT]
        want, held = user_assist(sa, obj, tgt, seen, held)
        cmd = dec(want)
        if log is not None:
            log.append((t, want, cmd, sa.state, sa.goal, np.round(sa.probs(), 2).tolist(), np.round(x, 3).tolist(), np.round(obj[tgt], 3).tolist()))
        v = sa.step(cmd if cmd != 'rest' else None, x)
        if sa.state == 'grasped' and sa.lift_from is not None and sa.goal != tgt:
            return 'wrong', (t + 1) * A.DT
        x = x + v * A.DT
        hist.append(x.copy())
        if sa.state == 'done':
            return ('success' if sa.goal == tgt else 'wrong'), (t + 1) * A.DT
    return 'timeout', T_MAX * A.DT


def run(cond, e, n, seed):
    rng = np.random.default_rng(seed)
    out = [trial(cond, e, rng) for _ in range(n)]
    res = np.array([o for o, _ in out])
    tm = np.array([t for o, t in out if o == 'success'])
    return dict(success=100 * np.mean(res == 'success'), wrong=100 * np.mean(res == 'wrong'),
                timeout=100 * np.mean(res == 'timeout'), t_med=float(np.median(tm)) if len(tm) else np.nan,
                t_q=(float(np.percentile(tm, 25)), float(np.percentile(tm, 75))) if len(tm) else (np.nan, np.nan))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--trials', type=int, default=300)
    ap.add_argument('--out')
    a = ap.parse_args()
    E = window_errors()
    lines = []

    def p(s=''):
        print(s, flush=True)
        lines.append(s)

    p(f'window error from GrabMyo 4ch acc_soft, days 8 + 29: 9 classes {E["G9"]:.3f}, 5 classes {E["G5"]:.3f}')
    p(f'{a.trials} trials per row, 3 objects, limit {T_MAX * A.DT:.0f} s')
    p('condition                         e      success  wrong  timeout   time median (quartiles), s')
    rows = [('A  direct, 9 classes', 'direct', E['G9']), ('C  assist, 5 classes', 'assist', E['G5']),
            ('A  direct, same e as C', 'direct', E['G5']), ('C  assist, same e as A', 'assist', E['G9']),
            ('A  direct, no errors', 'direct', 0.0), ('C  assist, no errors', 'assist', 0.0)]
    for i, (name, cond, e) in enumerate(rows):
        r = run(cond, e, a.trials, 1000 + i)
        p(f'{name:32s} {e:5.3f}  {r["success"]:6.1f} % {r["wrong"]:5.1f} % {r["timeout"]:6.1f} %   '
          f'{r["t_med"]:5.1f} ({r["t_q"][0]:.1f}-{r["t_q"][1]:.1f})')
    p('\nsweep of the window error (both conditions at the same e):')
    p('  e      direct success / time      assist success / time')
    for j, e in enumerate((0.0, 0.1, 0.2, 0.3, 0.4)):
        d = run('direct', e, a.trials, 2000 + j)
        s = run('assist', e, a.trials, 3000 + j)
        p(f'  {e:.1f}   {d["success"]:5.1f} % / {d["t_med"]:5.1f} s      {s["success"]:5.1f} % / {s["t_med"]:5.1f} s')
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, 'assist_sim.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
