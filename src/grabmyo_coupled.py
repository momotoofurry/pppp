"""Hindsight labels coupled to the decoder's own errors, GrabMyo days 1 / 8 / 29, 43 people, G5 (report 35.73 B).

35.66 / 35.70 drew each window's label from P(label | true class) measured in the pick-and-place simulation. Whether a
window got a label did not depend on what the GrabMyo model predicted on that window, and the simulated decoder's
window errors were independent. The real rule agree2 labels a window only when the decoder's ESTABLISHED command
agrees with the geometry. So on real data the labelled windows are mostly ones the model already gets right, and
errors that come in runs (real EMG) leave whole stretches unlabelled. Here the labels come from the model's own
predictions on each task trial:
  established command  K_DC equal predictions in a row (as the board); it holds until another class has K_DC in a row
  geometry             the trial's class: the user holds one gesture for the whole trial (geometry errors ignored,
                       so the coupled rule has no wrong labels; it measures only WHICH windows get labels)
  agree2_t6            label g where the established command is g and does not change in the next N_TAIL windows
                       (Rest exempt from the tail rule, as labeler.py)
Conditions (all carry the running sums across days, as 'acc' in grabmyo_simlabels.py):
  acc          accumulation, no task labels
  pw_true      every window, true class (upper bound)
  drawn_h      35.70: agree2_t6 (hesitant) drawn from the simulated confusion, hard (for comparison)
  cpl_h        coupled agree2_t6, hard
  fix<w>e<p>   cpl + the windows under a WRONG established command (the user corrects afterwards) labelled with the
               trial class at weight w; with probability p that label is a random other class (geometry error)
Reported per condition: day means, windows labelled, label error, and 'corrective' = labelled windows on which the
model's own window prediction was wrong (the windows a label can teach something new).

usage: python src/grabmyo_coupled.py --dir /mnt/d/grabmyo [--subjects 1-43] [--jobs 8] [--out results/grabmyo]
"""
import argparse
import os
import sys

import numpy as np
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grabmyo_crossday as GC  # noqa: E402
import grabmyo_simlabels as GS  # noqa: E402
import selftest9_analysis as S9  # noqa: E402

REST = GC.REST
CLS = GS.CLS
N_TAIL = 6
FIX = [(0.3, 0.05), (0.3, 0.2), (1.0, 0.05)]
CONDS = ['cue', 'acc', 'pw_true', 'drawn_h', 'cpl_h'] + [f'fix{w:g}e{p:g}' for w, p in FIX]
DRAWN = ('agree2_t6', 'hesitant')


def update(mdl, R, labs, wts):
    """weighted hard labels: one decay per trial, as GS.multi_hard (wts all 1 = multi_hard)"""
    Zq = mdl.z(R)
    wts = np.asarray(wts, float)
    mdl.G = S9.DECAY * mdl.G + (Zq * wts[:, None]).T @ Zq
    mdl.s = S9.DECAY * mdl.s
    mdl.n = S9.DECAY * mdl.n
    for c in set(labs):
        idx = [i for i, l in enumerate(labs) if l == c]
        k = mdl.classes.index(c)
        mdl.s[k] += (Zq[idx] * wts[idx, None]).sum(0)
        mdl.n[k] += wts[idx].sum()
    mdl.fit()


def established(pr):
    est, run_c, run_n, out = None, None, 0, []
    for p in pr:
        if p == run_c:
            run_n += 1
        else:
            run_c, run_n = p, 1
        if run_n >= S9.K_DC:
            est = run_c
        out.append(est)
    return out


def coupled(mdl, Xall, g, w, p, rng):
    """-> (rows, labels, weights, own window predictions) for one task trial"""
    pr = [int(c) for c in mdl.predict(Xall)]
    est = established(pr)
    rows, labs, wts, own = [], [], [], []
    for i in range(5, len(Xall)):
        c = est[i]
        if c is None:
            continue
        tail = c != REST and any(e != c for e in est[i + 1:i + 1 + N_TAIL])
        if c == g and not tail:
            rows.append(i)
            labs.append(g)
            wts.append(1.0)
            own.append(pr[i])
        elif c != g and w is not None:
            lab = g if rng.random() >= p else int(rng.choice([x for x in CLS if x != g]))
            rows.append(i)
            labs.append(lab)
            wts.append(w)
            own.append(pr[i])
    return rows, labs, wts, own


def window_pass(mdl, F, cond, rng, mats, tally):
    if cond in ('pw_true', 'drawn_h'):
        GS.window_pass(mdl, F, 'pw_true' if cond == 'pw_true' else '_'.join(DRAWN) + '_h', rng, mats, tally)
        return
    w = p = None
    if cond.startswith('fix'):
        w, p = (float(v) for v in cond[3:].split('e'))
    for t in (2, 3, 4):
        for g in CLS:
            Xall = F[(g, t)]
            if len(Xall) <= 5:
                continue
            rows, labs, wts, own = coupled(mdl, Xall, g, w, p, rng)
            tally[0] += len(Xall) - 5
            tally[1] += len(rows)
            tally[2] += sum(l != g for l in labs)
            tally[3] += sum(o != g for o, wt in zip(own, wts) if wt == 1.0)    # corrective among the agree2 labels
            if rows:
                update(mdl, Xall[rows], labs, wts)


def run_subject(days, seed, mats):
    S9.REST = REST
    out = {c: [] for c in CONDS}
    tallies = {c: [0, 0, 0, 0] for c in CONDS}
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
            if c != 'acc':
                window_pass(models[c], F, c, rngs[c], mats, tallies[c])
            out[c].append(GC.test_acc(models[c], F, CLS))
    return out, tallies


def subject(root, subj, o, mats):
    chan_sets = [[o + i for i in (0, 2, 4, 6)] * 2, [o + i for i in (1, 3, 5, 7)] * 2]
    per = {c: [] for c in CONDS}
    tal = {c: [0, 0, 0, 0] for c in CONDS}
    for ci, chans in enumerate(chan_sets):
        days = [GC.load_session(root, sess, subj, chans) for sess in (1, 2, 3)]
        r, t = run_subject(days, subj * 10 + ci, mats)
        for c in CONDS:
            per[c].append(r[c])
            tal[c] = [a + b for a, b in zip(tal[c], t[c])]
    return subj, {c: np.mean(per[c], axis=0) for c in CONDS}, tal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--subjects', default='1-43')
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--mats', default='results/assist/label_sim2_confusion.json')
    ap.add_argument('--out')
    a = ap.parse_args()
    mats = GS.load_mats(a.mats, [DRAWN])
    lo, hi = (a.subjects.split('-') + [None])[:2]
    subs = list(range(int(lo), int(hi or lo) + 1))
    res = Parallel(n_jobs=a.jobs)(delayed(subject)(a.dir, s, 0, mats) for s in subs)
    lines = []

    def p(s=''):
        print(s, flush=True)
        lines.append(s)

    p(f'GrabMyo 4ch G5, {len(subs)} participants; balanced accuracy %, day 1 / day 8 / day 29; later = mean of days 8, 29')
    p(f'coupled labels: established command = {S9.K_DC} equal predictions in a row; agree2_t6 (N_TAIL {N_TAIL}); '
      f'drawn_h = 35.70 draw ({"|".join(DRAWN)}, e = {GS.E_KEY})')
    R = {c: np.array([r[c] for _, r, _ in res]) for c in CONDS}
    tal = {c: np.sum([t[c] for _, _, t in res], axis=0) for c in CONDS}
    p('  condition          day1 / day8 / day29    labelled   label error   corrective (of agree2 labels)')
    for c in CONDS:
        m = R[c].mean(0)
        extra = ''
        if tal[c][0]:
            n_l = max(tal[c][1], 1)
            corr = f'{100 * tal[c][3] / n_l:5.1f} %' if c.startswith(('cpl', 'fix')) else '   --  '
            extra = f'   {100 * tal[c][1] / tal[c][0]:5.1f} %    {100 * tal[c][2] / n_l:5.2f} %      {corr}'
        p(f'  {c:16s}  {m[0]:5.1f} / {m[1]:5.1f} / {m[2]:5.1f}{extra}')
    later = {c: R[c][:, 1:].mean(1) for c in CONDS}
    for ref in ('acc', 'drawn_h', 'cpl_h'):
        p(f'  later, difference vs {ref}:')
        for c in CONDS:
            if c in ('cue', ref):
                continue
            d = later[c] - later[ref]
            lo_, hi_ = np.percentile([np.random.default_rng(b).choice(d, len(d)).mean() for b in range(2000)], [2.5, 97.5])
            p(f'    {c:16s} {d.mean():+5.2f}  (95 % CI {lo_:+5.2f} to {hi_:+5.2f}), better in {int((d > 0).sum())}/{len(d)}')
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, f'grabmyo_coupled_{a.subjects}.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
