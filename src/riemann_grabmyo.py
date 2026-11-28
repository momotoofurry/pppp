#!/usr/bin/env python3
"""Cross-day public dataset validation on GrabMyo (43 participants, Days 1 / 8 / 29, G7 = 7 classes, 4 channels).
Compares:
  - Base-40D         (4ch standard 40 features + z-score + OAS LDA)
  - Log-40D (R16)    (log on RMS / WL / MAV)
  - TS-10D (RA)      (4x4 Riemannian tangent space 10 features alone)
  - 40D + TS10 (RA)  (50 features)
  - Log40D+TS10 (RA) (50 features)
Protocol matches src/grabmyo_crossday.py:
  - 4 forearm channels [0, 2, 4, 6] (ring 1 every other electrode), resampled 2048 -> 2000 Hz
  - cued pass: trial 1 of each G7 gesture (windows from 0.5 s, cap 30)
  - test:      trials 5-7 of each G7 gesture (windows from 0.5 s), balanced accuracy %
  - Conditions on later days (Day 8 & Day 29):
      cue:       same-day cued pass only
      acc:       running sums accumulated across days (Day 1 -> 8 -> 29)
      zero-shot: Day 1 model applied directly to Day 8 / 29 (using Day 8/29 session z-score & R_ra)
"""
import multiprocessing as mp
import os
import sys

import numpy as np
from scipy import stats as sst
from scipy.linalg import eigh
from scipy.signal import butter, resample_poly, sosfilt
from sklearn.covariance import oas

sys.path.insert(0, '/work/src')
import grabmyo_crossday as GM

SOS = butter(4, (10 * 2 / 2000, 500 * 2 / 2000), btype='bandpass', output='sos')
CH4 = [0, 2, 4, 6]
G7 = GM.SETS['G7']
WIN, STEP = 400, 200
UPPER_I, UPPER_J = np.triu_indices(4)
UPPER_W = np.where(UPPER_I == UPPER_J, 1.0, np.sqrt(2.0))
HAMM = 0.54 - 0.46 * np.cos(2.0 * np.pi * np.arange(WIN) / WIN)
DF = 2000.0 / 512.0
FREQS = np.arange(257) * DF
METHODS = ['Base-40D', 'Log-40D', 'TS-10D(RA)', '40D+TS10', 'Log40D+TS10']


def sym_inv_sqrt(M, eps=1e-12):
    w, V = eigh(M)
    w = np.maximum(w, eps)
    return (V * (1.0 / np.sqrt(w))) @ V.T


def sym_sqrt(M, eps=1e-12):
    w, V = eigh(M)
    w = np.maximum(w, eps)
    return (V * np.sqrt(w)) @ V.T


def sym_log(M, eps=1e-12):
    w, V = eigh(M)
    w = np.maximum(w, eps)
    return (V * np.log(w)) @ V.T


def sym_exp(M):
    w, V = eigh(M)
    return (V * np.exp(w)) @ V.T


def riemann_mean(covs, max_iter=20, tol=1e-5):
    R = np.mean(covs, axis=0)
    for _ in range(max_iter):
        Ri = sym_inv_sqrt(R)
        Rh = sym_sqrt(R)
        S = np.zeros_like(R)
        for C in covs:
            S += sym_log(Ri @ C @ Ri)
        S /= len(covs)
        R = Rh @ sym_exp(S) @ Rh
        if np.linalg.norm(S, 'fro') < tol:
            break
    return R


def extract_trial(X4_raw):
    """X4_raw: (N, 4) mV at 2048 Hz -> (F40, covs) from 0.5 s onward."""
    Y = (resample_poly(X4_raw, 125, 128, axis=0) * 1e-3).T.astype(np.float64)  # (4, N')
    Xf = sosfilt(SOS, Y, axis=1)
    nw = (Xf.shape[1] - WIN) // STEP + 1
    F = np.empty((nw, 40), dtype=np.float64)
    covs = np.empty((nw, 4, 4), dtype=np.float64)
    for w in range(nw):
        seg = Xf[:, w * STEP:w * STEP + WIN]
        rms = np.sqrt(np.mean(seg * seg, axis=1))
        d = np.diff(seg, axis=1)
        wl = np.sum(np.abs(d), axis=1)
        zc = np.sum((np.signbit(seg[:, :-1]) != np.signbit(seg[:, 1:])) & (np.abs(d) > 0), axis=1)
        ssc = np.sum((np.signbit(d[:, :-1]) != np.signbit(d[:, 1:])) & (np.maximum(np.abs(d[:, :-1]), np.abs(d[:, 1:])) > 0), axis=1)
        mav = np.mean(np.abs(seg), axis=1)
        c = seg - seg.mean(axis=1, keepdims=True)
        m2 = np.mean(c * c, axis=1)
        m3 = np.mean(c * c * c, axis=1)
        skw = np.where(m2 > 0, m3 / (m2 * np.sqrt(np.maximum(m2, 1e-30))), 0.0)
        spec = np.fft.rfft(seg * HAMM[None, :], n=512, axis=1)
        psd = spec.real ** 2 + spec.imag ** 2
        psd[:, 1:-1] *= 2.0
        sm0 = np.sum(psd, axis=1)
        sm1 = psd @ FREQS
        sm2 = psd @ (FREQS * FREQS)
        mnf = np.where(sm0 > 0, sm1 / np.maximum(sm0, 1e-30), 0.0)
        vcf = np.where(sm0 > 0, sm2 / np.maximum(sm0, 1e-30) - mnf * mnf, 0.0)
        cum = np.cumsum(psd, axis=1)
        mdf = np.argmin(np.abs(cum - 0.5 * sm0[:, None]), axis=1) * DF
        pkf = np.argmax(psd, axis=1) * DF
        F[w, 0:4] = rms
        F[w, 4:8] = wl
        F[w, 8:12] = ssc
        F[w, 12:16] = zc
        F[w, 16:20] = mav
        F[w, 20:24] = skw
        F[w, 24:28] = vcf
        F[w, 28:32] = mdf
        F[w, 32:36] = mnf
        F[w, 36:40] = pkf
        C = (c @ c.T) / WIN
        tr = np.trace(C)
        covs[w] = C + (1e-6 * tr + 1e-15) * np.eye(4)
    return F[5:], covs[5:]


def tangent_feats(covs, R_ref):
    Ri = sym_inv_sqrt(R_ref)
    out = np.empty((len(covs), 10), dtype=np.float64)
    for i, C in enumerate(covs):
        L = sym_log(Ri @ C @ Ri)
        out[i] = L[UPPER_I, UPPER_J] * UPPER_W
    return out


def zscore(F_cal, F_test):
    mu = F_cal.mean(axis=0)
    sd = F_cal.std(axis=0)
    inv = np.where(sd > 0, 1.0 / sd, 0.0)
    return (F_cal - mu) * inv, (F_test - mu) * inv


def fit_predict_bal(X_tr, y_tr, X_te, y_te):
    mu_c, E = {}, []
    for c in G7:
        Xc = X_tr[y_tr == c]
        mu_c[c] = Xc.mean(axis=0)
        E.append(Xc - mu_c[c])
    C, _ = oas(np.vstack(E), assume_centered=True)
    W = np.array([np.linalg.solve(C, mu_c[c]) for c in G7])
    b = np.array([-0.5 * float(mu_c[c] @ W[i]) for i, c in enumerate(G7)])
    pred = np.array([G7[i] for i in (X_te @ W.T + b[None, :]).argmax(axis=1)])
    return 100.0 * float(np.mean([np.mean(pred[y_te == c] == c) for c in G7]))


def run_subject(subj):
    root = '/grabmyo'
    sess_data = []
    for s in (1, 2, 3):
        d = os.path.join(root, f'Session{s}', f'session{s}_participant{subj}')
        F_cal, C_cal, y_cal = [], [], []
        F_te, C_te, y_te = [], [], []
        for c in G7:
            gm = GM.GM[c]
            # Trial 1 = cued pass
            X, _ = GM.read_wfdb(os.path.join(d, f'session{s}_participant{subj}_gesture{gm}_trial1'))
            f, cv = extract_trial(X[:, CH4])
            f, cv = f[:30], cv[:30]
            F_cal.append(f); C_cal.append(cv); y_cal.append(np.full(len(f), c, dtype=int))
            # Trials 5-7 = held-out test
            for t in (5, 6, 7):
                X, _ = GM.read_wfdb(os.path.join(d, f'session{s}_participant{subj}_gesture{gm}_trial{t}'))
                f, cv = extract_trial(X[:, CH4])
                F_te.append(f); C_te.append(cv); y_te.append(np.full(len(f), c, dtype=int))
        F_cal = np.vstack(F_cal); C_cal = np.vstack(C_cal); y_cal = np.concatenate(y_cal)
        F_te = np.vstack(F_te); C_te = np.vstack(C_te); y_te = np.concatenate(y_te)
        R_ra = riemann_mean(C_cal)
        TS_cal = tangent_feats(C_cal, R_ra)
        TS_te = tangent_feats(C_te, R_ra)
        F_cal_log = F_cal.copy(); F_te_log = F_te.copy()
        for sl in (slice(0, 4), slice(4, 8), slice(16, 20)):
            F_cal_log[:, sl] = np.log(np.maximum(F_cal_log[:, sl], 1e-12))
            F_te_log[:, sl] = np.log(np.maximum(F_te_log[:, sl], 1e-12))
        Zc_b, Zt_b = zscore(F_cal, F_te)
        Zc_l, Zt_l = zscore(F_cal_log, F_te_log)
        Zc_ts, Zt_ts = zscore(TS_cal, TS_te)
        sess_data.append({
            'y_cal': y_cal, 'y_te': y_te,
            'Base-40D': (Zc_b, Zt_b),
            'Log-40D': (Zc_l, Zt_l),
            'TS-10D(RA)': (Zc_ts, Zt_ts),
            '40D+TS10': (np.hstack([Zc_b, Zc_ts]), np.hstack([Zt_b, Zt_ts])),
            'Log40D+TS10': (np.hstack([Zc_l, Zc_ts]), np.hstack([Zt_l, Zt_ts])),
        })

    out = {}
    for m in METHODS:
        cues, accs, zshots = [], [], []
        X_acc, y_acc = [], []
        X1, y1 = sess_data[0][m][0], sess_data[0]['y_cal']
        for i, sd in enumerate(sess_data):
            Xc, Xt = sd[m]
            yc, yt = sd['y_cal'], sd['y_te']
            X_acc.append(Xc); y_acc.append(yc)
            a_cue = fit_predict_bal(Xc, yc, Xt, yt)
            if i > 0:
                a_acc = fit_predict_bal(np.vstack(X_acc), np.concatenate(y_acc), Xt, yt)
                a_0 = fit_predict_bal(X1, y1, Xt, yt)
                cues.append(a_cue); accs.append(a_acc); zshots.append(a_0)
        out[m] = (float(np.mean(cues)), float(np.mean(accs)), float(np.mean(zshots)))
    return subj, out


def main():
    subjs = list(range(1, 44))
    with mp.Pool(processes=min(16, os.cpu_count() or 4)) as pool:
        res = pool.map(run_subject, subjs)
    res.sort(key=lambda z: z[0])
    print(f'=== GrabMyo Cross-Day Validation (43 subjects, Days 8 & 29, G7 = 7 classes, 4 channels) ===')
    for idx, label in [(0, 'Same-day cue (Days 8 & 29 mean)'),
                       (1, 'Cross-day acc (Day 1+8+29 -> Days 8 & 29)'),
                       (2, 'Zero-shot transfer (Day 1 -> Days 8 & 29)')]:
        print(f'\n-- {label} --')
        base = np.array([r[1]['Base-40D'][idx] for r in res])
        log40 = np.array([r[1]['Log-40D'][idx] for r in res])
        for m in METHODS:
            vals = np.array([r[1][m][idx] for r in res])
            d_b = vals - base
            h_b = sst.t.ppf(0.975, len(d_b) - 1) * d_b.std(ddof=1) / np.sqrt(len(d_b))
            d_l = vals - log40
            h_l = sst.t.ppf(0.975, len(d_l) - 1) * d_l.std(ddof=1) / np.sqrt(len(d_l))
            print(f'  {m:<12s}: {vals.mean():5.2f}% | vs Base {d_b.mean():+5.2f} (95% CI {d_b.mean()-h_b:+5.2f},{d_b.mean()+h_b:+5.2f}, {(d_b>0).sum():2d}/43) '
                  f'| vs Log40D {d_l.mean():+5.2f} (CI {d_l.mean()-h_l:+5.2f},{d_l.mean()+h_l:+5.2f}, {(d_l>0).sum():2d}/43)')


if __name__ == '__main__':
    main()
