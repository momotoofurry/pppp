"""Baseline [8] (Zanghieri et al., BioCAS 2023): label-free PCA alignment of the input, classifier unchanged.

Their method (github.com/pulp-bio/online-semg-posture-adaptation, protocol.calibration_experiment): the classifier is
trained on the PCs of the standardised channels of the reference session; on a new session the mean, scale and PCs
are re-estimated without labels (Oja SGA initialised with the reference PCs), the new PCs are reordered and
sign-matched to the reference PCs (pca.reorder_w_like_reference_pca), and the new data is projected with them.
Here, for our RF on 80 features (10 features x 8 channels), per feature type f the same is done in channel space
(8 x 8): reference = day-1 calibration, new = test block 0 (unlabelled, the same data as our start-up alignment);
x_f -> mu_ref + s_ref * (W_ref @ W_new_ord.T @ ((x_f - mu_new) / s_new)), i.e. the new PC coordinates are put back
into the reference feature space, so the unchanged one-shot model (day-1 z-score) classifies them. Batch PCA
(numpy eigh) is used instead of Oja SGA: the converged solution, i.e. the best case of the online estimate.
Variants (each with the same one-shot model as zscore_sweep.run / aug_sweep.py: same numpy seed):
  fixed       one-shot model, no adaptation, no start-up alignment
  pca         [8]: PCA alignment from block 0, one-shot model unchanged
  pca_cum     [8] re-estimated causally: block b uses the PCs of blocks 0..b-1 (block 0 uses block 0)
The firmware v2 numbers (start-up alignment + self-calibration + class-balanced z-score update, same seeds and
one-shot model) are read from results/aug_sweep.csv (aug = 'none') for the paired comparison.
Writes results/pca_baseline.csv (per run and block) and results/pca_baseline_summary.csv.
Usage (in the container): python src/pca_baseline.py [--jobs 19]
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
import pipeline as P  # noqa: E402
import rf_size  # noqa: E402
import selfcal_sweep as S  # noqa: E402
import shift_sweep as SH  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
N, DEPTH, PREC = SH.N, SH.DEPTH, SH.PREC
NF = len(P.FEATS)
VARIANTS = ['fixed', 'pca', 'pca_cum']


def pcs(Z):
    """principal axes of the standardised rows Z (n x 8), columns sorted by decreasing variance"""
    w, V = np.linalg.eigh(np.cov(Z, rowvar=False))
    return V[:, np.argsort(w)[::-1]]


def reorder_like(W, W_ref):
    """pca.reorder_w_like_reference_pca of [8]: greedy match of every reference PC to the new PC with the largest
    squared projection, then the sign of the reference"""
    props = np.square(W_ref.T @ W)
    taken = []
    for i in range(W.shape[1]):
        for j in np.argsort(props[i])[::-1]:
            if j not in taken:
                taken.append(j)
                break
    W = W[:, taken]
    return W * np.sign(np.diag(W_ref.T @ W))


class Align:
    """per feature type: reference statistics of the calibration, new statistics of the given rows"""

    def __init__(self, Xc):
        self.ref = [self._stats(Xc[:, f * 8:(f + 1) * 8]) for f in range(NF)]
        self.new = None

    @staticmethod
    def _stats(X):
        mu, s = X.mean(0), X.std(0)
        s = np.where(s > 0, s, 1.0)
        return mu, s, pcs((X - mu) / s)

    def fit(self, X):
        self.new = []
        for f in range(NF):
            mu, s, W = self._stats(X[:, f * 8:(f + 1) * 8])
            self.new.append((mu, s, reorder_like(W, self.ref[f][2])))

    def map(self, X):
        out = np.empty_like(X)
        for f in range(NF):
            (mr, sr, Wr), (mn, sn, Wn) = self.ref[f], self.new[f]
            z = (X[:, f * 8:(f + 1) * 8] - mn) / sn
            out[:, f * 8:(f + 1) * 8] = mr + sr * (z @ Wn @ Wr.T)
        return out


def run(subject, seed, shift, variant):
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), PREC), None)
    np.random.seed(seed * 1000 + subject)                            # as zscore_sweep.run: same one-shot model
    z = np.load(SH.prepare(subject, shift))
    Xc_raw, yc = z['Xc'], z['yc']
    blocks = [(z[f'X{b}'], z[f'y{b}']) for b in range(P.N_BLOCKS)]   # raw rotation, no start-up alignment
    mu, var = Xc_raw.mean(0), Xc_raw.var(0)
    Xc = (Xc_raw - mu) / np.sqrt(var)
    pre = P.load_pretrain(S.DATASETS['arm_position'][0])
    n_pre, n_app = N // 2, N - N // 2
    pruned = P.prune(rf_size.truncate_depth(copy.deepcopy(pre), DEPTH), Xc, yc)
    app = P.train_rf(Xc, yc, n_app, DEPTH, None)
    mdl_os = emg_functions.append(P.subset(pruned, range(n_pre)), app)
    al = Align(Xc_raw)
    if variant == 'pca':
        al.fit(blocks[0][0])
    rows = []
    seen = []
    for b, (X_raw, y) in enumerate(blocks):
        if variant == 'pca_cum':
            al.fit(np.concatenate(seen) if seen else X_raw)
        Xin = X_raw if variant == 'fixed' else al.map(X_raw)
        pred = P.predict(mdl_os, (Xin - mu) / np.sqrt(var), PREC)
        rows.append(dict(subject=subject, seed=seed, shift=shift, variant=variant, block=b, acc=np.mean(pred == y)))
        seen.append(X_raw)
    return rows


def summarize(acc, v2):
    ps = acc.groupby(['shift', 'variant', 'subject']).acc.mean().unstack(1) * 100
    v2s = v2.groupby(['shift', 'subject']).acc_adapt.mean() * 100
    out = []

    def paired(row, name, x, y):
        d = x - y
        row[f'{name}_diff'] = d.mean()
        row[f'{name}_better'] = int((d > 0).sum())
        row[f'{name}_p'] = wilcoxon(x, y).pvalue if np.any(d != 0) else 1.0

    for sh in sorted(set(acc['shift'])):
        g = ps.loc[sh]
        row = dict(shift=sh, **{v: g[v].mean() for v in VARIANTS if v in g})
        for v in ('pca', 'pca_cum'):
            if v in g:
                paired(row, f'{v}_vs_fixed', g[v], g['fixed'])
        if sh in v2s.index.get_level_values(0):
            row['v2'] = v2s.loc[sh].mean()
            for v in ('pca', 'pca_cum'):
                paired(row, f'v2_vs_{v}', v2s.loc[sh].reindex(g.index), g[v])
        out.append(row)
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--variants', nargs='+', default=VARIANTS, choices=VARIANTS)
    ap.add_argument('--shifts', type=float, nargs='+', default=[0, 0.25, 0.5, 1])
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--subjects', type=int, nargs='+', default=list(range(20)))
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--suffix', default='')
    args = ap.parse_args()
    t0 = time.time()
    import check_features_c as FC
    FC.lib()
    Parallel(n_jobs=args.jobs)(delayed(SH.prepare)(s, sh) for sh in args.shifts for s in args.subjects)
    tasks = [(s, sd, sh, v) for sh in args.shifts for v in args.variants for sd in args.seeds for s in args.subjects]
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(run)(*t) for t in tasks)
    acc = pd.DataFrame([r for rows in res for r in rows])
    acc.to_csv(os.path.join(OUT, f'pca_baseline{args.suffix}.csv'), index=False, float_format='%.4f')
    v2 = pd.read_csv(os.path.join(OUT, 'aug_sweep.csv'))
    v2 = v2[(v2.aug == 'none') & v2.seed.isin(args.seeds) & v2.subject.isin(args.subjects)]
    s = summarize(acc, v2)
    s.to_csv(os.path.join(OUT, f'pca_baseline_summary{args.suffix}.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 250)
    print(s.round(3).to_string(index=False))
    print(f'took {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
