"""Task labels from the two-mode assist, in simulation (report 35.65).

Question: in use, the system never sees which gesture the user meant, only what happened. After a trial ends in a
confirmed grasp and put-down, can it label the windows of that trial in hindsight, and how often is such a label wrong?
That error rate is the 'wrong context' rate of 35.55 (soft labels safe, hard labels collapse at >= 10 %).

Simulation: modes_sim.py's pick-and-place (same scene, simulated user, 5-class decoder with window error e, K = 3).
Two user types:
  dominant  - in mode 1 always moves along the larger of the (y, z) offsets first (as modes_sim.py);
  any-order - per trial picks y-first or z-first, finishes that axis, then the other (people differ).
What the system knows afterwards (no access to the user's intent): its own mode / phase / position per window, where
it locked 'pick' and 'place' (the last lock before the grasp / the put-down), the grasp and put-down events.

Hindsight rule per window (successful trials only; anything else -> no label):
  mode 1, before the grasp: offset d = (pick lock point - arm) in (y, z);
  mode 1, holding:          offset d = (place lock point - arm) in (y, z);
    |d| < REST_R in both                         -> rest (the user stopped there to lock)
    larger component > MIN_D and >= RATIO x the other -> that direction
    otherwise (diagonal, near the end of an axis) -> no label
  mode 2 pick / place, the lock that succeeded: farther than GRASP_TOL from the object / put-down point -> forward
    (= the 'up' gesture, W), within it -> rest; while the system lowers the object -> rest
  mode 2 out after the grasp / put-down -> back (= the 'down' gesture, S)
  mode 2 locks that were cancelled (wrong lock), mode 2 free -> no label
Compared against the gesture the simulated user actually made (its 'want' that window).
Baseline: self-training labels = the decoder's own window output (wrong with probability e by construction).

usage: python src/assist/label_sim.py [--trials 300] [--out results/assist]
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assist_sim as S  # noqa: E402
import modes as M  # noqa: E402
import modes_sim as MS  # noqa: E402

REST_R, MIN_D, RATIO = 0.01, 0.015, 2.0
CLASSES = S.SET5


class RawDecoder(S.Decoder):
    """the board's decoder; also keeps the window's own (raw) output, the self-training label"""
    def __call__(self, intended):
        c = intended
        if self.rng.random() < self.e:
            c = self.rng.choice([x for x in self.classes if x != intended])
        self.raw = c
        if c == self.run_c:
            self.run_n += 1
        else:
            self.run_c, self.run_n = c, 1
        if self.run_n >= S.K:
            self.est = c
        return self.est


def user_any(ma, seen, t_obj, t_shelf, est, order):
    """modes_sim.user, but in mode 1 one axis first (order 1 = y, 2 = z), then the other"""
    if ma.m == 2 or ma.lowering is not None:
        return MS.user(ma, seen, t_obj, t_shelf, est)
    if ma.held is None:
        tgt, tol = ma.obj[t_obj], M.LOCK_ALIGN * 0.6
    else:
        tgt = np.array([0, MS.SHELVES[t_shelf][1], MS.SHELVES[t_shelf][2] + M.OBJ_H / 2 + 0.04])
        tol = 0.02
    d = tgt - seen
    d[0] = 0.0
    if np.abs(d[1:]).max() < tol:
        return 'rest'
    i = order if abs(d[order]) >= tol else 3 - order
    want = S.axis_cmd(d, (i,))
    if abs(d[i]) < MS.LEAD and est not in (None, 'rest'):
        return 'rest'
    return want


def trial(e, rng, kind):
    ma = M.ModeAssist(MS.OBJ, MS.SHELVES)
    t_obj = int(rng.integers(3))
    free = [k for k in range(len(MS.SHELVES))
            if all(np.linalg.norm(o[:2] - MS.SHELVES[k][:2]) > 0.06
                   or abs(o[2] - (MS.SHELVES[k][2] + M.OBJ_H / 2)) > 0.03 for o in MS.OBJ)]
    t_shelf = int(rng.choice(free))
    order = int(rng.integers(1, 3))
    dec = RawDecoder(S.SET5, e, rng)
    x = MS.X0.copy()
    hist = [x.copy()] * (S.REACT + 1)
    rec = []                                           # per window: what the system saw, and the truth
    for t in range(MS.T_MAX):
        seen = hist[-1 - S.REACT]
        want = (MS.user(ma, seen, t_obj, t_shelf, dec.est) if kind == 'dominant'
                else user_any(ma, seen, t_obj, t_shelf, dec.est, order))
        cmd = dec(want)
        r = dict(want=want, raw=dec.raw, m=ma.m, phase=ma.phase, x=x.copy(), held=ma.held,
                 lowering=ma.lowering is not None, lock=(ma.phase, ma.goal, ma.shelf) if ma.m == 2 else None)
        held0 = ma.held
        v = ma.step(cmd if cmd != 'rest' else None, x)
        if ('邊緣' in ma.msg or '太靠近' in ma.msg) and ma.armed is False:
            ma.msg, ma.armed = '', True
        r['grasp'] = held0 is None and ma.held is not None
        r['put'] = held0 is not None and ma.held is None
        rec.append(r)
        x = x + v * M.DT
        hist.append(x.copy())
        on = (ma.held is None and abs(ma.obj[t_obj][2] - (MS.SHELVES[t_shelf][2] + M.OBJ_H / 2)) < 1e-6
              and abs(ma.obj[t_obj][0] - MS.SHELVES[t_shelf][0]) <= M.SHELF_HX - M.EDGE + 1e-6
              and abs(ma.obj[t_obj][1] - MS.SHELVES[t_shelf][1]) <= M.SHELF_HY - M.EDGE + 1e-6)
        if on and ma.m == 1:
            return True, rec, ma
    return False, rec, ma


STILL = 0.001                          # m per window: the arm did not move


def hindsight_motion(rec, ma):
    """rule 'motion': the arm's own movement that window, kept only when it went toward the point the trial confirmed
    (the lock point in mode 1, the grasp / put-down point in mode 2); still arm -> rest only where the user had to
    stop (at the lock point, at the grasp / put-down point). Never uses 'want'."""
    tg = next(i for i, r in enumerate(rec) if r['grasp'])
    tp = next(i for i, r in enumerate(rec) if r['put'])

    def last_lock_start(end, phase):
        i = end
        while i > 0 and rec[i - 1]['m'] == 2 and rec[i - 1]['phase'] == phase:
            i -= 1
        return i
    a = last_lock_start(tg, 'pick')
    b = last_lock_start(tp, 'place')
    lock_pt = {0: rec[a]['x'], 1: rec[b]['x']}
    tl = next((i for i in range(b, tp + 1) if rec[i]['lowering']), tp)
    obj_pt, put_pt = rec[tg]['x'], rec[tl]['x']
    mv = [np.linalg.norm((rec[i + 1]['x'] if i + 1 < len(rec) else r['x']) - r['x']) >= STILL for i, r in enumerate(rec)]
    out = []
    for i, r in enumerate(rec):
        lab = None
        disp = (rec[i + 1]['x'] if i + 1 < len(rec) else r['x']) - r['x']
        still = not mv[i]
        # the decoder needs K equal windows to change its output: the arm keeps moving K - 1 windows after the user let
        # go. Moving windows just before a stop are therefore ambiguous -> no label
        if not still and not all(mv[i + 1:i + S.K]):
            out.append(None)
            continue
        if r['lowering']:
            lab = 'rest'
        elif r['m'] == 1 and i < tp and (i < a or tg <= i < b):
            d = lock_pt[0 if i < tg else 1] - r['x']
            if still:
                lab = 'rest' if np.abs(d[1:]).max() < REST_R else None
            else:
                ax = 1 if abs(disp[1]) >= abs(disp[2]) else 2
                if abs(disp[ax]) >= RATIO * abs(disp[3 - ax]) and np.sign(disp[ax]) == np.sign(d[ax]) and abs(d[ax]) > 0.002:
                    lab = S.axis_cmd(disp, (ax,))
        elif r['m'] == 2 and r['phase'] == 'pick' and a <= i < tg:
            if still:
                lab = 'rest' if np.linalg.norm(obj_pt - r['x']) < M.GRASP_TOL else None
            elif disp[0] > 0:
                lab = 'up'
        elif r['m'] == 2 and r['phase'] == 'place' and b <= i < tl:
            if still:
                lab = 'rest' if np.linalg.norm(put_pt - r['x']) < M.GRASP_TOL else None
            elif disp[0] > 0:
                lab = 'up'
        elif r['m'] == 2 and r['phase'] == 'out' and i > tg and not still and disp[0] < 0:
            lab = 'down'
        out.append(lab)
    return out


def hindsight(rec, ma):
    """rule 'geometry': labels from where the arm was relative to the confirmed points (never from 'want')"""
    tg = next(i for i, r in enumerate(rec) if r['grasp'])
    tp = next(i for i, r in enumerate(rec) if r['put'])
    # the lock that succeeded: start of the last mode-2 pick (place) run before the grasp (put-down)
    def last_lock_start(end, phase):
        i = end
        while i > 0 and rec[i - 1]['m'] == 2 and rec[i - 1]['phase'] == phase:
            i -= 1
        return i
    a = last_lock_start(tg, 'pick')
    b = last_lock_start(tp, 'place')
    lock_pt = {0: rec[a]['x'], 1: rec[b]['x']}
    tl = next((i for i in range(b, tp + 1) if rec[i]['lowering']), tp)    # put-down point: before the lowering
    obj_pt, put_pt = rec[tg]['x'], rec[tl]['x']
    out = []
    for i, r in enumerate(rec):
        lab = None
        if r['lowering']:
            lab = 'rest'
        elif r['m'] == 1 and i < tp:
            d = lock_pt[0 if i < tg else 1] - r['x']
            dy, dz = d[1], d[2]
            big, small = max(abs(dy), abs(dz)), min(abs(dy), abs(dz))
            if big < REST_R:
                lab = 'rest' if (i < a or tg <= i < b) else None
            elif big > MIN_D and big >= RATIO * small:
                lab = S.axis_cmd(np.array([0, dy, dz]), (1, 2))
        elif r['m'] == 2 and r['phase'] == 'pick' and a <= i < tg:
            lab = 'up' if np.linalg.norm(obj_pt - r['x']) > M.GRASP_TOL else 'rest'
        elif r['m'] == 2 and r['phase'] == 'place' and b <= i < tp:
            lab = 'up' if np.linalg.norm(put_pt - r['x']) > M.GRASP_TOL else 'rest'
        elif r['m'] == 2 and r['phase'] == 'out' and i > tg:
            lab = 'down'
        out.append(lab)
    return out


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

    p(f'task labels in hindsight from the two-mode assist, {a.trials} trials per row (label_sim.py)')
    p(f'rule: rest within {100 * REST_R:.0f} cm of the lock point, a direction when its offset > {100 * MIN_D:.1f} cm '
      f'and >= {RATIO:.0f}x the other; only successful trials are labelled')
    p('  rule      user       e      success  labelled windows  task-label error  self-training error   '
      'task-label error by true class (up / down / left / right / rest)')
    detail = {}
    def agree(rec, ma):                 # label only where the two rules give the same class
        return [g if g == m else None for g, m in zip(hindsight(rec, ma), hindsight_motion(rec, ma))]
    rules = (('geometry', hindsight), ('motion', hindsight_motion), ('agree', agree))
    for kind in ('dominant', 'any-order'):
        for j, e in enumerate((0.0, 0.1, E['G5'], 0.2, E['G9'], 0.3)):
            rng = np.random.default_rng(7000 + j + (100 if kind != 'dominant' else 0))
            st = {rn: dict(n_lab=0, n_wrong=0, byc={c: [0, 0] for c in CLASSES}, conf={}) for rn, _ in rules}
            n_all = n_self = succ = 0
            for _ in range(a.trials):
                ok, rec, ma = trial(e, rng, kind)
                if not ok:
                    continue
                succ += 1
                n_all += len(rec)
                n_self += sum(r['raw'] != r['want'] for r in rec)
                for rn, fn in rules:
                    s = st[rn]
                    for r, lab in zip(rec, fn(rec, ma)):
                        if lab is None:
                            continue
                        s['n_lab'] += 1
                        s['byc'][r['want']][0] += 1
                        if lab != r['want']:
                            s['n_wrong'] += 1
                            s['byc'][r['want']][1] += 1
                            s['conf'][(r['want'], lab)] = s['conf'].get((r['want'], lab), 0) + 1
            for rn, _ in rules:
                s = st[rn]
                per = ' / '.join(f'{100 * w / n:4.1f}' if n else '  - ' for n, w in (s['byc'][c] for c in CLASSES))
                p(f'  {rn:8s}  {kind:9s}  {e:5.3f}  {100 * succ / a.trials:5.1f} %   {100 * s["n_lab"] / n_all:5.1f} %'
                  f'          {100 * s["n_wrong"] / max(s["n_lab"], 1):5.2f} %          {100 * n_self / n_all:5.2f} %'
                  f'             {per}')
                detail[(rn, kind, round(e, 3))] = sorted(s['conf'].items(), key=lambda kv: -kv[1])[:4]
    p('most common task-label mistakes (true -> label: windows):')
    for k, v in detail.items():
        p(f'  {k[0]:8s} {k[1]:9s} e {k[2]:5.3f}: ' +', '.join(f'{t}->{l}: {n}' for (t, l), n in v))
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, 'label_sim.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
