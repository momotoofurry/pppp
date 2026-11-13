"""A learning rule that tolerates wrong labels from the interaction (report 35.17). PC only, exploratory.

Report 35.16: the sums of the LDA take every label at face value; 20 % wrong labels cost 7-8 points. Two facts make
a robust version cheap:
  - the within-class covariance can be taken from the scatter of the windows INSIDE a trial (around the trial's own
    mean): that does not depend on the label at all;
  - only the class means need labels, and a mean over trials can be replaced by a coordinate-wise MEDIAN over the
    last K trial means of that class: up to half of them may carry a wrong label.
Learners (all on float64 features in the day-1 z-score, shrinkage and solve as lda_anchor.OasLDA):
  plain     the sums of ldacal.c with fading 0.97 per learned trial (lda_context2.py)
  med<K>    covariance = within-trial scatter (fading 0.97); class mean = median of the last K trial means of the
            class (the day-1 calibration trial is the first entry). Memory on a device: K x 6 x 80 values.
  medb<K>   as med<K>, plus the scatter of the trial means around their class median in the covariance (the
            trial-to-trial variation that the within-trial scatter does not see)
  gate      plain sums, but a label is only believed straight away when the current model ranks it first or second for
            the trial. Otherwise the trial waits (last 3 per label); it is learned, together with the waiting one,
            when a later trial with the same label lies closer to it than to every current class mean: two trials
            that agree with each other and with nothing the model knows are a moved class, one alone is suspect.
Feedback settings: a subset of lda_context2.CONDS (same stream, same scoring, same random draws per seed).
Writes results/lda_robust.csv and lda_robust_summary.csv.
Usage (container; Kyranou at /data): python src/lda_robust.py [--jobs 19]
"""
import argparse
import os
import sys
from collections import deque

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lda_anchor as LA  # noqa: E402
import lda_context2 as C2  # noqa: E402
import leaf_guard as LG  # noqa: E402
import leaf_sweep as LS  # noqa: E402
import pipeline as P  # noqa: E402
import selfcal_sweep as S  # noqa: E402
import zscore_sweep as ZW  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
W, REST, DECAY = C2.W, C2.REST, C2.DECAY
FEED = ['ideal', 'r0.5', 'e0.1', 'e0.2', 'e0.3', 'real', 'real_cue1', 'real_m3_cue1']
LEARNERS = ['plain', 'gate', 'med5', 'med9', 'medb5', 'medb9']
SEEDS = (0, 1, 2)


def oas_solve(Sw, N, m):
    d = Sw.shape[0]
    mu = np.trace(Sw) / d
    alpha = np.mean(Sw ** 2)
    num, den = alpha + mu ** 2, (N + 1.0) * (alpha - mu ** 2 / d)
    rho = 1.0 if den == 0 else min(num / den, 1.0)
    w = np.linalg.solve((1 - rho) * Sw + rho * mu * np.eye(d), m.T).T
    return w, -0.5 * np.sum(m * w, axis=1)


class Plain:
    def __init__(self, Zc, yc):
        self.m = LA.OasLDA()
        self.m.add(Zc, yc)
        self.m.fit()

    def learn(self, Z, lab):
        C2.learn(self.m, Z, lab)

    def scores(self, Z):
        return self.m.scores(Z)


class Gate(Plain):
    def __init__(self, Zc, yc):
        super().__init__(Zc, yc)
        self.pend = [deque(maxlen=3) for _ in range(LS.K)]

    def learn(self, Z, lab):
        m = Z.mean(0)
        if lab in np.argsort(self.m.scores(m[None])[0])[-2:]:
            return super().learn(Z, lab)
        mu = self.m.s / self.m.n[:, None]
        dmin = np.min(np.linalg.norm(mu - LA.OasLDA.q(m[None])[0], axis=1))
        for j, Zp in enumerate(self.pend[lab]):
            if np.linalg.norm(Zp.mean(0) - m) < dmin:
                del self.pend[lab][j]
                super().learn(Zp, lab)
                return super().learn(Z, lab)
        self.pend[lab].append(Z)


class Median:
    def __init__(self, Zc, yc, K, between):
        self.K, self.between = K, between
        self.G, self.n = np.zeros((Zc.shape[1],) * 2), 0.0
        self.q = [deque(maxlen=K) for _ in range(LS.K)]
        for c in range(LS.K):
            self._add(Zc[yc == c], c)
        self._fit()

    def _add(self, Z, lab):
        m = Z.mean(0)
        R = Z - m
        self.G = DECAY * self.G + R.T @ R
        self.n = DECAY * self.n + len(Z) - 1
        self.q[lab].append(m)

    def _fit(self):
        m = np.stack([np.median(np.stack(q), axis=0) for q in self.q])
        Sw, N = self.G / self.n, self.n
        if self.between:
            dev = np.concatenate([np.stack(q) - m[c] for c, q in enumerate(self.q) if len(q) > 1] or [np.zeros((0, m.shape[1]))])
            if len(dev):
                Sw = Sw + dev.T @ dev / len(dev)
        self.w, self.b = oas_solve(Sw, N, m)

    def learn(self, Z, lab):
        self._add(Z, lab)
        self._fit()

    def scores(self, Z):
        return Z @ self.w.T + self.b


def make(name, Zc, yc):
    if name == 'plain':
        return Plain(Zc, yc)
    if name == 'gate':
        return Gate(Zc, yc)
    return Median(Zc, yc, int(name.lstrip('medb')), name.startswith('medb'))


def run(learner, feed, Xc_raw, yc, blocks, score_from, cue_blocks, rng):
    """lda_context2.run with a pluggable learner (same order of random draws)"""
    p = dict(C2.BASE, **C2.CONDS[feed])
    mu, sd = Xc_raw.mean(0), Xc_raw.std(0)
    mdl = make(learner, (Xc_raw - mu) / sd, yc)
    queue, rows = [], []
    for b, (X, y) in enumerate(blocks):
        y = np.asarray(y).astype(np.int64)
        Z = (np.asarray(X, dtype=np.float64) - mu) / sd
        _, scored = LG.split(y, [0], 2) if b in score_from else (None, np.arange(len(y)))
        smask = np.zeros(len(y), bool)
        smask[scored] = True
        cued = set()
        if p['cue'] and b in cue_blocks:
            a1, _ = LG.split(y, [0], 1)
            for i in sorted(set(a1 // W * W)):
                mdl.learn(Z[i:i + W], int(y[i]))
                cued.add(int(i))
        ok = np.zeros(len(y), bool)
        for i in range(0, len(y), W):
            while queue and queue[0][0] <= 0:
                _, Zq, lq = queue.pop(0)
                mdl.learn(Zq, lq)
            queue = [(d - 1, z, l) for d, z, l in queue]
            sl = slice(i, i + W)
            t = int(y[i])
            s = mdl.scores(Z[sl])
            if p['m'] < LS.K:
                allow = np.concatenate([[t], rng.choice([k for k in range(LS.K) if k != t], p['m'] - 1, replace=False)])
                mask = np.full(LS.K, -np.inf)
                mask[allow] = 0.0
                s = s + mask
            pr = np.argmax(s, axis=1)
            ok[sl] = pr == t
            cmd = int(np.argmax(np.bincount(pr, minlength=LS.K)))
            if i in cued or cmd == REST:
                continue
            if rng.random() >= p['c']:
                continue
            lab = cmd if cmd == t else (t if rng.random() < p['r'] else None)
            if lab is None:
                continue
            if rng.random() < p['e']:
                lab = int(rng.choice([k for k in range(LS.K) if k != lab]))
            if p['D']:
                queue.append((p['D'], Z[sl], lab))
            else:
                mdl.learn(Z[sl], lab)
        rows.append(dict(block=b, acc=ok[smask].mean(), n=int(smask.sum())))
    return rows


def job_dev(subject, shift):
    Xc_raw, yc, blocks, _ = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    out = []
    for L in LEARNERS:
        for f in FEED:
            for seed in SEEDS:
                rng = np.random.default_rng(seed * 100003 + subject)
                out += [dict(data='dev', comp=f'shift{shift:g}', subject=subject, seed=seed, learner=L, feed=f, **r)
                        for r in run(L, f, Xc_raw, yc, blocks, range(len(blocks)), range(len(blocks)), rng)]
    return out


def job_ext(data, p):
    import external_check as EC
    import leaf_external as LE
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), LS.PREC), None)
    d1 = EC.Session(data, p, 1, 1)
    d2 = [EC.Session(data, p, 2, b) for b in (1, 2)]
    f, Xc, yc, _ = LE.calibrate(d1, p, 0, P.load_pretrain(S.DATASETS['arm_position'][0]))
    if f is None:
        return []
    blocks = EC.stream(d2, 5, EC.ROW1, 0)
    out = []
    for L in LEARNERS:
        for fd in FEED:
            for seed in SEEDS:
                rng = np.random.default_rng(seed * 100003 + p)
                out += [dict(data='ext', comp='A1', subject=p, seed=seed, learner=L, feed=fd, **r)
                        for r in run(L, fd, Xc, yc, blocks, [0], [0], rng)]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--data', default='/data')
    args = ap.parse_args()
    import check_features_c as FC
    import lda_robust as M
    FC.lib()
    pd.set_option('display.width', 250)
    tasks = [delayed(M.job_dev)(s, sh) for sh in (0.0, 0.5) for s in range(20)]
    tasks += [delayed(M.job_ext)(args.data, p) for p in range(1, 9)]
    res = Parallel(n_jobs=args.jobs, verbose=5)(tasks)
    df = pd.DataFrame([r for rs in res for r in rs])
    df.to_csv(os.path.join(OUT, 'lda_robust.csv'), index=False, float_format='%.4f')
    a = df[((df.data == 'dev') & (df.block >= 1)) | ((df.data == 'ext') & (df.block == 1))]
    ps = (a.groupby(['comp', 'feed', 'learner', 'subject']).acc.mean() * 100).unstack('learner')
    rows = []
    for (comp, fd), g in ps.groupby(level=[0, 1]):
        for L in LEARNERS:
            d = g[L] - g['plain']
            m, lo, hi = LS.ci(d) if np.any(d != 0) else (0.0, 0.0, 0.0)
            rows.append(dict(comp=comp, feed=fd, learner=L, acc=g[L].mean(), vs_plain=m, lo=lo, hi=hi, worst=d.min()))
    sm = pd.DataFrame(rows)
    sm.to_csv(os.path.join(OUT, 'lda_robust_summary.csv'), index=False, float_format='%.4g')
    for comp in sm.comp.unique():
        print(comp)
        print(sm[sm.comp == comp].pivot(index='feed', columns='learner', values='acc').loc[FEED, LEARNERS].round(1).to_string())


if __name__ == '__main__':
    main()
