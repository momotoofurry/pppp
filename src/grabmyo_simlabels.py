"""Do the assist's hindsight task labels help the board's cross-day accumulation? GrabMyo days 1 / 8 / 29, 43 people,
G5 (4 directions + rest), report 35.66.

35.55 injected random wrong goals per trial. Here the labels have the structure the assist would give (35.65,
label_sim.py): per window, the label is drawn from P(label | true class) measured in the pick-and-place simulation,
including 'no label' (results/assist/label_sim_confusion.json, decoder window error e = 0.123 = GrabMyo G5).
Same data, features, model, day protocol and accumulation as grabmyo_labels.py (cued pass = trial 1, task = trials
2-4 of every class including rest, test = trials 5-7). Windows of a task trial: from the 6th on (as there).

Conditions (all carry the running sums across days, as 'acc'):
  cue        daily short calibration (reference)
  acc        accumulation, no task labels
  self       35.55's self-training: the decided command, hard, per trial (rest trials not used)
  soft1      35.55's soft label with the true goal, per trial (rest trials not used)
  pw_self    per window: the model's own prediction, hard (self-training at window level)
  pw_true    per window: the true class, hard, every window (upper bound)
  <rule>_<user>_h / _s   per window: label drawn from the simulated rule; hard, or soft (prior 1 - eps on the
             label, eps = max(0.03, the rule's error rate) spread over the others)
Reported: day means, later (days 8, 29) minus acc and minus self, 95 % bootstrap CI, better in n / 43, and the
label error / coverage actually drawn.

usage: python src/grabmyo_simlabels.py --dir /grabmyo [--subjects 1-43] [--jobs 8] [--out results/grabmyo]
"""
import argparse
import json
import os
import sys

import numpy as np
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grabmyo_crossday as GC  # noqa: E402
import grabmyo_labels as GL  # noqa: E402
import selftest9_analysis as S9  # noqa: E402

REST = GC.REST
CLS = GC.SETS['G5']                                   # [0, 1, 2, 3, 8] <-> up, down, left, right, rest
NAMES = ['up', 'down', 'left', 'right', 'rest']
E_KEY = '0.123'
RULES = [('agree', 'dominant'), ('agree', 'any-order'), ('motion', 'any-order'), ('geometry', 'any-order')]
CONDS = ['cue', 'acc', 'self', 'soft1', 'pw_self', 'pw_true'] + [f'{r}_{u}_{k}' for r, u in RULES for k in 'hs']
# --ablate: how much of the gain comes from labelling the rest trials ('_nr' = rest trials not labelled) and from
# using every window of a trial ('_dec' = only the decided run of windows, as 35.55's per-trial labels)
ABLATE = ['cue', 'acc', 'soft1', 'pw_true', 'pw_true_nr', 'pw_true_dec_nr', 'agree_any-order_s', 'agree_any-order_s_nr']


def load_mats(path, rules=None):
    raw = json.load(open(path, encoding='utf-8'))
    out = {}
    for r, u in (rules or RULES):
        m = raw[f'{r}|{u}|{E_KEY}']
        P = np.zeros((5, 6))                         # true x (5 labels + none)
        for i, t in enumerate(NAMES):
            row = np.array([m[t][l] for l in NAMES + ['none']], float)
            P[i] = row / row.sum()
        lab = P[:, :5].sum()
        err = sum(P[i, j] for i in range(5) for j in range(5) if i != j) / lab
        out[f'{r}_{u}'] = (P, max(0.03, float(err)))
    return out


def multi_hard(mdl, R, labs):
    Zq = mdl.z(R)
    mdl.G = S9.DECAY * mdl.G + Zq.T @ Zq
    mdl.s = S9.DECAY * mdl.s
    mdl.n = S9.DECAY * mdl.n
    for c in set(labs):
        idx = [i for i, l in enumerate(labs) if l == c]
        k = mdl.classes.index(c)
        mdl.s[k] += Zq[idx].sum(0)
        mdl.n[k] += len(idx)
    mdl.fit()


def multi_soft(mdl, R, labs, eps):
    cls = mdl.classes
    prior = np.array([[1 - eps if c == l else eps / (len(cls) - 1) for c in cls] for l in labs])
    s = mdl.scores(R)
    q = prior * np.exp(S9.BETA * (s - s.max(1, keepdims=True)))
    q /= q.sum(1, keepdims=True)
    Zq = mdl.z(R)
    mdl.G = S9.DECAY * mdl.G + Zq.T @ Zq
    mdl.s = S9.DECAY * mdl.s + q.T @ Zq
    mdl.n = S9.DECAY * mdl.n + q.sum(0)
    mdl.fit()


def window_pass(mdl, F, cond, rng, mats, tally):
    nr, dec = cond.endswith('_nr'), '_dec' in cond
    cond = cond.replace('_dec', '').replace('_nr', '')
    for t in (2, 3, 4):
        for g in CLS:
            if nr and g == REST:
                continue
            X = F[(g, t)][5:]
            if dec:
                X = S9.decide(mdl, F[(g, t)])[1]
                if X is None:
                    continue
            if len(X) == 0:
                continue
            if cond == 'pw_self':
                labs = [int(c) for c in mdl.predict(X)]
                keep = list(range(len(X)))
            elif cond == 'pw_true':
                labs, keep = [g] * len(X), list(range(len(X)))
            else:
                P, eps = mats[cond[:-2]]
                row = P[CLS.index(g)]
                draw = rng.choice(6, size=len(X), p=row)
                keep = [i for i, d in enumerate(draw) if d < 5]
                labs = [CLS[draw[i]] for i in keep]
            tally[0] += len(X)
            tally[1] += len(keep)
            tally[2] += sum(l != g for l in labs)
            if not keep:
                continue
            R = X[keep]
            if cond.endswith('_s'):
                multi_soft(mdl, R, labs, mats[cond[:-2]][1])
            else:
                multi_hard(mdl, R, labs)


def run_subject(days, seed, mats, CONDS=CONDS):
    S9.REST = REST
    out = {c: [] for c in CONDS}
    tallies = {c: [0, 0, 0] for c in CONDS}
    models = {}
    rngs = {c: np.random.default_rng(seed * 1000 + i) for i, c in enumerate(CONDS)}
    for di, F in enumerate(days):
        Xc, yc = GC.stack(F, [(c, 1) for c in CLS], cap=30)
        out['cue'].append(GC.test_acc(S9.Model(Xc, np.arange(len(Xc)), yc, CLS), F, CLS))
        for c in CONDS[1:]:
            if di == 0:
                models[c] = GC.Acc(Xc, yc, CLS)
            else:
                models[c].new_session(Xc, yc)
            if c in ('self', 'soft1'):
                GL.label_pass(models[c], F, CLS, c, rngs[c])
            elif c != 'acc':
                window_pass(models[c], F, c, rngs[c], mats, tallies[c])
            out[c].append(GC.test_acc(models[c], F, CLS))
    return out, tallies


def subject(root, subj, o, mats, CONDS=CONDS):
    chan_sets = [[o + i for i in (0, 2, 4, 6)] * 2, [o + i for i in (1, 3, 5, 7)] * 2]
    per = {c: [] for c in CONDS}
    tal = {c: [0, 0, 0] for c in CONDS}
    for ci, chans in enumerate(chan_sets):
        days = [GC.load_session(root, sess, subj, chans) for sess in (1, 2, 3)]
        r, t = run_subject(days, subj * 10 + ci, mats, CONDS)
        for c in CONDS:
            per[c].append(r[c])
            tal[c] = [a + b for a, b in zip(tal[c], t[c])]
    return subj, {c: np.mean(per[c], axis=0) for c in CONDS}, tal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--subjects', default='1-43')
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--ring-offset', type=int, default=0)
    ap.add_argument('--mats', default='results/assist/label_sim_confusion.json')
    ap.add_argument('--out')
    ap.add_argument('--ablate', action='store_true')
    ap.add_argument('--rules', help='35.70: comma-separated rule|user keys of the --mats file (e.g. agree2_t4|hesitant)')
    ap.add_argument('--tag', default='', help='suffix of the output file')
    a = ap.parse_args()
    rules = [tuple(x.split('|')) for x in a.rules.split(',')] if a.rules else None
    if rules:
        CONDS = ['cue', 'acc', 'pw_true'] + [f'{r}_{u}_{k}' for r, u in rules for k in 'hs']
    else:
        CONDS = ABLATE if a.ablate else globals()['CONDS']
    mats = load_mats(a.mats, rules)
    lo, hi = (a.subjects.split('-') + [None])[:2]
    subs = list(range(int(lo), int(hi or lo) + 1))
    res = Parallel(n_jobs=a.jobs)(delayed(subject)(a.dir, s, a.ring_offset, mats, CONDS) for s in subs)
    lines = []

    def p(s=''):
        print(s, flush=True)
        lines.append(s)

    p(f'GrabMyo 4ch G5, {len(subs)} participants; balanced accuracy %, day 1 / day 8 / day 29; later = mean of days 8, 29')
    p(f'per-window labels drawn from label_sim.py confusion at e = {E_KEY} (soft eps per rule: '
      + ', '.join(f'{k} {v[1]:.3f}' for k, v in mats.items()) + ')')
    R = {c: np.array([r[c] for _, r, _ in res]) for c in CONDS}
    tal = {c: np.sum([t[c] for _, _, t in res], axis=0) for c in CONDS}
    p('  condition                 day1 / day8 / day29    windows labelled   label error')
    for c in CONDS:
        m = R[c].mean(0)
        extra = ''
        if tal[c][0]:
            extra = f'   {100 * tal[c][1] / tal[c][0]:5.1f} %          {100 * tal[c][2] / max(tal[c][1], 1):5.2f} %'
        p(f'  {c:24s}  {m[0]:5.1f} / {m[1]:5.1f} / {m[2]:5.1f}{extra}')
    later = {c: R[c][:, 1:].mean(1) for c in CONDS}
    for ref in [x for x in ('acc', 'self', 'soft1') if x in CONDS]:
        p(f'  later, difference vs {ref}:')
        for c in CONDS:
            if c in ('cue', ref):
                continue
            d = later[c] - later[ref]
            lo_, hi_ = np.percentile([np.random.default_rng(b).choice(d, len(d)).mean() for b in range(2000)], [2.5, 97.5])
            p(f'    {c:24s} {d.mean():+5.2f}  (95 % CI {lo_:+5.2f} to {hi_:+5.2f}), better in {int((d > 0).sum())}/{len(d)}')
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, f'grabmyo_simlabels{"_ablate" if a.ablate else ""}{a.tag}_{a.subjects}.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
