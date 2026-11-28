#!/usr/bin/env python3
"""Report 35.110, R20 pre-registered evaluation (results/riemann_110/PREREG_R20.md):
4x4 Riemannian Tangent Space (TS-10D, AIRM mean) + Log-40D (50 features) vs Base-40D and Log-40D (R16)
on 4-channel S7 self-test recordings.

Usage (container, /sd = D:\selftest_data):
  python src/riemann_r20.py --dir /sd/T00 --days T00_d1_S T00_d2_S --out results/riemann_110
  python src/riemann_r20.py --dir /sd/T00 --days T00_d1_G T00_d2_G --out results/riemann_110 --dev
"""
import argparse
import os
import sys

import numpy as np
from scipy.linalg import eigh
from scipy.signal import butter, sosfilt
from sklearn.covariance import oas

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import selftest_analysis as SA  # noqa: E402
import selftest9_analysis as S9  # noqa: E402

SOS = butter(4, (10 * 2 / 2000, 500 * 2 / 2000), btype='bandpass', output='sos')
CL = S9.SETS['S7']
WIN, STEP = 400, 200
UPPER_I, UPPER_J = np.triu_indices(4)
UPPER_W = np.where(UPPER_I == UPPER_J, 1.0, np.sqrt(2.0))
HAMM = 0.54 - 0.46 * np.cos(2.0 * np.pi * np.arange(WIN) / WIN)
DF = 2000.0 / 512.0
FREQS = np.arange(257) * DF


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


def riemann_mean(covs, max_iter=25, tol=1e-6):
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


def extract_4ch(X_filt, nw):
    F = np.empty((nw, 40), dtype=np.float64)
    covs = np.empty((nw, 4, 4), dtype=np.float64)
    for w in range(nw):
        seg = X_filt[:, w * STEP:w * STEP + WIN]
        rms = np.sqrt(np.mean(seg * seg, axis=1))
        d = np.diff(seg, axis=1)
        wl = np.sum(np.abs(d), axis=1)
        zc = np.sum((np.signbit(seg[:, :-1]) != np.signbit(seg[:, 1:])) & (np.abs(d) > 0), axis=1)
        ssc = np.sum((np.signbit(d[:, :-1]) != np.signbit(d[:, 1:]))
                     & (np.maximum(np.abs(d[:, :-1]), np.abs(d[:, 1:])) > 0), axis=1)
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
    return F, covs


def tangent_feats(covs, R_ref):
    Ri = sym_inv_sqrt(R_ref)
    out = np.empty((len(covs), 10), dtype=np.float64)
    for i, C in enumerate(covs):
        L = sym_log(Ri @ C @ Ri)
        out[i] = L[UPPER_I, UPPER_J] * UPPER_W
    return out


def zscore(F, cal_rows):
    mu = F[cal_rows].mean(axis=0)
    sd = F[cal_rows].std(axis=0)
    inv = np.where(sd > 0, 1.0 / sd, 0.0)
    return (F - mu) * inv


def fit_oas_lda(X, y):
    mu_c, E = {}, []
    for c in CL:
        Xc = X[y == c]
        mu_c[c] = Xc.mean(axis=0)
        E.append(Xc - mu_c[c])
    C, _ = oas(np.vstack(E), assume_centered=True)
    W = np.array([np.linalg.solve(C, mu_c[c]) for c in CL])
    b = np.array([-0.5 * float(mu_c[c] @ W[i]) for i, c in enumerate(CL)])
    return W, b


def acc(W, b, X, y):
    pred = np.array([CL[i] for i in (X @ W.T + b[None, :]).argmax(axis=1)])
    return 100.0 * float(np.mean(pred == y))


def load_day(root, name):
    day = S9.load_day(root, name, 4.0, frozenset(CL))
    folder = S9.day_folder(root, name)
    X8, _, _ = SA.load_emg(os.path.join(folder, f'{name}_emg.csv'))
    X_f = sosfilt(SOS, X8[:, :4].T.astype(np.float64), axis=1)
    nw = (X8.shape[0] - WIN) // STEP + 1
    assert nw == len(day['F'])
    F40, covs = extract_4ch(X_f, nw)
    cm = np.isin(day['cal_lab'], CL)
    cal_r, cal_y = day['cal_rows'][cm], day['cal_lab'][cm]
    pr, py = [], []
    for items in day['probes']:
        for w, g in items:
            if g in CL:
                pr.append(w)
                py.append(np.full(len(w), g, dtype=int))
    pr, py = np.concatenate(pr), np.concatenate(py)

    F_log = F40.copy()
    for sl in (slice(0, 4), slice(4, 8), slice(16, 20)):
        F_log[:, sl] = np.log(np.maximum(F_log[:, sl], 1e-12))
    R_ra = riemann_mean(covs[cal_r])
    TS = tangent_feats(covs, R_ra)

    Zb = zscore(F40, cal_r)
    Zl = zscore(F_log, cal_r)
    Zt = zscore(TS, cal_r)
    return dict(name=name, cal_r=cal_r, cal_y=cal_y, pr=pr, py=py, feats={
        'Base-40D': Zb,
        'Log-40D': Zl,
        'TS-10D(RA)': Zt,
        '40D+TS10': np.hstack([Zb, Zt]),
        'Log40D+TS10': np.hstack([Zl, Zt]),
    })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default='/sd/T00')
    ap.add_argument('--days', nargs=2, required=True)
    ap.add_argument('--out', default='results/riemann_110')
    ap.add_argument('--dev', action='store_true', help='development dry-run (not a decision)')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    d1, d2 = [load_day(a.dir, n) for n in a.days]
    lines = [f'R20 {"DEV DRY-RUN (NOT A DECISION)" if a.dev else "PRE-REGISTERED DECISION"}: {a.days[0]}, {a.days[1]} (S7, 4ch)']
    lines.append(f'{"Method":<14} | {"d1 cue":>7} | {"d2 cue":>7} | {"mean cue":>8} | {"acc->d2":>8} | {"0-shot->d2":>10}')
    lines.append('-' * 68)
    res = {}
    for m in ('Base-40D', 'Log-40D', 'TS-10D(RA)', '40D+TS10', 'Log40D+TS10'):
        Z1, Z2 = d1['feats'][m], d2['feats'][m]
        W1, b1 = fit_oas_lda(Z1[d1['cal_r']], d1['cal_y'])
        W2, b2 = fit_oas_lda(Z2[d2['cal_r']], d2['cal_y'])
        W12, b12 = fit_oas_lda(np.vstack([Z1[d1['cal_r']], Z2[d2['cal_r']]]),
                               np.concatenate([d1['cal_y'], d2['cal_y']]))
        a1 = acc(W1, b1, Z1[d1['pr']], d1['py'])
        a2 = acc(W2, b2, Z2[d2['pr']], d2['py'])
        a12 = acc(W12, b12, Z2[d2['pr']], d2['py'])
        a0 = acc(W1, b1, Z2[d2['pr']], d2['py'])
        res[m] = (a1, a2, 0.5 * (a1 + a2), a12, a0)
        lines.append(f'{m:<14} | {a1:6.2f}% | {a2:6.2f}% | {0.5*(a1+a2):7.2f}% | {a12:7.2f}% | {a0:9.2f}%')

    b = res['Base-40D']
    l = res['Log-40D']
    c = res['Log40D+TS10']
    da1, da2, dam, dacc = c[0] - b[0], c[1] - b[1], c[2] - b[2], c[3] - b[3]
    db1, db2, dbm = c[0] - l[0], c[1] - l[1], c[2] - l[2]
    pass_a = (da1 > 0) and (da2 > 0) and (dam >= 2.0) and (dacc >= 0.0)
    pass_b = (db1 > 0) and (db2 > 0) and (dbm >= 1.0)
    lines.append('')
    lines.append(f'R20-A (Log40D+TS10 vs Base-40D): d1 {da1:+.2f}, d2 {da2:+.2f}, mean {dam:+.2f}, acc {dacc:+.2f} -> '
                 f'{"PASS" if pass_a else "FAIL"}')
    lines.append(f'R20-B (Log40D+TS10 vs Log-40D):  d1 {db1:+.2f}, d2 {db2:+.2f}, mean {dbm:+.2f} -> '
                 f'{"PASS" if pass_b else "FAIL"}')
    txt = '\n'.join(lines) + '\n'
    print(txt)
    fname = 'r20_dev_1123.txt' if a.dev else 'r20_result.txt'
    with open(os.path.join(a.out, fname), 'w', encoding='utf-8', newline='\n') as f:
        f.write(txt)


if __name__ == '__main__':
    main()
