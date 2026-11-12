"""Rejection rule for the LDA main line (report 35.12). PC only; model = the MCU form (ldacal.c math), setting
cum_T2 of lda_main.py (two cued passes learned, labels accumulated, anchor z-score), scoring as leaf_guard.py.

Report 35.11: the LDA posterior is over-confident, so the firmware's 'top share >= 0.6' cannot be reused. A
temperature only rescales the posterior; what matters is how well a rule RANKS windows. Rules, all from the six
discriminant values s_c = x.w_c + b_c that ld_scores already gives (dist needs one more quadratic form):
  post    largest posterior (softmax of s)                 margin  s(1) - s(2), the log-odds of the two best classes
  dist    minus the squared Mahalanobis distance to the mean of the predicted class (x^T C^-1 x - 2 s(1))
  both    accept only if margin AND dist pass (each at its own threshold; same quantile for both)
Reference: the fixed one-shot forest with its vote share (the frozen firmware's rule), same windows.

1. Ranking (dev shifts 0 / 0.5, Kyranou A1), active gestures: accuracy of the accepted windows when the best
   90 / 80 / 70 / 50 % by the rule are kept (threshold per subject = oracle quantile: this compares the rules, it
   is not a deployable threshold).
2. Deployable thresholds for margin, target = keep 90 % of the active windows:
   loso    one fixed threshold from the other subjects (dev: leave one out; Kyranou: the dev threshold)
   anchor  per session, from the cued start-up windows themselves: the q-th percentile of their margins (the
           windows the model was fitted on, so they look easier than later windows; q is chosen leave-one-out
           on dev so that 90 % of the later active windows pass)
   Reported: realised coverage and accepted accuracy per subject (mean, min).
3. Unknown movements (dev shift 0): one active gesture h is left out of all labels (5-class LDA) and plays the
   movement the system was never taught. Per rule: AUROC known-vs-unknown, and at the threshold that keeps 90 % of
   the known active windows, the share of unknown windows that would still give a command (accepted and not
   predicted Rest). Mean over the 5 choices of h. Without rejection every unknown window not called Rest triggers.
Writes results/lda_reject_rank.csv, lda_reject_thr.csv, lda_reject_open.csv.
Usage (container; Kyranou at /data): python src/lda_reject.py [--jobs 19]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.stats import rankdata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leaf_guard as LG  # noqa: E402
import leaf_sweep as LS  # noqa: E402
import lda_main as LM  # noqa: E402
import pipeline as P  # noqa: E402
import selfcal_sweep as S  # noqa: E402
import zscore_sweep as ZW  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
REST = 5
RULES = ['post', 'margin', 'dist']
KEEP = [0.9, 0.8, 0.7, 0.5]


def q(X):
    return P.quantize(X).astype(np.float64) / (1 << P.Q_SHIFT)


class Lda:
    """ldacal.c math in float64, any subset of classes"""

    def __init__(self):
        self.G, self.s, self.n = np.zeros((80, 80)), np.zeros((LS.K, 80)), np.zeros(LS.K)

    def add(self, X, y):
        X = q(X)
        self.G += X.T @ X
        for c in np.unique(y):
            self.s[c] += X[y == c].sum(0)
            self.n[c] += np.sum(y == c)

    def fit(self):
        self.cls = np.flatnonzero(self.n > 0)
        d, N = 80, self.n.sum()
        m = self.s[self.cls] / self.n[self.cls, None]
        Sw = (self.G - (m.T * self.n[self.cls]) @ m) / N
        mu = np.trace(Sw) / d
        alpha = np.mean(Sw ** 2)
        num, den = alpha + mu ** 2, (N + 1.0) * (alpha - mu ** 2 / d)
        rho = 1.0 if den == 0 else min(num / den, 1.0)
        self.Ci = np.linalg.inv((1 - rho) * Sw + rho * mu * np.eye(d))
        self.w = m @ self.Ci
        self.b = -0.5 * np.sum(m * self.w, axis=1)

    def rules(self, X):
        """pred (class id) and the rule values, larger = more confident"""
        X = q(X)
        s = X @ self.w.T + self.b
        o = np.sort(s, axis=1)
        e = np.exp(s - o[:, -1:])
        quad = np.einsum('nd,de,ne->n', X, self.Ci, X)
        return self.cls[np.argmax(s, axis=1)], dict(post=e.max(1) / e.sum(1), margin=o[:, -1] - o[:, -2],
                                                    dist=-(quad - 2 * o[:, -1]))


def stream(Xc_raw, yc, blk, skip0, drop=None):
    """cum_T2 over the blocks -> per scored window: y, pred, rules; and the rule values of the anchors (pooled)"""
    keep = (lambda y: y != drop) if drop is not None else (lambda y: np.ones(len(y), bool))
    mdl = Lda()
    mu0, sd0 = Xc_raw.mean(0), Xc_raw.std(0)
    mdl.add(((Xc_raw - mu0) / sd0)[keep(yc)], yc[keep(yc)])
    Y, Pp, R, A = [], [], {r: [] for r in RULES}, {r: [] for r in RULES}
    mu = sd = None
    for b, (Xa, ya, Xu, yu) in enumerate(blk):
        if len(ya):
            mu, sd = Xa.mean(0), Xa.std(0)
            Za = ((Xa - mu) / sd)[keep(ya)]
            mdl.add(Za, ya[keep(ya)])
            mdl.fit()
            _, ra = mdl.rules(Za)
            act = ya[keep(ya)] != REST
            if not (skip0 and b == 0):
                for r in RULES:
                    A[r].append(ra[r][act])
        if skip0 and b == 0:
            continue
        p, rv = mdl.rules((Xu - mu) / sd)
        Y.append(yu)
        Pp.append(p)
        for r in RULES:
            R[r].append(rv[r])
    cat = np.concatenate
    return cat(Y), cat(Pp), {r: cat(R[r]) for r in RULES}, {r: cat(A[r]) for r in RULES}


def acc_at(conf, ok, keep):
    """accuracy of the best `keep` share of the windows by conf (ties: all windows at the threshold are kept)"""
    thr = np.quantile(conf, 1 - keep)
    m = conf >= thr
    return ok[m].mean() * 100, m.mean() * 100


def auroc(pos, neg):
    r = rankdata(np.concatenate([pos, neg]))
    return (r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def forest(mdl, Xc_raw, blk, skip0):
    conf, pred = LM.forest_conf(mdl, Xc_raw, blk)
    k = 1 if skip0 else 0
    return np.concatenate(conf[k:]), np.concatenate(pred[k:])


def analyse(tag, Xc_raw, yc, blk, skip0, f_mdl, open_set):
    y, p, rv, anc = stream(Xc_raw, yc, blk, skip0)
    act = y != REST
    ok = p == y
    rank, raw, opn = [], [], []
    fc, fp = forest(f_mdl, Xc_raw, blk, skip0)
    for name, conf, good in [(r, rv[r], ok) for r in RULES] + [('forest_share', fc, fp == y)]:
        for kp in KEEP:
            a, cov = acc_at(conf[act], good[act], kp)
            rank.append(dict(**tag, rule=name, keep=kp, acc=a, coverage=cov, acc_all=good[act].mean() * 100))
    # 'both': margin and dist at the same quantile each
    for kp in KEEP:
        best = None
        for qq in np.linspace(0, 0.6, 61):                   # per-rule quantile so that the AND keeps `kp`
            m = (rv['margin'] >= np.quantile(rv['margin'][act], qq)) & (rv['dist'] >= np.quantile(rv['dist'][act], qq))
            if m[act].mean() <= kp:
                best = m
                break
        if best is not None and best[act].any():
            rank.append(dict(**tag, rule='both', keep=kp, acc=ok[act & best].mean() * 100,
                             coverage=best[act].mean() * 100, acc_all=ok[act].mean() * 100))
    raw = dict(tag=tag, margin=rv['margin'][act], ok=ok[act], anchor=anc['margin'])
    if open_set:
        for h in range(5):
            yh, ph, rh, _ = stream(Xc_raw, yc, blk, skip0, drop=h)
            known, unk = (yh != h) & (yh != REST), yh == h
            trig0 = np.mean(ph[unk] != REST) * 100
            for r in RULES + ['both']:
                if r == 'both':
                    row = dict(**tag, held_out=h, rule=r, auroc=np.nan)
                    m = None
                    for qq in np.linspace(0, 0.6, 61):
                        mm = (rh['margin'] >= np.quantile(rh['margin'][known], qq)) & \
                             (rh['dist'] >= np.quantile(rh['dist'][known], qq))
                        if mm[known].mean() <= 0.9:
                            m = mm
                            break
                else:
                    row = dict(**tag, held_out=h, rule=r, auroc=auroc(rh[r][known], rh[r][unk]))
                    m = rh[r] >= np.quantile(rh[r][known], 0.1)
                row.update(known_cov=m[known].mean() * 100, known_acc=np.mean(ph[known & m] == yh[known & m]) * 100,
                           unknown_trigger=np.mean(m[unk] & (ph[unk] != REST)) * 100, unknown_trigger_noreject=trig0)
                opn.append(row)
    return rank, raw, opn


def job_dev(subject, shift):
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), LS.PREC), None)
    Xc_raw, yc, blocks, _ = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    blk = LG.blocks_for(blocks, 'T2', 2, range(len(blocks)))
    np.random.seed(subject)
    mu, sd = Xc_raw.mean(0), Xc_raw.std(0)
    f = LS.one_shot((Xc_raw - mu) / sd, yc, P.load_pretrain(S.DATASETS['arm_position'][0]))
    return analyse(dict(data='dev', comp=f'shift{shift:g}', subject=subject), Xc_raw, yc, blk, True, f, shift == 0)


def job_ext(data, p):
    import external_check as EC
    import leaf_external as LE
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), LS.PREC), None)
    d1, d2 = EC.Session(data, p, 1, 1), [EC.Session(data, p, 2, b) for b in (1, 2)]
    f, Xc, yc, _ = LE.calibrate(d1, p, 0, P.load_pretrain(S.DATASETS['arm_position'][0]))
    if f is None:
        return [], None, []
    blk = LG.blocks_for(EC.stream(d2, 5, EC.ROW1, 0), 'T2', 2, [0])
    return analyse(dict(data='ext', comp='A1', subject=p), Xc, yc, blk, False, f, False)


def thresholds(raws):
    """deployable thresholds for margin, target 90 % of the active windows"""
    dev = [r for r in raws if r['tag']['data'] == 'dev' and r['tag']['comp'] == 'shift0']
    rows = []

    def q_for(group):                                        # anchor percentile so that pooled 90 % pass
        best, err = None, 1e9
        for qq in np.arange(0, 60.5, 0.5):
            cov = np.mean(np.concatenate([g['margin'] >= np.percentile(g['anchor'], qq) for g in group]))
            if abs(cov - 0.9) < err:
                best, err = qq, abs(cov - 0.9)
        return best

    for r in raws:
        t = r['tag']
        others = [g for g in dev if not (t['data'] == 'dev' and g['tag']['subject'] == t['subject'])]
        thr = np.quantile(np.concatenate([g['margin'] for g in others]), 0.1)
        qq = q_for(others)
        for name, th in (('loso', thr), ('anchor', np.percentile(r['anchor'], qq))):
            m = r['margin'] >= th
            rows.append(dict(**t, method=name, threshold=th, anchor_pct=qq if name == 'anchor' else np.nan,
                             coverage=m.mean() * 100, acc=r['ok'][m].mean() * 100 if m.any() else np.nan,
                             acc_all=r['ok'].mean() * 100))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--data', default='/data')
    args = ap.parse_args()
    import check_features_c as FC
    import lda_reject as M
    FC.lib()
    pd.set_option('display.width', 250)
    tasks = [delayed(M.job_dev)(s, sh) for sh in (0.0, 0.5) for s in range(20)]
    tasks += [delayed(M.job_ext)(args.data, p) for p in range(1, 9)]
    res = [r for r in Parallel(n_jobs=args.jobs, verbose=5)(tasks) if r[1] is not None]
    rank = pd.DataFrame([x for r in res for x in r[0]])
    opn = pd.DataFrame([x for r in res for x in r[2]])
    thr = thresholds([r[1] for r in res])
    rank.to_csv(os.path.join(OUT, 'lda_reject_rank.csv'), index=False, float_format='%.4g')
    thr.to_csv(os.path.join(OUT, 'lda_reject_thr.csv'), index=False, float_format='%.5g')
    opn.to_csv(os.path.join(OUT, 'lda_reject_open.csv'), index=False, float_format='%.4g')
    print('accuracy of the accepted active windows (mean over subjects); acc_all = no rejection')
    print(rank.groupby(['data', 'comp', 'rule', 'keep'])[['acc', 'coverage', 'acc_all']].mean().unstack('keep')
          .round(1).to_string())
    print('\ndeployable margin thresholds (target coverage 90 %)')
    print(thr.groupby(['data', 'comp', 'method']).agg(threshold=('threshold', 'mean'), pct=('anchor_pct', 'mean'),
                                                      cov_mean=('coverage', 'mean'), cov_min=('coverage', 'min'),
                                                      cov_max=('coverage', 'max'), acc=('acc', 'mean'),
                                                      acc_min=('acc', 'min'), acc_all=('acc_all', 'mean')).round(2).to_string())
    print('\nunknown movement (one gesture never taught), mean over held-out gesture and subject')
    print(opn.groupby('rule')[['auroc', 'known_cov', 'known_acc', 'unknown_trigger', 'unknown_trigger_noreject']].mean()
          .round(2).to_string())
    print(opn.groupby(['held_out', 'rule']).unknown_trigger.mean().unstack('rule').round(1).to_string())


if __name__ == '__main__':
    main()
