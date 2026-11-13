"""Real re-donning on public data: NinaPro DB6 (Palermo et al. 2017), report 35.31. PC only, exploratory.

Data: 10 subjects, 5 days x 2 sessions (morning T1, afternoon T2), 7 grasps (restimulus 1 3 4 6 9 10 11) + rest,
12 repetitions each, Delsys Trigno at 2 kHz. Features from src/db6_features.py: the first electrode ring (columns
0-7), src/c/features.c streamed over the whole session (200 ms windows, 100 ms step). All 8 classes are used (no
gesture dropped). Classes 0-6 = grasps in restimulus order, 7 = rest.

Trials: a grasp repetition = the 10 central windows lying wholly inside its restimulus segment (all windows when
fewer than 10; a repetition with fewer than 3 is missing). Rest: rest segments with >= 10 windows, 12 of them evenly
spaced over the session, 10 central windows each.

Protocol per subject, sessions in recorded order D1T1, D1T2, D2T1 ... D5T2:
- day 1 = D1T1, all 12 repetitions: z-score statistics (kept fixed, as on the device) and the day-1 model;
- each of the 9 later sessions: cued pass = repetition 1 of every class (80 windows; Vidovic et al. 2016 used one 4 s
  repetition of every movement); task stream = repetitions 2-6; probe = repetitions 7-12 (480 windows), scored after
  the session's updates, every window, argmax of the 8 LDA scores.
- features in the day-1 z-score, Q5.10, shrinkage LDA from running sums with OAS, forgetting 0.97 per learned trial
  (lda_anchor.OasLDA / lda_context2.learn / task_sim2.learn_soft, here for 8 classes).
Methods
  fixed        day-1 model
  cue1, cue2   ours: 1 or 2 cued passes per session added to the running sums, kept across sessions
  cue1_reset   day-1 sums + only this session's cued pass (no accumulation across sessions)
  LDAMA, LDACMA, LDAnew  Vidovic et al. 2016 eq. 6-7 from the day-1 model with this session's cued pass
               (tau, lambda) = (0.7, 0), (0.8, 0.8), (1, 1); solved with OAS as in task_sim6.py
  LDACMA_cum   the same with the calibration statistics pooled over all cued passes so far (our reading of their
               cumulative LDADEA)
  vid_best     the (tau, lambda) of a 0.1 grid that is best ON THIS DATA (optimistic upper bound)
  within       this session's repetitions 1-6 only (a full recalibration every session; reference)
  task stream  after the cued pass (cue1_*) or without it: for every repetition 2-6 the grasps are attempted in a
               random order; the decision = the first run of 3 equal non-rest window predictions (task_sim K_DC),
               its rows = that run extended while the prediction stays; no decision -> nothing learned. The robot's
               expected grasp is the intended one, replaced with probability e by a random other grasp.
               pos (P-CIIL: learn the prediction when it equals the expected), pn (hard: learn the expected), soft
               (task_sim2: prior expected 1 - eps, other grasps eps / 6, rest p0; q = prior x exp(beta x mean score)),
               oracle (learn the true grasp). e = 0, 0.1, 0.2, 0.3; 5 seeds.
Decision rules, fixed before running (per subject mean over the 9 later sessions and the seeds, 10 subjects, paired,
95 % t CI):
  R8  'a cued pass per session holds on real re-donning' only if cue1 - fixed >= +5 points with CI above 0.
  R9  'one cued pass + soft task labels beats the published short recalibration' only if cue1_soft (e 0) - LDACMA
      >= +1 point with CI above 0. Also reported against LDACMA_cum and vid_best; when cue1_soft - LDACMA_cum has a
      CI containing 0, the report says the gain over LDACMA comes from the accumulation.
  Exclusion (fixed before running, after seeing that S2_D2_T2.mat is a 1.7 min file with grasp 1 only): a session
  with any grasp repetition or rest trial missing is skipped as if not recorded (no learning, not scored); the per
  subject mean is over the remaining later sessions.
  Flat channel (fixed before the final run): S9_D1_T1 column 7 is all zero (the only flat channel of the 100
  sessions); features with zero or undefined (NaN: skw, vcf, mnf) day-1 spread are 0 after the z-score, so subject 9 runs on 7 channels throughout.
  R10 soft labels with 30 % wrong task labels: cue1_soft - cue1_pn >= +1 with CI above 0 at e 0.3, and
      cue1_soft (e 0.3) - cue1 reported (task labels still useful when its CI is above 0).
Writes results/db6_sim.csv (per subject, session, method, seed), db6_sim_summary.txt.
Usage (in the container): python src/db6_sim.py [--jobs 10]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy import stats as sst

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lda_robust as LR  # noqa: E402
import pipeline as P  # noqa: E402
import task_sim2 as T2  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
FEAT = '/db6/features'
GRASPS = (1, 3, 4, 6, 9, 10, 11)
K = 8
REST = 7
NW, MIN_W, N_REP = 10, 3, 12
CUE, STREAM, PROBE = (0,), (1, 2, 3, 4, 5), (6, 7, 8, 9, 10, 11)
DECAY, K_DC = 0.97, 3
EPS, P0, BETA = T2.EPS, T2.P0, T2.BETA
SESSIONS = [(d, t) for d in range(1, 6) for t in (1, 2)]
GRID = [round(x, 1) for x in np.arange(0, 1.01, 0.1)]
PAPER = {'LDAMA': (0.7, 0.0), 'LDACMA': (0.8, 0.8), 'LDAnew': (1.0, 1.0)}
ERRS = (0.0, 0.1, 0.2, 0.3)
SEEDS = range(5)


def q(X):
    return P.quantize(X).astype(np.float64) / (1 << P.Q_SHIFT)


class RunLDA:
    """lda_anchor.OasLDA for K classes, with lda_context2.learn (forgetting) and task_sim2.learn_soft"""

    def __init__(self, d=80):
        self.G, self.s, self.n = np.zeros((d, d)), np.zeros((K, d)), np.zeros(K)

    def add(self, Z, y):
        Zq = q(Z)
        self.G += Zq.T @ Zq
        for c in range(K):
            self.s[c] += Zq[y == c].sum(0)
            self.n[c] += np.sum(y == c)

    def fit(self):
        N = self.n.sum()
        m = self.s / self.n[:, None]
        S = (self.G - (m.T * self.n) @ m) / N
        self.w, self.b = LR.oas_solve(S, N, m)
        return self

    def learn(self, Z, lab, fit=True):
        self.G *= DECAY
        self.s *= DECAY
        self.n *= DECAY
        self.add(Z, np.full(len(Z), lab))
        if fit:
            self.fit()

    def learn_soft(self, Z, qq):
        Zq = q(Z)
        self.G = DECAY * self.G + Zq.T @ Zq
        self.s = DECAY * self.s + np.outer(qq, Zq.sum(0))
        self.n = DECAY * self.n + qq * len(Zq)
        self.fit()

    def copy(self):
        o = RunLDA(self.G.shape[0])
        o.G, o.s, o.n = self.G.copy(), self.s.copy(), self.n.copy()
        return o.fit()

    def scores(self, Z):
        return q(Z) @ self.w.T + self.b


def acc(mdl, Z, y):
    return float(np.mean(np.argmax(mdl.scores(Z), 1) == y) * 100)


def mid(idx):
    if len(idx) <= NW:
        return idx
    a = (len(idx) - NW) // 2
    return idx[a:a + NW]


def trials(path):
    """-> X (windows x 80, raw features), list over classes of 12 window-index arrays (None when missing), shortfalls"""
    z = np.load(path)
    F, lab, rep, seg = np.nan_to_num(z['F'].astype(np.float64)), z['lab'], z['rep'], z['seg']   # skw/vcf/mnf of an all-zero channel are NaN
    tr, short = [], 0
    for g in GRASPS:
        t = []
        for r in range(1, N_REP + 1):
            idx = np.flatnonzero((lab == g) & (rep == r))
            short += int(len(idx) < NW)
            t.append(mid(idx) if len(idx) >= MIN_W else None)
        tr.append(t)
    rs = [np.flatnonzero(seg == s) for s in np.unique(seg[lab == 0])]
    rs = [i for i in rs if len(i) >= NW]
    if len(rs) < N_REP:
        tr.append([None] * N_REP)
        return F, tr, short
    pick = np.round(np.linspace(0, len(rs) - 1, N_REP)).astype(int)
    tr.append([mid(rs[k]) for k in pick])
    return F, tr, short


def cat(F, tr, which):
    rows = [(tr[c][k], c) for c in range(K) for k in which if tr[c][k] is not None]
    return np.concatenate([F[i] for i, _ in rows]), np.concatenate([np.full(len(i), c) for i, c in rows])


def stats(Zq, y):
    mu = np.stack([Zq[y == c].mean(0) for c in range(K)])
    R = Zq - mu[y]
    return mu, R.T @ R / len(Zq), float(len(Zq))


class Vid:
    def __init__(self, w, b):
        self.w, self.b = w, b

    def scores(self, Z):
        return q(Z) @ self.w.T + self.b


def vid(train, cal, tau, lam):
    (mu_t, S_t, n_t), (mu_c, S_c, n_c) = train, cal
    return Vid(*LR.oas_solve((1 - lam) * S_t + lam * S_c, (1 - lam) * n_t + lam * n_c, (1 - tau) * mu_t + tau * mu_c))


def stream(mdl, Zs, mode, e, rng):
    """one task stream over the session's repetitions 2-6; returns command counts"""
    st = dict(cmd=0, cmd_ok=0, miss=0, lab_wrong=0)
    for k in STREAM:
        for g in rng.permutation(REST):
            Z = Zs[g][k]
            exp = int(g)
            if mode != 'oracle' and e > 0 and rng.random() < e:
                exp = int(rng.choice([c for c in range(REST) if c != g]))
            if Z is None:
                continue
            pr = np.argmax(mdl.scores(Z), 1)
            j = next((i for i in range(len(pr) - K_DC + 1) if pr[i] != REST and (pr[i:i + K_DC] == pr[i]).all()), None)
            if j is None:
                st['miss'] += 1
                continue
            pred = int(pr[j])
            end = j
            while end + 1 < len(pr) and pr[end + 1] == pred:
                end += 1
            rows = Z[j:end + 1]
            st['cmd'] += 1
            st['cmd_ok'] += int(pred == g)
            if mode == 'oracle':
                mdl.learn(rows, int(g))
            elif mode == 'pos':
                if pred == exp:
                    mdl.learn(rows, pred)
            elif mode == 'pn':
                st['lab_wrong'] += int(exp != g)
                mdl.learn(rows, exp)
            elif mode == 'soft':
                prior = np.full(K, EPS / (REST - 1))
                prior[exp] = 1 - EPS
                prior[REST] = P0
                s = mdl.scores(rows).mean(0)
                qq = prior * np.exp(BETA * (s - s.max()))
                qq /= qq.sum()
                st['lab_wrong'] += int(np.argmax(qq) != g)
                mdl.learn_soft(rows, qq)
    return st


def job(subject):
    sess = [trials(os.path.join(FEAT, f'S{subject}_D{d}_T{t}.npz')) for d, t in SESSIONS]
    F0, tr0, _ = sess[0]
    X0, y0 = cat(F0, tr0, range(N_REP))
    m0, s0 = X0.mean(0), X0.std(0)
    bad = ~np.isfinite(s0) | (s0 == 0)            # a flat day-1 feature (S9 D1T1 channel 7 is all zero) stays 0
    m0[bad], s0[bad] = 0.0, np.inf
    base = RunLDA()
    base.add((X0 - m0) / s0, y0)
    base.fit()
    train = stats(q((X0 - m0) / s0), y0)
    data = []
    for (d, t), (F, tr, short) in zip(SESSIONS[1:], sess[1:]):
        if any(i is None for c in range(K) for i in tr[c]) or len(tr[REST]) < N_REP:
            print(f'S{subject}_D{d}_T{t}: incomplete, skipped', flush=True)
            continue
        Z = (F - m0) / s0
        Zs = [[Z[i] if i is not None else None for i in tr[c]] for c in range(K)]
        Zc, yc = cat(Z, tr, CUE)
        Zc2, yc2 = cat(Z, tr, (0, 1))
        Zp, yp = cat(Z, tr, PROBE)
        Zw, yw = cat(Z, tr, range(6))
        data.append(dict(day=d, t=t, Zs=Zs, Zc=Zc, yc=yc, Zc2=Zc2, yc2=yc2, Zp=Zp, yp=yp, Zw=Zw, yw=yw, short=short))
    out = []

    def rec(b, method, a, seed=0, e=0.0, **kw):
        out.append(dict(subject=subject, session=b + 1, day=data[b]['day'], t=data[b]['t'], method=method, seed=seed,
                        e=e, acc=a, **kw))

    # static methods
    cum = {k: base.copy() for k in ('cue1', 'cue2')}
    cal_all = []
    for b, D in enumerate(data):
        rec(b, 'fixed', acc(base, D['Zp'], D['yp']), short=D['short'])
        for k, (Zc, yc) in (('cue1', (D['Zc'], D['yc'])), ('cue2', (D['Zc2'], D['yc2']))):
            for c in range(K):
                if np.any(yc == c):
                    cum[k].learn(Zc[yc == c], c, fit=False)
            cum[k].fit()
            rec(b, k, acc(cum[k], D['Zp'], D['yp']))
        r = base.copy()
        for c in range(K):
            r.learn(D['Zc'][D['yc'] == c], c, fit=False)
        rec(b, 'cue1_reset', acc(r.fit(), D['Zp'], D['yp']))
        cal = stats(q(D['Zc']), D['yc'])
        cal_all.append(q(D['Zc']))
        Zall = np.concatenate(cal_all)
        yall = np.concatenate([x['yc'] for x in data[:b + 1]])
        calc = stats(Zall, yall)
        for name, (tau, lam) in PAPER.items():
            rec(b, name, acc(vid(train, cal, tau, lam), D['Zp'], D['yp']))
        rec(b, 'LDACMA_cum', acc(vid(train, calc, 0.8, 0.8), D['Zp'], D['yp']))
        for tau in GRID:
            for lam in GRID:
                rec(b, f'grid_{tau}_{lam}', acc(vid(train, cal, tau, lam), D['Zp'], D['yp']))
        w = RunLDA()
        w.add(D['Zw'], D['yw'])
        rec(b, 'within', acc(w.fit(), D['Zp'], D['yp']))
    # task streams
    for seed in SEEDS:
        for cue in (1, 0):
            for mode in ('oracle', 'pos', 'pn', 'soft'):
                for e in (ERRS if mode != 'oracle' else (0.0,)):
                    rng = np.random.default_rng(seed * 100003 + subject * 101 + int(e * 100))
                    mdl = base.copy()
                    for b, D in enumerate(data):
                        if cue:
                            for c in range(K):
                                if np.any(D['yc'] == c):
                                    mdl.learn(D['Zc'][D['yc'] == c], c, fit=False)
                            mdl.fit()
                        st = stream(mdl, D['Zs'], mode, e, rng)
                        rec(b, ('cue1_' if cue else '') + mode, acc(mdl, D['Zp'], D['yp']), seed, e, **st)
    return out


def ci(d):
    d = np.asarray(d, dtype=float)
    m = d.mean()
    h = sst.t.ppf(0.975, len(d) - 1) * d.std(ddof=1) / np.sqrt(len(d))
    return m, m - h, m + h


def summarize(df, lines):
    def p(s=''):
        lines.append(s)
        print(s, flush=True)

    per = df.groupby(['method', 'e', 'subject']).acc.mean().unstack('subject')
    grid = per.loc[[i for i in per.index if i[0].startswith('grid_')]]
    best = grid.mean(axis=1).idxmax()
    p(f'vid_best on this data: {best[0]} ({grid.mean(axis=1).max():.2f})')
    vb = per.loc[[best]].copy()
    vb.index = pd.MultiIndex.from_tuples([('vid_best', 0.0)], names=per.index.names)
    per = pd.concat([per.loc[[i for i in per.index if not i[0].startswith('grid_')]], vb])
    p('\nmean probe accuracy % (8 classes), mean of 9 later sessions, 10 subjects')
    for (m, e), r in per.iterrows():
        p(f'  {m:12s} e {e:.1f}  {r.mean():6.2f}  (min {r.min():5.1f}, max {r.max():5.1f})')
    p('\nby session (D1T2 ... D5T2), e 0')
    bs = df[(df.e == 0) & (~df.method.str.startswith('grid_'))].groupby(['method', 'day', 't']).acc.mean().unstack(['day', 't'])
    p(bs.round(1).to_string())

    def diff(a, b, ea=0.0, eb=0.0, rule=None, need=None):
        d = per.loc[(a, ea)] - per.loc[(b, eb)]
        m, lo, hi = ci(d)
        tag = ''
        if need is not None:
            tag = '  PASS' if (m >= need and lo > 0) else '  FAIL'
        p(f'  {rule or "":4s} {a}(e {ea}) - {b}(e {eb}) = {m:+.2f} ({lo:+.2f}, {hi:+.2f}), {int((d > 0).sum())}/10 higher{tag}')

    p('\npaired differences (95 % t CI)')
    diff('cue1', 'fixed', rule='R8', need=5)
    diff('cue1_soft', 'LDACMA', rule='R9', need=1)
    diff('cue1_soft', 'LDACMA_cum')
    diff('cue1_soft', 'vid_best')
    diff('cue1', 'LDACMA')
    diff('cue1', 'LDACMA_cum')
    diff('cue1_reset', 'LDACMA')
    diff('cue1', 'cue1_reset')
    diff('cue1_soft', 'cue1')
    diff('cue1_soft', 'cue1_pn', 0.3, 0.3, rule='R10', need=1)
    diff('cue1_soft', 'cue1', 0.3, 0.0)
    diff('cue1_pos', 'cue1', 0.3, 0.0)
    diff('cue1_soft', 'cue1_pos', 0.3, 0.3)
    diff('cue2', 'cue1_soft')
    diff('within', 'cue1_soft')
    diff('soft', 'fixed')
    diff('soft', 'cue1')
    cmd = df[df.method.str.contains('soft|pn|pos|oracle')].groupby(['method', 'e'])[['cmd', 'cmd_ok', 'miss', 'lab_wrong']].sum()
    cmd['cmd_acc %'] = (cmd.cmd_ok / cmd.cmd * 100).round(1)
    p('\ntask streams: commands decided, right, missed attempts, wrong labels learned (all subjects, seeds, sessions)')
    p(cmd.to_string())
    p(f"\nrepetitions with fewer than {NW} windows: {int(df[df.method == 'fixed'].short.sum())}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=10)
    args = ap.parse_args()
    rows = Parallel(n_jobs=args.jobs, verbose=0)(delayed(job)(s) for s in range(1, 11))
    df = pd.DataFrame([r for rr in rows for r in rr])
    df.to_csv(os.path.join(OUT, 'db6_sim.csv'), index=False)
    lines = []
    pd.set_option('display.width', 250)
    summarize(df, lines)
    with open(os.path.join(OUT, 'db6_sim_summary.txt'), 'w') as f:
        f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
