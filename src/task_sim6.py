"""Published baselines from the papers themselves (report 35.30). PC only, exploratory.

A. Short recalibration by covariate shift adaptation, Vidovic et al. 2016 (IEEE TNSRE 24(9):961-970, eq. 6-7, sec. II-C,
   III-B): the day-1 LDA parameters are shrunk towards those of a small calibration set of the current session,
       mu_c = (1 - tau) mu_train,c + tau mu_cal,c        Sigma = (1 - lambda) Sigma_train + lambda Sigma_cal
   LDAMA tau 0.7, lambda 0; LDACMA tau 0.8, lambda 0.8 (their subject-independent grid-search optimum); LDAnew
   tau = lambda = 1 (calibration set only). Always from the day-1 model (LDACMA, not their LDAFA). Calibration set =
   our one cued pass (trial 0 of every gesture, 10 windows each; their online calibration was one 4 s repetition of
   every movement). Pooled covariance (their LDA), Q5.10 features in the day-1 z-score as ours; solved with OAS
   shrinkage as ours (80 features, 60 calibration windows: the calibration covariance alone is singular), N for OAS =
   (1 - lambda) N_train + lambda N_cal. Also the best (tau, lambda) of a 0.1-step grid chosen ON THIS DATA (shift 0.5),
   an optimistic upper bound for the baseline. Probe = trials 3-4 of every gesture of each block, as task_sim.py.
   Compared per subject with task_sim4.csv (same probe, blocks 1-10): cue1 (our running sums, no task labels) and
   cue1_soft (one cued pass + soft task labels), e = 0.
B. Confidence-based rejection, Scheme et al. 2013 (IEEE TBME 60(6), eq. 11-13, sec. III-A): confidence = softmax of
   the LDA discriminants; below 0.97 the window is no motion. Their eq. 15 also relabels active windows whose mean
   absolute value is below mu_NM + 3 sigma_NM as no motion: the same idea as our activity gate, with another
   threshold. Front ends on task_sim4's closed loop (p_dev 0.1, no wrong task labels): none, act (ours: geometric
   mean of the Rest median and the smallest gesture median of day 1), act_s (threshold mu + 3 sigma of the day-1 Rest
   activity), rej (0.97). Without a cued pass (P+N labels: the false-command stress case) and with one cued pass +
   soft labels.
Decision rules, fixed before running (shift 0.5, blocks 1-10, per subject, 95 % CI):
  R6 'one cued pass + soft task labels beats the published short recalibration' only if cue1_soft - LDACMA (paper
     parameters) >= +1 point with CI above 0; also reported against the grid-best (tau, lambda).
  R7 our activity-gate threshold is kept over Scheme's only if, without a cued pass, false commands from Rest are not
     higher than with act_s and the probe accuracy is not lower by more than 0.5 points; confidence rejection (0.97)
     is reported next to them.
Writes results/task_sim6_vidovic.csv, task_sim6_frontend.csv and task_sim6_summary.txt.
Usage (in the container): python src/task_sim6.py [--jobs 19]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lda_anchor as LA  # noqa: E402
import lda_robust as LR  # noqa: E402
import leaf_guard as LG  # noqa: E402
import leaf_sweep as LS  # noqa: E402
import pipeline as P  # noqa: E402
import task_sim as T  # noqa: E402
import task_sim2 as T2  # noqa: E402
import task_sim4 as T4  # noqa: E402
import zscore_sweep as ZW  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
REST = T.REST
GRID = [round(x, 1) for x in np.arange(0, 1.01, 0.1)]
PAPER = {'LDAMA': (0.7, 0.0), 'LDACMA': (0.8, 0.8), 'LDAnew': (1.0, 1.0)}
FRONT = {'none': dict(), 'act': dict(act=True), 'act_s': dict(act=True, thr='scheme'), 'rej': dict(rej=0.97)}


def stats(Zq, y):
    mu = np.stack([Zq[y == c].mean(0) for c in range(LS.K)])
    R = Zq - mu[y]
    return mu, R.T @ R / len(Zq), float(len(Zq))


def vidovic_job(subject, shift):
    Xc_raw, yc, blocks, _ = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    m0, s0 = Xc_raw.mean(0), Xc_raw.std(0)
    mu_t, S_t, n_t = stats(LA.OasLDA.q((Xc_raw - m0) / s0), yc)
    out = []
    for b, (X, y) in enumerate(blocks):
        y = np.asarray(y).astype(np.int64)
        Z = (np.asarray(X, dtype=np.float64) - m0) / s0
        tr = [LG.trials(y, c) for c in range(LS.K)]
        ci = np.concatenate([tr[c][0] for c in range(LS.K)])
        pi = np.concatenate([i for c in range(LS.K) for i in tr[c][3:5]])
        mu_c, S_c, n_c = stats(LA.OasLDA.q(Z[ci]), y[ci])
        Zp = LA.OasLDA.q(Z[pi])
        for tau in GRID:
            for lam in GRID:
                w, bb = LR.oas_solve((1 - lam) * S_t + lam * S_c, (1 - lam) * n_t + lam * n_c, (1 - tau) * mu_t + tau * mu_c)
                acc = float(np.mean(np.argmax(Zp @ w.T + bb, axis=1) == y[pi]) * 100)
                out.append(dict(subject=subject, shift=shift, block=b, tau=tau, lam=lam, acc=acc))
    return out


def front_job(subject, shift, seed):
    Xc_raw, yc, blocks, _ = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    mu, sd = Xc_raw.mean(0), Xc_raw.std(0)
    Zc = (Xc_raw - mu) / sd
    act_c = Xc_raw[:, T2.MAV].sum(1)
    med = [np.median(act_c[yc == c]) for c in range(LS.K)]
    thr = {'gm': float(np.sqrt(med[REST] * min(med[:5]))),
           'scheme': float(act_c[yc == REST].mean() + 3 * act_c[yc == REST].std())}
    data = []
    for X, y in blocks:
        y = np.asarray(y).astype(np.int64)
        X = np.asarray(X, dtype=np.float64)
        Z = (X - mu) / sd
        A = X[:, T2.MAV].sum(1)
        tr = [LG.trials(y, c) for c in range(LS.K)]
        pools = [[Z[i] for i in tr[c][:3]] for c in range(LS.K)]
        apools = [[A[i] for i in tr[c][:3]] for c in range(LS.K)]
        pi = np.concatenate([i for c in range(LS.K) for i in tr[c][3:5]])
        data.append((pools, apools, Z[pi], y[pi], A[pi], y[pi]))
    out = []
    for base, bcfg in (('pn', dict(labels='hard')), ('cue1_soft', dict(labels='soft', cue=1))):
        for fname, fcfg in FRONT.items():
            cfg = dict(bcfg, **fcfg)
            t = thr[cfg.get('thr', 'gm')]
            rng = np.random.default_rng(seed * 100003 + subject)
            rng_e = np.random.default_rng(seed * 7919 + subject * 31)
            mdl = T4.make(cfg, Zc, yc)
            for b, (pools, apools, Zp, yp, Ap, _) in enumerate(data):
                for k in range(cfg.get('cue', 0)):
                    for c in range(LS.K):
                        mdl.learn(pools[c][k], c)
                st = T4.session(mdl, cfg, pools, apools, t, rng, rng_e, 0.1, 0.0)
                out.append(dict(subject=subject, shift=shift, seed=seed, base=base, front=fname, block=b,
                                probe_after=T.probe(mdl, Zp, yp), thr_ratio=t / thr['gm'],
                                rest_open=float(np.mean(Ap[yp == REST] >= t) * 100),
                                gesture_blocked=float(np.mean(Ap[yp != REST] < t) * 100) if cfg.get('act') else 0.0,
                                cue_s=8.0 * cfg.get('cue', 0), **st))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    args = ap.parse_args()
    import check_features_c as FC
    import task_sim6 as M
    FC.lib()
    pd.set_option('display.width', 250)
    lines = []

    def say(s=''):
        print(s)
        lines.append(str(s))

    # ---- A. Vidovic
    vd = pd.DataFrame([r for rs in Parallel(n_jobs=args.jobs)(delayed(M.vidovic_job)(s, sh) for sh in (0.0, 0.5)
                                                          for s in range(20)) for r in rs])
    vd.to_csv(os.path.join(OUT, 'task_sim6_vidovic.csv'), index=False, float_format='%.4g')
    v = vd[vd.block >= 1].groupby(['shift', 'tau', 'lam', 'subject']).acc.mean()
    grid = v.groupby(level=[0, 1, 2]).mean()
    t4 = pd.read_csv(os.path.join(OUT, 'task_sim4.csv'))
    ours = t4[(t4.block >= 1) & (t4.e == 0) & t4.cond.isin(['cue1', 'cue1_soft', 'cue2', 'fixed'])]
    ours = ours.groupby(['shift', 'cond', 'subject']).probe_after.mean()
    for sh in (0.0, 0.5):
        best = grid.xs(sh, level='shift').idxmax()
        say(f'shift {sh}: grid-best (tau, lambda) on this data = {best}, {grid.xs(sh, level="shift").max():.2f} %')
        rows = {f'{k} (tau {t}, lambda {l})': v.xs((sh, t, l), level=[0, 1, 2]) for k, (t, l) in PAPER.items()}
        rows[f'grid best (tau {best[0]}, lambda {best[1]}), tuned on this data'] = v.xs((sh,) + best, level=[0, 1, 2])
        for c in ('fixed', 'cue1', 'cue2', 'cue1_soft'):
            rows[f'ours: {c}'] = ours.xs((sh, c), level=[0, 1])
        say(pd.Series({k: s.mean() for k, s in rows.items()}).round(2).to_string())
        for ref in ('LDACMA (tau 0.8, lambda 0.8)', f'grid best (tau {best[0]}, lambda {best[1]}), tuned on this data'):
            for c in ('cue1', 'cue1_soft'):
                dd = rows[f'ours: {c}'] - rows[ref]
                m, lo, hi = LS.ci(dd)
                say(f'  {c} - {ref}: {m:+.2f} ({lo:+.2f}, {hi:+.2f}), better {int((dd > 0).sum())} worse {int((dd < 0).sum())}')
                if sh == 0.5 and c == 'cue1_soft' and ref.startswith('LDACMA'):
                    say('    R6: ' + ('PASS' if (m >= 1 and lo > 0) else 'FAIL'))
        say()
    # ---- B. front ends
    fr = pd.DataFrame([r for rs in Parallel(n_jobs=args.jobs)(delayed(M.front_job)(s, sh, seed) for sh in (0.0, 0.5)
                                                          for seed in (0, 1) for s in range(20)) for r in rs])
    fr.to_csv(os.path.join(OUT, 'task_sim6_frontend.csv'), index=False, float_format='%.4g')
    d = fr[fr.block >= 1].copy()
    d['false_rest_pct'] = d.false_rest / d.actions.clip(lower=1) * 100
    d['wrong_action_pct'] = d.wrong_actions / d.actions.clip(lower=1) * 100
    d['done'] = (d.cycles >= T.N_CYCLES) * 100
    d['total_s'] = d.seconds + d.cue_s
    cols = ['probe_after', 'false_rest_pct', 'wrong_action_pct', 'done', 'total_s', 'rest_open', 'gesture_blocked', 'thr_ratio']
    ps = d.groupby(['shift', 'base', 'front', 'subject'])[cols].mean()
    sm = ps.groupby(level=[0, 1, 2]).mean()
    say(sm.round(2).to_string())
    for sh in (0.0, 0.5):
        for base in ('pn', 'cue1_soft'):
            for f in ('act_s', 'rej', 'none'):
                dd = ps.xs((sh, base, 'act'), level=[0, 1, 2]).probe_after - ps.xs((sh, base, f), level=[0, 1, 2]).probe_after
                m, lo, hi = LS.ci(dd)
                say(f'  shift {sh} {base}: probe act - {f} = {m:+.2f} ({lo:+.2f}, {hi:+.2f})')
    a, s_ = sm.loc[(0.5, 'pn', 'act')], sm.loc[(0.5, 'pn', 'act_s')]
    dprobe = ps.xs((0.5, 'pn', 'act'), level=[0, 1, 2]).probe_after - ps.xs((0.5, 'pn', 'act_s'), level=[0, 1, 2]).probe_after
    ok = a.false_rest_pct <= s_.false_rest_pct and dprobe.mean() >= -0.5
    say(f'R7: no cued pass, shift 0.5: false_rest act {a.false_rest_pct:.2f} % vs act_s {s_.false_rest_pct:.2f} %, '
        f'probe act - act_s {dprobe.mean():+.2f} -> ' + ('KEEP our threshold' if ok else "USE Scheme's threshold"))
    open(os.path.join(OUT, 'task_sim6_summary.txt'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
