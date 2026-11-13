"""Is the task-label gain on NinaPro DB6 only time adjacency? (report 35.32). PC only, exploratory.

In DB6 the 12 repetitions of a grasp are recorded back to back, so in db6_sim.py the task stream (repetitions 2-6)
lies right before the probe (repetitions 7-12). Here every model is scored instead on the NEXT later session's probe
(repetitions 7-12 of session b + 1), in the state it has at the end of session b, i.e. before session b + 1's cued
pass and stream: hours (T1 -> T2) or a day (T2 -> next T1) after the last label. The 8 later sessions that have a
next one are scored (subject 2: the skipped D2T2 is not a 'next' either; its neighbours pair over the gap).
Same data, features, trials, learners, seeds and stream as db6_sim.py; e 0 and 0.3.
Decision rule, fixed before running (per subject mean, 10 subjects, paired 95 % t CI):
  R11 'the task labels carry information beyond time adjacency' only if, on the next session's probe,
      cue1_soft (e 0) - cue1 >= +1 point with CI above 0. The same-session gain (db6_sim: +13.77) is reported beside
      it; the ratio says how much of it survives.
Also reported: cue1_soft - LDACMA_cum, cue1_soft (e 0.3) - cue1_pn (e 0.3), within (session b's own repetitions 1-6)
carried to the next session.
Writes results/db6_adj.csv, db6_adj_summary.txt.
Usage (in the container): python src/db6_adj.py [--jobs 10]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db6_sim as D  # noqa: E402

OUT = D.OUT


def job(subject):
    sess = [D.trials(os.path.join(D.FEAT, f'S{subject}_D{d}_T{t}.npz')) for d, t in D.SESSIONS]
    F0, tr0, _ = sess[0]
    X0, y0 = D.cat(F0, tr0, range(D.N_REP))
    m0, s0 = X0.mean(0), X0.std(0)
    bad = ~np.isfinite(s0) | (s0 == 0)
    m0[bad], s0[bad] = 0.0, np.inf
    base = D.RunLDA()
    base.add((X0 - m0) / s0, y0)
    base.fit()
    train = D.stats(D.q((X0 - m0) / s0), y0)
    data = []
    for (d, t), (F, tr, _) in zip(D.SESSIONS[1:], sess[1:]):
        if any(i is None for c in range(D.K) for i in tr[c]) or len(tr[D.REST]) < D.N_REP:
            continue
        Z = (F - m0) / s0
        Zs = [[Z[i] for i in tr[c]] for c in range(D.K)]
        Zc, yc = D.cat(Z, tr, D.CUE)
        Zp, yp = D.cat(Z, tr, D.PROBE)
        Zw, yw = D.cat(Z, tr, range(6))
        data.append(dict(day=d, t=t, Zs=Zs, Zc=Zc, yc=yc, Zp=Zp, yp=yp, Zw=Zw, yw=yw))
    out = []

    def rec(b, method, mdl, seed=0, e=0.0):
        if b + 1 < len(data):
            nx = data[b + 1]
            out.append(dict(subject=subject, day=data[b]['day'], t=data[b]['t'], next_day=nx['day'], next_t=nx['t'],
                            method=method, seed=seed, e=e, acc_next=D.acc(mdl, nx['Zp'], nx['yp']),
                            acc_same=D.acc(mdl, data[b]['Zp'], data[b]['yp'])))

    cum = base.copy()
    cal_all = []
    for b, Dd in enumerate(data):
        rec(b, 'fixed', base)
        for c in range(D.K):
            cum.learn(Dd['Zc'][Dd['yc'] == c], c, fit=False)
        cum.fit()
        rec(b, 'cue1', cum)
        cal = D.stats(D.q(Dd['Zc']), Dd['yc'])
        cal_all.append((D.q(Dd['Zc']), Dd['yc']))
        calc = D.stats(np.concatenate([z for z, _ in cal_all]), np.concatenate([y for _, y in cal_all]))
        rec(b, 'LDACMA', D.vid(train, cal, 0.8, 0.8))
        rec(b, 'LDACMA_cum', D.vid(train, calc, 0.8, 0.8))
        w = D.RunLDA()
        w.add(Dd['Zw'], Dd['yw'])
        rec(b, 'within', w.fit())
    for seed in D.SEEDS:
        for mode in ('oracle', 'pos', 'pn', 'soft'):
            for e in ((0.0,) if mode == 'oracle' else (0.0, 0.3)):
                rng = np.random.default_rng(seed * 100003 + subject * 101 + int(e * 100))
                mdl = base.copy()
                for b, Dd in enumerate(data):
                    for c in range(D.K):
                        mdl.learn(Dd['Zc'][Dd['yc'] == c], c, fit=False)
                    mdl.fit()
                    D.stream(mdl, Dd['Zs'], mode, e, rng)
                    rec(b, 'cue1_' + mode, mdl, seed, e)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=10)
    args = ap.parse_args()
    rows = Parallel(n_jobs=args.jobs)(delayed(job)(s) for s in range(1, 11))
    df = pd.DataFrame([r for rr in rows for r in rr])
    df.to_csv(os.path.join(OUT, 'db6_adj.csv'), index=False)
    lines = []

    def p(s=''):
        lines.append(s)
        print(s, flush=True)

    per_n = df.groupby(['method', 'e', 'subject']).acc_next.mean().unstack('subject')
    per_s = df.groupby(['method', 'e', 'subject']).acc_same.mean().unstack('subject')
    p('mean accuracy %, 8 classes; model at the end of session b scored on b + 1 (next) and on b (same; the 8 sessions'
      ' that have a next one)')
    for i in per_n.index:
        p(f'  {i[0]:12s} e {i[1]:.1f}  next {per_n.loc[i].mean():6.2f}   same {per_s.loc[i].mean():6.2f}')

    def diff(per, a, b, ea=0.0, eb=0.0, rule='', need=None, tag=''):
        d = per.loc[(a, ea)] - per.loc[(b, eb)]
        m, lo, hi = D.ci(d)
        r = ''
        if need is not None:
            r = '  PASS' if (m >= need and lo > 0) else '  FAIL'
        p(f'  {rule:4s} [{tag}] {a}(e {ea}) - {b}(e {eb}) = {m:+.2f} ({lo:+.2f}, {hi:+.2f}), {int((d > 0).sum())}/10 higher{r}')
        return m

    p('\npaired differences (95 % t CI)')
    mn = diff(per_n, 'cue1_soft', 'cue1', rule='R11', need=1, tag='next')
    ms = diff(per_s, 'cue1_soft', 'cue1', tag='same')
    p(f'       share of the same-session gain left on the next session: {mn / ms * 100:.0f} %')
    for a, b, ea, eb in (('cue1_oracle', 'cue1', 0, 0), ('cue1_soft', 'LDACMA_cum', 0, 0), ('cue1_soft', 'LDACMA', 0, 0),
                         ('cue1', 'LDACMA_cum', 0, 0), ('cue1_soft', 'cue1_pn', 0.3, 0.3),
                         ('cue1_soft', 'cue1_pos', 0.3, 0.3), ('cue1_soft', 'cue1', 0.3, 0), ('within', 'cue1_soft', 0, 0),
                         ('cue1', 'fixed', 0, 0)):
        diff(per_n, a, b, ea, eb, tag='next')
    p('\nby gap (next session same day vs next day), e 0, next-session accuracy')
    df['gap'] = np.where(df.next_day == df.day, 'same day', 'next day')
    g = df[df.e == 0].groupby(['method', 'gap']).acc_next.mean().unstack()
    p(g.round(2).to_string())
    with open(os.path.join(OUT, 'db6_adj_summary.txt'), 'w') as f:
        f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
