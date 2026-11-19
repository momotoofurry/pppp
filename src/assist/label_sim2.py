"""Hindsight task labels under harder user behaviour, and a stricter rule (report 35.70).

35.65 tested two users (dominant axis first / one axis first). Here, with the 35.68 controller (relax after a switch,
mix steering):
  users
    dominant    35.63's simulated user
    any-order   one axis first, then the other (35.65)
    overshoot   lets go only when it SEES the target reached (no early release): with the reaction time and the
                decoder's K windows the arm passes the target, then the user pulls back
    detour      first goes 8 cm in a random direction (around something), then to the target
    hesitant    pauses 0.3-1 s at random (2 % chance per step while moving)
    mind-change heads for another object first, switches to the real one 5 cm before reaching it
  rules (all from what the system logged; never from the user's intent)
    geometry, motion, agree   35.65
    cmd      the decoder's established command that window (not the arm's motion: in mode 1 the assist bends the
             motion, so the motion can point along the assist instead of the user's command), kept if it moves toward
             the point the trial confirmed (by > 2 mm along its axis). Windows where the command changes within the
             next K - 1 windows are left out (the user had already switched: decoder delay, also before reversals,
             e.g. after an overshoot). Rest: the established Rest at the lock / grasp / put-down point, the
             'relax first' prompt after a mode switch (a cue), and the automatic lowering.
    agree2   geometry and cmd give the same class
  trial-level checks (both new rules): a put-down within 3 cm (3-D; 35.71 fixed a 2-D check that took a shelf right
    above the pick-up spot for an undo) of where the object was picked up counts as an undo:
    the trial gives no labels (the simulated users never do this; the rule is for the experiment)
  MCU buffer: labels need the windows since the last confirmation; with a buffer of BUF windows before each grasp /
    put-down the older windows are lost: reported as labelled windows with the buffer.

usage: python src/assist/label_sim2.py [--trials 300] [--out results/assist]
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assist as A  # noqa: E402
import assist_sim as S  # noqa: E402
import label_sim as LS  # noqa: E402
import modes as M  # noqa: E402
import modes_sim as MS  # noqa: E402

CLASSES = S.SET5
USERS = ['dominant', 'any-order', 'overshoot', 'detour', 'hesitant', 'mind-change']
BUF = 100                    # windows (sim step 100 ms = 10 s; with the planned 50 ms step: 200 windows, about 31 KB)


class User:
    def __init__(self, kind, rng, t_obj):
        self.kind, self.rng = kind, rng
        self.order = int(rng.integers(1, 3)) if kind != 'dominant' else None
        self.pause = 0
        self.detour = None
        if kind == 'detour':
            ax = int(rng.integers(1, 3))
            self.detour = [ax, float(rng.choice([-1.0, 1.0])), None]      # axis, sign, start
        self.decoy = int(rng.choice([g for g in range(len(MS.OBJ)) if g != t_obj])) if kind == 'mind-change' else None

    def __call__(self, ma, seen, t_obj, t_shelf, est):
        if ma.m == 2 or ma.lowering is not None or ma.wait_release:
            want = MS.user(ma, seen, t_obj, t_shelf, est)
            return self._hesitate(want)
        if self.detour is not None and ma.held is None:
            ax, sg, x0 = self.detour
            if x0 is None:
                self.detour[2] = x0 = seen.copy()
            if abs(seen[ax] - x0[ax]) < 0.08:
                u = np.zeros(3)
                u[ax] = sg
                return S.axis_cmd(u, (ax,))
            self.detour = None
        if ma.held is None:
            tgt, tol = ma.obj[t_obj], M.LOCK_ALIGN * 0.6
            if self.decoy is not None:
                dd = ma.obj[self.decoy] + A.PRE - seen
                if np.linalg.norm(dd[1:]) < 0.05:
                    self.decoy = None
                else:
                    tgt = ma.obj[self.decoy]
        else:
            tgt = np.array([0, MS.SHELVES[t_shelf][1], MS.SHELVES[t_shelf][2] + M.OBJ_H / 2 + 0.04])
            tol = 0.02
        d = tgt - seen
        d[0] = 0.0
        if np.abs(d[1:]).max() < tol:
            return 'rest'
        if self.order is None:
            i = 1 if abs(d[1]) >= abs(d[2]) else 2
        else:
            i = self.order if abs(d[self.order]) >= tol else 3 - self.order
        want = S.axis_cmd(d, (i,))
        if self.kind != 'overshoot' and abs(d[i]) < MS.LEAD and est not in (None, 'rest'):
            want = 'rest'
        return self._hesitate(want)

    def _hesitate(self, want):
        if self.kind != 'hesitant':
            return want
        if self.pause > 0:
            self.pause -= 1
            return 'rest'
        if want != 'rest' and self.rng.random() < 0.02:
            self.pause = int(self.rng.integers(3, 11))
            return 'rest'
        return want


def trial(e, rng, kind):
    ma = M.ModeAssist(MS.OBJ, MS.SHELVES)
    t_obj = int(rng.integers(3))
    free = [k for k in range(len(MS.SHELVES))
            if all(np.linalg.norm(o[:2] - MS.SHELVES[k][:2]) > 0.06
                   or abs(o[2] - (MS.SHELVES[k][2] + M.OBJ_H / 2)) > 0.03 for o in MS.OBJ)]
    t_shelf = int(rng.choice(free))
    user = User(kind, rng, t_obj)
    dec = LS.RawDecoder(S.SET5, e, rng)
    x = MS.X0.copy()
    hist = [x.copy()] * (S.REACT + 1)
    rec = []
    pick_pos = None
    for t in range(MS.T_MAX):
        seen = hist[-1 - S.REACT]
        want = user(ma, seen, t_obj, t_shelf, dec.est)
        cmd = dec(want)
        r = dict(want=want, raw=dec.raw, cmd=cmd, m=ma.m, phase=ma.phase, x=x.copy(), held=ma.held,
                 lowering=ma.lowering is not None, wait=ma.wait_release,
                 lock=(ma.phase, ma.goal, ma.shelf) if ma.m == 2 else None)
        held0 = ma.held
        if held0 is None and ma.phase == 'pick' and ma.goal is not None:
            pick_pos = ma.obj[ma.goal].copy()
        v = ma.step(cmd if cmd != 'rest' else None, x)
        if ('邊緣' in ma.msg or '太靠近' in ma.msg) and ma.armed is False:
            ma.msg, ma.armed = '', True
        r['grasp'] = held0 is None and ma.held is not None
        r['put'] = held0 is not None and ma.held is None
        if r['grasp']:
            r['pick_pos'] = pick_pos
        rec.append(r)
        x = x + v * M.DT
        hist.append(x.copy())
        on = (ma.held is None and abs(ma.obj[t_obj][2] - (MS.SHELVES[t_shelf][2] + M.OBJ_H / 2)) < 1e-6
              and abs(ma.obj[t_obj][0] - MS.SHELVES[t_shelf][0]) <= M.SHELF_HX - M.EDGE + 1e-6
              and abs(ma.obj[t_obj][1] - MS.SHELVES[t_shelf][1]) <= M.SHELF_HY - M.EDGE + 1e-6)
        if on and ma.m == 1:
            return True, rec, ma
    return False, rec, ma


def _events(rec):
    tg = next(i for i, r in enumerate(rec) if r['grasp'])
    tp = next(i for i, r in enumerate(rec) if r['put'])

    def last_lock_start(end, phase):
        i = end
        while i > 0 and rec[i - 1]['m'] == 2 and rec[i - 1]['phase'] == phase:
            i -= 1
        return i
    a = last_lock_start(tg, 'pick')
    b = last_lock_start(tp, 'place')
    tl = next((i for i in range(b, tp + 1) if rec[i]['lowering']), tp)
    return tg, tp, a, b, tl


def undo(rec):
    tg, tp, *_ = _events(rec)
    p0 = rec[tg].get('pick_pos')
    # 3-D: a shelf directly above / below the pick-up spot is not an undo (35.71: shelf 4 is above shelf 0)
    return p0 is not None and np.linalg.norm(rec[tp]['x'] - p0) < 0.03


def hindsight_cmd(rec, ma, tail_n=None):
    tail_n = S.K - 1 if tail_n is None else tail_n
    if undo(rec):
        return [None] * len(rec)
    tg, tp, a, b, tl = _events(rec)
    lock_pt = {0: rec[a]['x'], 1: rec[b]['x']}
    obj_pt, put_pt = rec[tg]['x'], rec[tl]['x']
    cmds = [r['cmd'] for r in rec]
    out = []
    for i, r in enumerate(rec):
        c = cmds[i]
        tail = c != 'rest' and any(cc != c for cc in cmds[i + 1:i + 1 + tail_n])   # decoder delay: user already switched
        lab = None
        if r['lowering'] or (r['wait'] and c == 'rest'):
            lab = 'rest'
        elif tail:
            lab = None
        elif r['m'] == 1 and i < tp and (i < a or tg <= i < b):
            d = lock_pt[0 if i < tg else 1] - r['x']
            if c == 'rest':
                lab = 'rest' if np.abs(d[1:]).max() < LS.REST_R else None
            elif c in A.DIRS:
                u = np.array(A.DIRS[c], float)
                lab = c if u @ d > 0.002 else None
        elif r['m'] == 2 and r['phase'] == 'pick' and a <= i < tg:
            near = np.linalg.norm(obj_pt - r['x']) < M.GRASP_TOL
            lab = 'rest' if (c == 'rest' and near) else ('up' if (c == 'up' and not near) else None)
        elif r['m'] == 2 and r['phase'] == 'place' and b <= i < tl:
            near = np.linalg.norm(put_pt - r['x']) < M.GRASP_TOL
            lab = 'rest' if (c == 'rest' and near) else ('up' if (c == 'up' and not near) else None)
        elif r['m'] == 2 and r['phase'] == 'out' and i > tg and c == 'down':
            lab = 'down'
        out.append(lab)
    return out


def agree2(rec, ma, tail_n=None):
    g, c = LS.hindsight(rec, ma), hindsight_cmd(rec, ma, tail_n)
    return [x if x == y else None for x, y in zip(g, c)]


def buffered(rec, labs, buf=BUF):
    """labels that survive a buffer of BUF windows before each confirmation (grasp, put-down)"""
    tg, tp, *_ = _events(rec)
    keep = [False] * len(rec)
    for ev in (tg, tp):
        for i in range(max(0, ev - buf), ev + 1):
            keep[i] = True
    # windows after the put-down (backing out) are labelled at the end of the trial: kept
    for i in range(tp, len(rec)):
        keep[i] = True
    return [l if k else None for l, k in zip(labs, keep)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--trials', type=int, default=300)
    ap.add_argument('--out')
    a = ap.parse_args()
    E = S.window_errors()
    rules = (('geometry', LS.hindsight), ('motion', LS.hindsight_motion),
             ('agree', lambda r, m: [x if x == y else None for x, y in zip(LS.hindsight(r, m), LS.hindsight_motion(r, m))]),
             ('cmd', hindsight_cmd), ('agree2', agree2),
             ('agree2_t4', lambda r, m: agree2(r, m, 4)), ('agree2_t6', lambda r, m: agree2(r, m, 6)))
    BUFS = (100, 200, 300)
    lines, mats = [], {}

    def p(s=''):
        print(s, flush=True)
        lines.append(s)

    p(f'hindsight task labels, harder users and the stricter rules (label_sim2.py), {a.trials} trials per row')
    p('  user         e      success | rule       labelled  error   | buffer 100 / 200 / 300 windows (10 / 20 / 30 s): labelled')
    for ui, kind in enumerate(USERS):
        for j, e in enumerate((E['G5'], E['G9'])):
            rng = np.random.default_rng(9000 + 100 * ui + j)
            st = {rn: dict(lab=0, wrong=0, blab={b: 0 for b in BUFS}, mat={c: {l: 0 for l in CLASSES + ['none']} for c in CLASSES})
                  for rn, _ in rules}
            n_all = succ = 0
            for _ in range(a.trials):
                ok, rec, ma = trial(e, rng, kind)
                if not ok:
                    continue
                succ += 1
                n_all += len(rec)
                for rn, fn in rules:
                    s = st[rn]
                    labs = fn(rec, ma)
                    for r, l in zip(rec, labs):
                        s['mat'][r['want']][l if l is not None else 'none'] += 1
                        if l is not None:
                            s['lab'] += 1
                            s['wrong'] += l != r['want']
                    for b in BUFS:
                        s['blab'][b] += sum(lb is not None for lb in buffered(rec, labs, b))
            for k, (rn, _) in enumerate(rules):
                s = st[rn]
                head = f'  {kind:11s}  {e:5.3f}  {100 * succ / a.trials:5.1f} %' if k == 0 else ' ' * 30
                p(f'{head} | {rn:10s} {100 * s["lab"] / n_all:5.1f} %  {100 * s["wrong"] / max(s["lab"], 1):5.2f} % | '
                  + ' / '.join(f'{100 * s["blab"][b] / n_all:5.1f} %' for b in BUFS))
                mats[f'{rn}|{kind}|{e:.3f}'] = s['mat']
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        open(os.path.join(a.out, 'label_sim2.txt'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
        json.dump(mats, open(os.path.join(a.out, 'label_sim2_confusion.json'), 'w', encoding='utf-8'), indent=1)


if __name__ == '__main__':
    main()
