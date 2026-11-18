"""Which labels of use add to the board's per-donning accumulation, across days? GrabMyo days 1 / 8 / 29, 43 people
(report 35.55, 2026-11-18). The two baselines a reviewer asks for first:
  self-training   the classifier's own decided command as a hard label (confidence = the board's run of K_DC equal
                  predictions); the standard unsupervised adaptation
  CIIL-like       context-informed relabelling (JNER 2024): if the decided command is goal-appropriate keep it,
                  otherwise relabel to the goal-appropriate class the model scores highest; hard label
against the board's soft labels (Model.soft: prior from the task x exp(beta x mean discriminant)).

Same data, features, model, decision and day protocol as grabmyo_crossday.py (4ch: every other ring-1 electrode
repeated, mean of the two sets; cued pass = trial 1, task = trials 2-4 of each command, test = trials 5-7). All
conditions carry the running sums across days (acc, the board's accumulation); hard labels forget with the same
DECAY as soft ones.
Context given to the labeller, per task trial (the true gesture g):
  1   one goal-appropriate command: g (the task names it; what the self-test's task segments give)
  2   two goal-appropriate commands: g and one other command at random (a goal up-left: up and left both fit; what
      shared-autonomy goal inference gives for a target off the axes)
  30  one command, but 30 % of the trials name a wrong one (goal inference wrong)
Conditions: cue (daily short calibration, reference), acc, self, ciil1, soft1, ciil2, soft2, ciil30, soft30.
Reported: days 8 + 29 mean, difference vs acc and vs self, better in n / 43.

usage: python src/grabmyo_labels.py --dir /grabmyo [--subjects 1-43] [--jobs 8] [--out results/grabmyo]
"""
import argparse
import os
import sys

import numpy as np
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grabmyo_crossday as GC  # noqa: E402
import selftest9_analysis as S9  # noqa: E402

REST, SETS = GC.REST, GC.SETS
CONDS = ['cue', 'acc', 'self', 'ciil1', 'soft1', 'ciil2', 'soft2', 'ciil30', 'soft30']
RATES, EPSS = (0, 10, 30, 50), (5, 15, 30, 50)
CORR = ['cue', 'acc', 'self', 'ciil1', 'soft1', 'xh', 'xs15', 'xcal']
SWEEP = ['cue', 'acc'] + [f'h{r}' for r in RATES] + [f's{r}e{e}' for r in RATES for e in EPSS]


def hard(mdl, R, k_cls):
    Zq = mdl.z(R)
    k = mdl.classes.index(k_cls)
    mdl.G = S9.DECAY * mdl.G + Zq.T @ Zq
    mdl.s = S9.DECAY * mdl.s
    mdl.n = S9.DECAY * mdl.n
    mdl.s[k] += Zq.sum(0)
    mdl.n[k] += len(Zq)
    mdl.fit()


def soft_set(mdl, R, ok, eps=None):
    """Model.soft with the prior's 1 - eps spread over the goal-appropriate commands ok (eps: the board's EPS)"""
    eps = S9.EPS if eps is None else eps
    cls = mdl.classes
    others = [c for c in cls if c not in ok and c != REST]
    prior = np.array([(1 - eps) / len(ok) if c in ok else S9.P0 if c == REST else eps / max(len(others), 1)
                      for c in cls])
    s = mdl.scores(R).mean(0)
    q = prior * np.exp(S9.BETA * (s - s.max()))
    q /= q.sum()
    Zq = mdl.z(R)
    mdl.G = S9.DECAY * mdl.G + Zq.T @ Zq
    mdl.s = S9.DECAY * mdl.s + np.outer(q, Zq.sum(0))
    mdl.n = S9.DECAY * mdl.n + q * len(Zq)
    mdl.fit()


def label_pass(mdl, F, classes, cond, rng):
    cmds = [c for c in classes if c != REST]
    n_ctx = n_wrong = 0
    for t in (2, 3, 4):
        for g in cmds:
            pred, R = S9.decide(mdl, F[(g, t)])
            if pred is None:
                continue
            if cond[0] == 'x':
                # goal inferred from the EMG-decoded commands only (no geometry): the most frequent non-Rest
                # prediction over the trial's windows; confidence P = its share. Errors follow the classifier's.
                pr = mdl.predict(F[(g, t)][5:])
                cnt = np.array([(pr == c).sum() for c in cmds])
                if cnt.sum() == 0:
                    continue
                goal = cmds[int(np.argmax(cnt))]
                conf = cnt.max() / cnt.sum()
                n_ctx += 1
                n_wrong += int(goal != g)
                if cond == 'xh':
                    if pred == goal:
                        hard(mdl, R, pred)
                    else:
                        hard(mdl, R, goal)
                elif cond == 'xs15':
                    soft_set(mdl, R, [goal], 0.15)
                elif cond == 'xcal':
                    soft_set(mdl, R, [goal], float(np.clip(1 - conf, 0.05, 0.5)))
                continue
            if cond[0] in 'hs' and cond[1].isdigit():
                r = int(cond[1:].split('e')[0]) / 100
                ok = [g] if rng.random() >= r else [int(rng.choice([c for c in cmds if c != g]))]
                if cond[0] == 'h':
                    if pred in ok:
                        hard(mdl, R, pred)
                    else:
                        s = mdl.scores(R).mean(0)
                        hard(mdl, R, max(ok, key=lambda c: s[mdl.classes.index(c)]))
                else:
                    soft_set(mdl, R, ok, int(cond.split('e')[1]) / 100)
                continue
            kind = cond[:4]
            ctx = cond[4:] if kind != 'self' else ''
            if ctx == '1':
                ok = [g]
            elif ctx == '2':
                ok = [g, int(rng.choice([c for c in cmds if c != g]))]
            elif ctx == '30':
                ok = [g] if rng.random() >= 0.3 else [int(rng.choice([c for c in cmds if c != g]))]
            if kind == 'self':
                hard(mdl, R, pred)
            elif kind == 'ciil':
                if pred in ok:
                    hard(mdl, R, pred)
                else:
                    s = mdl.scores(R).mean(0)
                    hard(mdl, R, max(ok, key=lambda c: s[mdl.classes.index(c)]))
            else:
                soft_set(mdl, R, ok)
    return n_ctx, n_wrong


def run_subject(days, classes, seed, CONDS=CONDS):
    S9.REST = REST
    out = {c: [] for c in CONDS}
    out['_err'] = {}
    models = {}
    rngs = {c: np.random.default_rng(seed * 1000 + i) for i, c in enumerate(CONDS)}
    for di, F in enumerate(days):
        Xc, yc = GC.stack(F, [(c, 1) for c in classes], cap=30)
        out['cue'].append(GC.test_acc(S9.Model(Xc, np.arange(len(Xc)), yc, classes), F, classes))
        for c in CONDS[1:]:
            if di == 0:
                models[c] = GC.Acc(Xc, yc, classes)
            else:
                models[c].new_session(Xc, yc)
            if c != 'acc':
                nc, nw = label_pass(models[c], F, classes, c, rngs[c])
                if c[0] == 'x':
                    e = out['_err'].setdefault(c, [0, 0])
                    e[0] += nc
                    e[1] += nw
            out[c].append(GC.test_acc(models[c], F, classes))
    return out


def subject(root, subj, o, CONDS=CONDS):
    chan_sets = [[o + i for i in (0, 2, 4, 6)] * 2, [o + i for i in (1, 3, 5, 7)] * 2]
    per = {s: {c: [] for c in CONDS} for s in SETS}
    err = {s: {} for s in SETS}
    for ci, chans in enumerate(chan_sets):
        days = [GC.load_session(root, sess, subj, chans) for sess in (1, 2, 3)]
        for s, cls in SETS.items():
            r = run_subject(days, cls, subj * 10 + ci, CONDS)
            for c in CONDS:
                per[s][c].append(r[c])
            for c, (nc, nw) in r['_err'].items():
                e = err[s].setdefault(c, [0, 0])
                e[0] += nc
                e[1] += nw
    out = {s: {c: np.mean(per[s][c], axis=0) for c in CONDS} for s in SETS}
    for s in SETS:
        out[s]['_err'] = err[s]
    return subj, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--subjects', default='1-43')
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--ring-offset', type=int, default=0)
    ap.add_argument('--out')
    ap.add_argument('--sweep', action='store_true')
    ap.add_argument('--corr', action='store_true')
    a = ap.parse_args()
    lo, hi = (a.subjects.split('-') + [None])[:2]
    subs = list(range(int(lo), int(hi or lo) + 1))
    conds = SWEEP if a.sweep else CORR if a.corr else CONDS
    res = Parallel(n_jobs=a.jobs)(delayed(subject)(a.dir, s, a.ring_offset, conds) for s in subs)
    lines = []

    def p(s=''):
        print(s, flush=True)
        lines.append(s)

    p(f'GrabMyo 4ch, {len(subs)} participants; balanced accuracy %, day 1 / day 8 / day 29; later = mean of days 8, 29')
    if a.corr:
        names = {'self': 'self-training', 'ciil1': 'CIIL-like, true goal', 'soft1': 'soft, true goal',
                 'xh': 'hard, inferred goal', 'xs15': 'soft eps 0.15, inferred goal', 'xcal': 'soft eps = 1 - P, inferred goal'}
        for s in SETS:
            later = {c: np.array([r[s][c] for _, r in res])[:, 1:].mean(1) for c in conds}
            ec = [sum(r[s]['_err'].get('xh', [0, 0])[i] for _, r in res) for i in (0, 1)]
            p(f'\n===== {s}: goal inferred from decoded commands is wrong in {100 * ec[1] / max(ec[0], 1):.1f} % of labelled trials')
            for ref in ('acc', 'self'):
                p(f'  later, difference vs {ref}:')
                for c in conds[2:]:
                    if c == ref:
                        continue
                    d = later[c] - later[ref]
                    lo_, hi_ = np.percentile([np.random.default_rng(b).choice(d, len(d)).mean() for b in range(2000)], [2.5, 97.5])
                    p(f'    {names[c]:32s} {d.mean():+5.2f}  (95 % CI {lo_:+5.2f} to {hi_:+5.2f}), better in {int((d > 0).sum())}/{len(d)}')
            for x, y in (('xcal', 'xh'), ('xcal', 'xs15'), ('xs15', 'xh')):
                d = later[x] - later[y]
                p(f'  {names[x]} - {names[y]}: {d.mean():+5.2f}, better in {int((d > 0).sum())}/{len(d)}')
        if a.out:
            os.makedirs(a.out, exist_ok=True)
            with open(os.path.join(a.out, f'grabmyo_labels_corr_{a.subjects}.txt'), 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines) + '\n')
        return
    if a.sweep:
        for s in SETS:
            later = {c: np.array([r[s][c] for _, r in res])[:, 1:].mean(1) for c in conds}
            p(f'\n===== {s}: later accuracy minus acc (no task labels), mean over participants (better in n/{len(subs)})')
            p('  wrong ctx | hard (CIIL-like) | ' + ' | '.join(f'soft eps {e / 100:.2f}' for e in EPSS))
            for r in RATES:
                cells = [later[f'h{r}'] - later['acc']] + [later[f's{r}e{e}'] - later['acc'] for e in EPSS]
                p(f'  {r:6d} %  | ' + ' | '.join(f'{d.mean():+6.2f} ({int((d > 0).sum()):2d})' for d in cells))
            p(f'  acc - cue: {(later["acc"] - later["cue"]).mean():+.2f}')
        if a.out:
            os.makedirs(a.out, exist_ok=True)
            with open(os.path.join(a.out, f'grabmyo_labels_sweep_{a.subjects}.txt'), 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines) + '\n')
        return
    for s in SETS:
        p(f'\n===== {s}')
        R = {c: np.array([r[s][c] for _, r in res]) for c in CONDS}
        for c in CONDS:
            m = R[c].mean(0)
            p(f'  {c:7s} {m[0]:5.1f} / {m[1]:5.1f} / {m[2]:5.1f}')
        later = {c: R[c][:, 1:].mean(1) for c in CONDS}
        for ref in ('acc', 'self'):
            p(f'  later, difference vs {ref}:')
            for c in CONDS:
                if c in ('cue', ref):
                    continue
                d = later[c] - later[ref]
                lo_, hi_ = np.percentile([np.random.default_rng(b).choice(d, len(d)).mean() for b in range(2000)], [2.5, 97.5])
                p(f'    {c:7s} {d.mean():+5.2f}  (95 % CI {lo_:+5.2f} to {hi_:+5.2f}), better in {int((d > 0).sum())}/{len(d)}')
        for x, y in (('soft1', 'ciil1'), ('soft2', 'ciil2'), ('soft30', 'ciil30')):
            d = later[x] - later[y]
            p(f'  {x} - {y}: {d.mean():+5.2f}, better in {int((d > 0).sum())}/{len(d)}')
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, f'grabmyo_labels_{a.subjects}.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
