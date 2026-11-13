"""A small neural network against the shrinkage LDA on real cross-session data (NinaPro DB6), report 35.38.
PC only, exploratory. Question asked by reviewers: why an LDA and not a neural network on the MCU?

Same data, trials, probes and protocol as db6_sim.py / db6_adj.py: 10 subjects, 8 classes, first electrode ring,
features.c (80 features), day-1 z-score, Q5.10 inputs; day 1 = D1T1 (all 12 repetitions); each later session: cued
pass = repetition 1 of every class (80 windows), probe = repetitions 7-12, scored on the same session (after its
cued pass) and on the NEXT session (before its cued pass, no time adjacency). No task labels here: the question is
the model class under the per-donning calibration budget.

Network: MLP 80 -> 64 -> 32 -> 8, ReLU, softmax cross-entropy, L2 1e-4, Adam (lr 1e-3, batch 32), 300 epochs on
day 1, written in numpy (no deep-learning library in the container). Settings fixed before running, not tuned.
Variants (3 seeds each):
  mlp_fixed      trained on day 1, never updated
  mlp_ft         fine-tuned on every session's cued pass (all weights, 30 epochs, lr 1e-3, batch 16), sequentially
                 (on the MCU: backpropagation over 80 windows x 30 epochs)
  mlp_ft_cum     the same, fine-tuned on all cued passes so far (on the MCU: 80 windows x 80 int16 = 12.5 KB kept
                 per session)
  mlp_head_lda   hidden layers frozen after day 1; the output layer replaced by our running-sum shrinkage LDA on
                 the 32 z-scored hidden activations (day-1 statistics), updated with every cued pass (forgetting
                 0.97 per learned trial, as cue1): a closed-form update like ours
  mlp_retrain    retrained from scratch on day 1 + all cued passes so far (the same information as cue1; not
                 feasible on the MCU; reference)
LDA (from db6_sim.py, recomputed here): lda_fixed, lda_cue1 (running sums + every cued pass).
Decision rule, fixed before running (per subject mean over sessions, 10 subjects, paired 95 % t CI):
  R13 the LDA is kept as the model if, on BOTH the same-session and the next-session probes, the best of the three
      MCU-updatable network variants (mlp_ft, mlp_ft_cum, mlp_head_lda; the best chosen per probe type, which
      favours the network) is not better than lda_cue1 by >= 2 points with a CI above 0. Otherwise the thesis has
      to adopt or discuss the network. mlp_retrain is reported, not part of the rule.
Also: parameters, Flash (float32 / int8), activation RAM, MACs per window, and the update cost of each variant.
Writes results/nn_compare.csv, nn_compare_summary.txt.
Usage (in the container, /db6 = D:\\db6_compact): python src/nn_compare.py [--jobs 10]
"""
import argparse
import os
import sys

os.environ.setdefault('OMP_NUM_THREADS', '1')        # 10 jobs in parallel: one BLAS thread each
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db6_sim as D  # noqa: E402

OUT = D.OUT
H1, H2 = 64, 32
L2, LR = 1e-4, 1e-3
EP0, BS0, EPF, BSF = 300, 32, 30, 16
SEEDS = (0, 1, 2)


class MLP:
    def __init__(self, seed, sizes=(80, H1, H2, D.K)):
        r = np.random.default_rng(seed)
        self.W = [r.normal(0, np.sqrt(2.0 / a), (a, b)) for a, b in zip(sizes[:-1], sizes[1:])]
        self.b = [np.zeros(b) for b in sizes[1:]]
        self.rng = r
        self._adam()

    def _adam(self):
        self.m = [np.zeros_like(p) for p in self.W + self.b]
        self.v = [np.zeros_like(p) for p in self.W + self.b]
        self.t = 0

    def hidden(self, X):
        h = X
        for W, b in zip(self.W[:-1], self.b[:-1]):
            h = np.maximum(h @ W + b, 0.0)
        return h

    def scores(self, X):
        return self.hidden(X) @ self.W[-1] + self.b[-1]

    def fit(self, X, y, epochs, bs, lr=LR, reset_adam=True):
        if reset_adam:
            self._adam()
        n = len(X)
        for _ in range(epochs):
            idx = self.rng.permutation(n)
            for s in range(0, n, bs):
                j = idx[s:s + bs]
                self._step(X[j], y[j], lr)
        return self

    def _step(self, X, y, lr):
        acts = [X]
        h = X
        for W, b in zip(self.W[:-1], self.b[:-1]):
            h = np.maximum(h @ W + b, 0.0)
            acts.append(h)
        z = h @ self.W[-1] + self.b[-1]
        p = np.exp(z - z.max(1, keepdims=True))
        p /= p.sum(1, keepdims=True)
        g = p
        g[np.arange(len(y)), y] -= 1.0
        g /= len(y)
        gW, gb = [None] * len(self.W), [None] * len(self.b)
        for k in range(len(self.W) - 1, -1, -1):
            gW[k] = acts[k].T @ g + L2 * self.W[k]
            gb[k] = g.sum(0)
            if k:
                g = (g @ self.W[k].T) * (acts[k] > 0)
        self.t += 1
        params = self.W + self.b
        grads = gW + gb
        for i, (pm, gr) in enumerate(zip(params, grads)):
            self.m[i] = 0.9 * self.m[i] + 0.1 * gr
            self.v[i] = 0.999 * self.v[i] + 0.001 * gr * gr
            mh = self.m[i] / (1 - 0.9 ** self.t)
            vh = self.v[i] / (1 - 0.999 ** self.t)
            pm -= lr * mh / (np.sqrt(vh) + 1e-8)

    def copy(self):
        o = MLP.__new__(MLP)
        o.W = [w.copy() for w in self.W]
        o.b = [b.copy() for b in self.b]
        o.rng = np.random.default_rng(self.rng.integers(1 << 31))
        o._adam()
        return o


class HeadLDA:
    """frozen MLP hidden layers + running-sum shrinkage LDA on the z-scored hidden activations"""

    def __init__(self, mlp, X0, y0):
        self.mlp = mlp
        H = mlp.hidden(X0)
        self.mu, self.sd = H.mean(0), H.std(0)
        self.sd[self.sd < 1e-6] = np.inf
        self.lda = D.RunLDA(H2)
        self.lda.add(self.z(X0), y0)
        self.lda.fit()

    def z(self, X):
        return (self.mlp.hidden(X) - self.mu) / self.sd

    def learn_pass(self, X, y):
        for c in range(D.K):
            if np.any(y == c):
                self.lda.learn(self.z(X[y == c]), c, fit=False)
        self.lda.fit()

    def scores(self, X):
        return self.lda.scores(self.z(X))


def acc(m, X, y):
    return float(np.mean(np.argmax(m.scores(X), 1) == y) * 100)


def load(subject):
    sess = [D.trials(os.path.join(D.FEAT, f'S{subject}_D{d}_T{t}.npz')) for d, t in D.SESSIONS]
    F0, tr0, _ = sess[0]
    X0, y0 = D.cat(F0, tr0, range(D.N_REP))
    m0, s0 = X0.mean(0), X0.std(0)
    bad = ~np.isfinite(s0) | (s0 == 0)
    m0[bad], s0[bad] = 0.0, np.inf
    data = []
    for (d, t), (F, tr, _) in zip(D.SESSIONS[1:], sess[1:]):
        if any(i is None for c in range(D.K) for i in tr[c]) or len(tr[D.REST]) < D.N_REP:
            continue
        Z = (F - m0) / s0
        Zc, yc = D.cat(Z, tr, D.CUE)
        Zp, yp = D.cat(Z, tr, D.PROBE)
        data.append(dict(day=d, t=t, Xc=D.q(Zc), yc=yc, Zc=Zc, Xp=D.q(Zp), yp=yp))
    return D.q((X0 - m0) / s0), (X0 - m0) / s0, y0, data


def job(subject):
    X0, Z0, y0, data = load(subject)
    out = []

    def rec(method, seed, b, m):
        same = acc(m, data[b]['Xp'], data[b]['yp'])
        nxt = acc(m, data[b + 1]['Xp'], data[b + 1]['yp']) if b + 1 < len(data) else np.nan
        out.append(dict(subject=subject, session=b + 1, day=data[b]['day'], t=data[b]['t'], method=method, seed=seed,
                        same=same, next=nxt))

    # LDA (as db6_sim: Z in, q() inside RunLDA)
    base = D.RunLDA()
    base.add(Z0, y0)
    base.fit()
    cum = base.copy()
    for b, Dd in enumerate(data):
        rec('lda_fixed', 0, b, base)
        for c in range(D.K):
            cum.learn(Dd['Zc'][Dd['yc'] == c], c, fit=False)
        cum.fit()
        rec('lda_cue1', 0, b, cum)
    for seed in SEEDS:
        net = MLP(seed * 1000 + subject).fit(X0, y0, EP0, BS0)
        ft, ftc, head = net.copy(), net.copy(), HeadLDA(net, X0, y0)
        Xs, ys = [X0], [y0]
        cues_X, cues_y = [], []
        for b, Dd in enumerate(data):
            rec('mlp_fixed', seed, b, net)
            ft.fit(Dd['Xc'], Dd['yc'], EPF, BSF)
            rec('mlp_ft', seed, b, ft)
            cues_X.append(Dd['Xc'])
            cues_y.append(Dd['yc'])
            ftc.fit(np.concatenate(cues_X), np.concatenate(cues_y), EPF, BSF)
            rec('mlp_ft_cum', seed, b, ftc)
            head.learn_pass(Dd['Xc'], Dd['yc'])
            rec('mlp_head_lda', seed, b, head)
            Xs.append(Dd['Xc'])
            ys.append(Dd['yc'])
            re = MLP(seed * 1000 + subject + 7).fit(np.concatenate(Xs), np.concatenate(ys), EP0, BS0)
            rec('mlp_retrain', seed, b, re)
    return out


def costs():
    sizes = (80, H1, H2, D.K)
    params = sum(a * b + b for a, b in zip(sizes[:-1], sizes[1:]))
    macs = sum(a * b for a, b in zip(sizes[:-1], sizes[1:]))
    act = max(sizes) * 2 * 4
    rows = [('MLP 80-64-32-8', params, params * 4, params, act, macs,
             f'backprop: ~3 x {macs:,} MACs x 80 windows x {EPF} epochs = {3 * macs * 80 * EPF / 1e6:.1f} M MACs per cued pass'),
            ('LDA (ldacal.c)', 80 * 8 + 8, (80 * 8 + 8) * 4, 80 * 8 + 8, 8 * 4, 80 * 8,
             'closed form: running sums (80 x 80 + 8 x 80 + 8 floats = 27.5 KB, 1 KB = 1024 B) + one 80 x 80 solve (ld_fit 3.9 ms on the board)'),
            ('MLP hidden + LDA head', params, params * 4, params, act, macs,
             f'closed form on 32 activations: sums 32 x 32 + 8 x 32 + 8 floats = {(32 * 32 + 8 * 32 + 8) * 4 / 1024:.1f} KB')]
    return pd.DataFrame(rows, columns=['model', 'params', 'flash_float32_B', 'flash_int8_B', 'activations_B',
                                       'MACs_per_window', 'update'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=10)
    args = ap.parse_args()
    rows = Parallel(n_jobs=args.jobs)(delayed(job)(s) for s in range(1, 11))
    df = pd.DataFrame([r for rr in rows for r in rr])
    df.to_csv(os.path.join(OUT, 'nn_compare.csv'), index=False)
    lines = []

    def p(s=''):
        lines.append(s)
        print(s, flush=True)

    per = {k: df.groupby(['method', 'subject'])[k].mean().unstack('subject') for k in ('same', 'next')}
    p('mean accuracy %, 8 classes, 10 subjects (networks: mean of 3 seeds)')
    p(f"  {'method':14s} {'same session':>13s} {'next session':>13s}")
    for m in ['lda_fixed', 'lda_cue1', 'mlp_fixed', 'mlp_ft', 'mlp_ft_cum', 'mlp_head_lda', 'mlp_retrain']:
        p(f"  {m:14s} {per['same'].loc[m].mean():13.2f} {per['next'].loc[m].mean():13.2f}")
    p('\npaired differences against lda_cue1 (95 % t CI, 10 subjects)')
    verdict = True
    for k in ('same', 'next'):
        best = max(['mlp_ft', 'mlp_ft_cum', 'mlp_head_lda'], key=lambda m: per[k].loc[m].mean())
        for m in ['mlp_fixed', 'mlp_ft', 'mlp_ft_cum', 'mlp_head_lda', 'mlp_retrain']:
            d = per[k].loc[m] - per[k].loc['lda_cue1']
            mm, lo, hi = D.ci(d)
            tag = '  <- best MCU-updatable' if m == best else ''
            p(f'  [{k}] {m:13s} - lda_cue1 = {mm:+.2f} ({lo:+.2f}, {hi:+.2f}), {int((d > 0).sum())}/10 higher{tag}')
        d = per[k].loc[best] - per[k].loc['lda_cue1']
        mm, lo, hi = D.ci(d)
        if mm >= 2 and lo > 0:
            verdict = False
    p(f"\nR13: {'PASS - the LDA is kept' if verdict else 'FAIL - a network is better by >= 2 points: adopt or discuss it'}")
    c = costs()
    p('\nmodel cost on the MCU (analytic)')
    p(c.to_string(index=False))
    with open(os.path.join(OUT, 'nn_compare_summary.txt'), 'w') as f:
        f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
