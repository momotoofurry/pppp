"""Electrode rotation by one position (45 degrees on an 8-electrode ring): does self-calibration recover, and does it
fail like confidence-based self-training (Campbell et al., JNER 2024)?

Scenario: one-shot calibration with the original placement (day 1); every test block is recorded with the ring
rotated by `shift` electrodes (day 2 re-donning): channel c of the model now sees electrode (c + shift) mod 8, i.e.
the 10 features of each channel are moved to the neighbouring channel. The ring order is assumed to be 1..8 around
the forearm (not documented by the authors; channels 1-4 and 5-8 are each a chain of neighbours). The calibration
set kept from day 1 is not rotated (as on the device).
Setting = the recommended MCU configuration of selfcal_sweep.py with the authors' 66-participant model: 100 trees,
depth 10, int16, int16 buffer of 375, 20 new trees with <= 32 leaves per block, t-SNE 500 iterations.
Methods (each run also records the fixed one-shot model on the same blocks):
  tsne  the self-calibration of this work: upstream manifold_clustering (re-label the buffer with the original
        one-shot model, t-SNE + K-Means) -> pseudo-labels
  uhc   unsupervised high-confidence self-training (the UHC baseline of Campbell et al.): pseudo-label = the current
        self-calibrated model's own prediction, only buffer rows whose top-vote ratio >= --uhc-tau (0.6) are used;
        no update when fewer than 10 rows qualify
Both train the same 20 trees on (pseudo-labelled rows + calibration set) and replace 20 random appended trees.
Writes results/shift_sweep.csv (per subject/seed/shift/method/block) and results/shift_sweep_summary.csv.
Usage (in the container): python src/shift_sweep.py [--shifts 0 1 -1] [--seeds 0 1 2] [--jobs 19]

--raw (strap scenario, fractional shifts): the rotation is applied to the raw EMG instead of the feature columns.
An electrode rotated by s = k + f positions (0 <= f < 1) records (1 - f) * electrode (c + k) + f * electrode (c + k + 1)
(linear interpolation between the two neighbouring electrodes, ~3 cm apart: a first-order approximation, since the
mix of two signals is not what an electrode between them would record). Features of every folder are then computed
with the C feature extraction (src/c/features.c, as check_features_c.py); the calibration is not rotated. Cached in
build/shift_features/. Methods in this mode:
  tsne   as above, no alignment
  align  re-alignment at start-up, no labels: from the first test block, estimate the integer rotation k that best
         matches the calibration's channel profile (per-channel mean of log RMS / MAV / WL, correlation summed over
         the three features, 8 candidates), permute the channels back for all blocks, then self-calibrate as tsne.
         On the device this needs only the stored calibration means (already kept for the z-score).
Writes results/shift_sweep_raw.csv and results/shift_sweep_raw_summary.csv.
Usage: python src/shift_sweep.py --raw --shifts 0 0.25 0.5 0.75 1 -0.5 -1 --methods tsne align
"""
import argparse
import copy
import os
import sys
import time

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.stats import wilcoxon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_features_c as FC  # noqa: E402
import pipeline as P  # noqa: E402
import rf_size  # noqa: E402
import selfcal_sweep as S  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
N_FEAT = len(P.FEATS)
N, DEPTH, PREC, BUF, MLN, IT = 100, 10, 'int16', 375, 32, 500
CACHE = os.path.join(P.ROOT, 'build', 'shift_features')
AMP = [P.FEATS.index(f) for f in ('rms', 'mav', 'wl')]          # amplitude features used for the alignment


def rotate(X, shift):
    """model channel c reads electrode (c + shift) mod 8: column f*8 + c <- f*8 + (c + shift) % 8"""
    if shift == 0:
        return X
    idx = [f * 8 + (c + shift) % 8 for f in range(N_FEAT) for c in range(8)]
    return X[:, idx]


def raw_features(subject, folder, shift):
    """C features (unnormalised, load_folder layout) of one folder with the raw EMG rotated by `shift` positions"""
    data = np.load(os.path.join(P.REPO, 'dataset_arm_position', str(subject), folder, 'data.npy')).astype(np.float32)
    label = np.load(os.path.join(P.REPO, 'dataset_arm_position', str(subject), folder, 'label.npy'))
    k = int(np.floor(shift))
    f = shift - k
    idx = (np.arange(8) + k) % 8
    if f:
        data = ((1 - f) * data[:, idx] + f * data[:, (idx + 1) % 8]).astype(np.float32)
    else:
        data = np.ascontiguousarray(data[:, idx])
    L = FC.lib()
    out = np.zeros((len(data), FC.NWIN, 80), dtype=np.float32)
    for t, rec in enumerate(data):
        rec = np.ascontiguousarray(rec)
        assert L.fe_recording(rec.ctypes.data, rec.shape[1], out[t].ctypes.data, FC.NWIN) == FC.NWIN
    X = out[:, FC.W0:, :].astype(np.float64).reshape(-1, 80)
    return X, np.repeat(label, FC.NWIN - FC.W0)


def prepare(subject, shift):
    path = os.path.join(CACHE, f'{subject}_{shift:g}.npz')
    if not os.path.exists(path):
        Xc, yc = raw_features(subject, 'calibration', 0)
        arrs = dict(Xc=Xc, yc=yc)
        for b in range(P.N_BLOCKS):
            arrs[f'X{b}'], arrs[f'y{b}'] = raw_features(subject, f'testing_block{b}', shift)
        os.makedirs(CACHE, exist_ok=True)
        np.savez(path + '.tmp.npz', **arrs)
        os.replace(path + '.tmp.npz', path)
    return path


def profile(X):
    """per amplitude feature: per-channel mean of log feature, standardised across the 8 channels (3 x 8)"""
    p = np.stack([np.log(np.maximum(X[:, a * 8:(a + 1) * 8], 1e-12)).mean(0) for a in AMP])
    return (p - p.mean(1, keepdims=True)) / p.std(1, keepdims=True)


def estimate_rotation(Xc_raw, X_raw):
    """integer k such that channel c of the new recording looks like calibration channel c + k"""
    q, p = profile(Xc_raw), profile(X_raw)
    score = [np.sum(q * np.roll(p, k, axis=1)) for k in range(8)]   # np.roll(p, k)[c] = p[c - k]
    k = int(np.argmax(score))
    return k if k < 4 else k - 8


def load_raw(subject, shift, method):
    z = np.load(prepare(subject, shift))
    Xc, yc = z['Xc'], z['yc']
    blocks = [(z[f'X{b}'], z[f'y{b}']) for b in range(P.N_BLOCKS)]
    k = 0
    if method == 'align':
        k = estimate_rotation(Xc, blocks[0][0])
        blocks = [(rotate(X, -k), y) for X, y in blocks]              # column c <- column c - k
    mu, sd = Xc.mean(0), Xc.std(0)
    return (Xc - mu) / sd, yc, [((X - mu) / sd, y) for X, y in blocks], k


def votes(mdl, X, precision):
    """P.predict, returning the vote counts per class (n x classes) instead of the argmax"""
    if precision == 'int16':
        Xp, thr = P.quantize(X), [P.quantize(t) for t in mdl['threshold']]
    else:
        Xp, thr = X, mdl['threshold']
    n = len(Xp)
    labels = P.leaf_labels(mdl)
    v = np.zeros((n, int(np.max(mdl['classes'])) + 1), dtype=np.int32)
    rows = np.arange(n)
    for left, right, feat, t, lab in zip(mdl['left'], mdl['right'], mdl['feature'], thr, labels):
        node = np.zeros(n, dtype=np.int64)
        active = left[node] > 0
        while active.any():
            idx = rows[active]
            nd = node[idx]
            go_left = Xp[idx, feat[nd]] < t[nd]
            node[idx] = np.where(go_left, left[nd], right[nd])
            active[idx] = left[node[idx]] > 0
        v[rows, lab[node]] += 1
    return v


def run(subject, seed, shift, method, uhc_tau, raw=False):
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), PREC), None)
    emg_functions.TSNE = S.tsne_with(IT, S.PERPLEXITY)
    np.random.seed(seed * 1000 + subject)
    if raw:
        Xc, yc, blocks, k_est = load_raw(subject, shift, method)
    else:
        Xc, yc, blocks = P.load_subject(subject)
        blocks = [(rotate(X, shift), y) for X, y in blocks]
        k_est = np.nan
    pre = P.load_pretrain()
    n_pre, n_app = N // 2, N - N // 2
    n_upd = int(round(S.REPLACE_FRAC * n_app))
    pruned = P.prune(rf_size.truncate_depth(copy.deepcopy(pre), DEPTH), Xc, yc)
    app = P.train_rf(Xc, yc, n_app, DEPTH, None)
    mdl_os = emg_functions.append(P.subset(pruned, range(n_pre)), app)
    mdl_sc = copy.deepcopy(mdl_os)
    feat_buf, lab_buf = np.zeros((0, Xc.shape[1])), np.zeros((0,))
    rows = []
    for b, (X, y) in enumerate(blocks):
        lab_os, lab_sc = P.predict(mdl_os, X, PREC), P.predict(mdl_sc, X, PREC)
        rec = dict(subject=subject, seed=seed, shift=shift, method=method, block=b,
                   acc_fixed=np.mean(lab_os == y), acc_adapt=np.mean(lab_sc == y), n_pseudo=np.nan, pseudo_acc=np.nan,
                   k_est=k_est)
        feat_buf, lab_buf = emg_functions.buffer_update(BUF, feat_buf, lab_buf, S.q16(X), lab_sc)
        if method in ('tsne', 'align'):
            feat_sel, lab_pseudo, lab_buf = emg_functions.manifold_clustering(
                feat_buf, list(S.LABELS), S.MIN_SAMPLE_CLASS, mdl_os, 'kmeans', embedding='tsne')
        else:
            v = votes(mdl_sc, feat_buf, PREC)
            ratio = v.max(axis=1) / v.sum(axis=1)
            keep = ratio >= uhc_tau
            feat_sel, lab_pseudo = feat_buf[keep], v.argmax(axis=1)[keep].astype(float)
        rec['n_pseudo'] = len(lab_pseudo)
        rows.append(rec)
        if len(lab_pseudo) < 10:
            continue
        new = P.train_rf(np.concatenate([feat_sel, S.q16(Xc)]), np.concatenate([lab_pseudo, yc]), n_upd, DEPTH, None, MLN)
        idx_remain = np.concatenate([np.arange(n_pre), np.random.permutation(range(n_pre, N))[:n_app - n_upd]])
        mdl_sc = emg_functions.replace(mdl_sc, new, idx_remain)
    return rows


def summarize_raw(acc, shifts):
    """per shift and method: its own fixed model and the adapted one; paired over subjects (Wilcoxon) against the
    fixed model, against tsne at the same shift and against tsne without rotation (the target).
    align: also the estimated rotation per subject (k_values 'estimate:count'; k_nearest = estimate equal to the
    nearest integer of the shift, not defined at exactly half a position)."""
    ps = acc.groupby(['shift', 'method', 'subject'])[['acc_fixed', 'acc_adapt']].mean() * 100
    late = acc[acc.block >= 8].groupby(['shift', 'method', 'subject']).acc_adapt.mean() * 100
    methods = [m for m in ('tsne', 'uhc', 'align') if m in set(acc.method)]
    ref = ps.loc[(0, 'tsne')].acc_adapt                              # no rotation, no alignment
    out = []

    def paired(row, name, x, y):
        d = x - y
        row[f'diff_{name}'] = d.mean()
        row[f'better_{name}'] = int((d > 0).sum())
        row[f'p_{name}'] = wilcoxon(x, y).pvalue if np.any(d != 0) else 1.0

    for sh in shifts:
        row = dict(shift=sh)
        for m in methods:
            a = ps.loc[(sh, m)]
            row[f'{m}_fixed'], row[m], row[f'{m}_late'] = a.acc_fixed.mean(), a.acc_adapt.mean(), late.loc[(sh, m)].mean()
            paired(row, f'{m}_vs_fixed', a.acc_adapt, a.acc_fixed)
            paired(row, f'{m}_vs_noshift', a.acc_adapt, ref)
            if m != 'tsne':
                paired(row, f'{m}_vs_tsne', a.acc_adapt, ps.loc[(sh, 'tsne')].acc_adapt)
        if 'align' in methods:
            k = acc[(acc['shift'] == sh) & (acc.method == 'align')].groupby('subject').k_est.first()
            row['k_nearest'] = int((k == np.floor(sh + 0.5)).sum()) if sh % 1 != 0.5 else np.nan
            row['k_values'] = ' '.join(f'{int(v)}:{n}' for v, n in k.value_counts().sort_index().items())
        out.append(row)
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--shifts', type=float, nargs='+', default=[0, 1, -1])
    ap.add_argument('--methods', nargs='+', default=['tsne', 'uhc'], choices=['tsne', 'uhc', 'align'])
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--subjects', type=int, nargs='+', default=list(range(20)))
    ap.add_argument('--uhc-tau', type=float, default=0.6)
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--suffix', default='')
    ap.add_argument('--raw', action='store_true', help='rotate the raw EMG (fractional shifts allowed), C features')
    ap.add_argument('--summarize-only', action='store_true', help='--raw: re-write the summary from the per-block csv')
    args = ap.parse_args()
    t0 = time.time()
    if args.raw and args.summarize_only:
        acc = pd.read_csv(os.path.join(OUT, f'shift_sweep_raw{args.suffix}.csv'))
        s = summarize_raw(acc, args.shifts)
        s.to_csv(os.path.join(OUT, f'shift_sweep_raw_summary{args.suffix}.csv'), index=False, float_format='%.4g')
        print(s.round(3).to_string(index=False))
        return
    if args.raw:
        FC.lib()                                                     # build the C library once, before the workers
        Parallel(n_jobs=args.jobs, verbose=2)(delayed(prepare)(s, sh) for sh in args.shifts for s in args.subjects)
        print(f'features ready after {time.time() - t0:.0f} s', flush=True)
        tasks = [(s, seed, sh, m, args.uhc_tau, True) for sh in args.shifts for m in args.methods
                 for seed in args.seeds for s in args.subjects]
        res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(run)(*t) for t in tasks)
        acc = pd.DataFrame([r for rows in res for r in rows])
        acc.to_csv(os.path.join(OUT, f'shift_sweep_raw{args.suffix}.csv'), index=False, float_format='%.4f')
        s = summarize_raw(acc, args.shifts)
        s.to_csv(os.path.join(OUT, f'shift_sweep_raw_summary{args.suffix}.csv'), index=False, float_format='%.4g')
        pd.set_option('display.width', 250)
        print(s.round(3).to_string(index=False))
        print(f'took {time.time() - t0:.0f} s')
        return
    args.shifts = [int(sh) for sh in args.shifts]
    assert 'align' not in args.methods, 'align needs --raw'
    tasks = [(s, seed, sh, m, args.uhc_tau) for sh in args.shifts for m in args.methods for seed in args.seeds
             for s in args.subjects]
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(run)(*t) for t in tasks)
    acc = pd.DataFrame([r for rows in res for r in rows])
    acc.to_csv(os.path.join(OUT, f'shift_sweep{args.suffix}.csv'), index=False, float_format='%.4f')

    # per subject (mean over seeds and blocks), in %
    ps = acc.groupby(['shift', 'method', 'subject'])[['acc_fixed', 'acc_adapt']].mean() * 100
    out = []
    for sh in args.shifts:
        fixed = ps.loc[(sh, args.methods[0])].acc_fixed          # identical for both methods (same seed, same model)
        row = dict(shift=sh, fixed=fixed.mean())
        for m in args.methods:
            a = ps.loc[(sh, m)].acc_adapt
            d = a - fixed
            row[f'{m}'] = a.mean()
            row[f'{m}_minus_fixed'] = d.mean()
            row[f'{m}_better_than_fixed'] = int((d > 0).sum())
            row[f'{m}_p_vs_fixed'] = wilcoxon(a, fixed).pvalue if np.any(d != 0) else 1.0
            late = acc[(acc['shift'] == sh) & (acc.method == m) & (acc.block >= 8)].groupby('subject').acc_adapt.mean() * 100
            row[f'{m}_late_blocks'] = late.mean()
        if {'tsne', 'uhc'} <= set(args.methods):
            a, b = ps.loc[(sh, 'tsne')].acc_adapt, ps.loc[(sh, 'uhc')].acc_adapt
            row['tsne_minus_uhc'] = (a - b).mean()
            row['tsne_better_than_uhc'] = int((a - b > 0).sum())
            row['p_tsne_vs_uhc'] = wilcoxon(a, b).pvalue if np.any(a != b) else 1.0
        row['fixed_late_blocks'] = (acc[(acc['shift'] == sh) & (acc.method == args.methods[0]) & (acc.block >= 8)]
                                    .groupby('subject').acc_fixed.mean() * 100).mean()
        out.append(row)
    s = pd.DataFrame(out)
    s.to_csv(os.path.join(OUT, f'shift_sweep_summary{args.suffix}.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 250)
    print(s.round(3).to_string(index=False))
    print(f'took {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
