"""Can a cheap linear projection replace t-SNE before K-Means in the self-calibration pseudo-labelling?

t-SNE is the largest block of the firmware RAM (92.5 KB of 223.8 KB, results/ram_history.csv) and the slowest step
(PC ~1 s per block). Colot et al. 2026 (BSPC 111:108283) get label-free pseudo-labels from LDA + K-Means alone.
The upstream manifold_clustering is used unchanged; only the object it calls as TSNE(...).fit_transform(X) is
replaced (its output is standardised and clustered by K-Means initialised at the one-shot model's class centres,
exactly as for t-SNE). Embeddings (--embed):
  tsne      current pipeline (sklearn t-SNE, 3-D, perplexity 10, 500 iterations)
  none      no embedding: K-Means on the 80 features (embedding=None upstream)
  ldacal5   LDA fitted once on the day-1 calibration set (labelled, already on the device), 5 components;
            on the device an 80 x 5 matrix computed at calibration time (1.6 KB float32)
  ldacal3   the same with 3 components
  ldabuf5   LDA re-fitted on the buffer itself with pseudo-labels, alternating with K-Means (Colot-style):
            labels from the one-shot model -> LDA (5 comp.) -> K-Means (init at class means) -> LDA ... 3 rounds,
            the last projection is returned; on the device two 80 x 80 scatter matrices + an eigen-solver
  pca5      unsupervised reference: PCA of the buffer, 5 components
Data and setting as zscore_sweep.py (z-score not updated): arm_position 20 subjects x 11 blocks x 3 seeds with the
66-participant model, C features, electrode offsets --shifts with the start-up alignment; demo 1 subject x 10 seeds.
MCU setting: 100 trees, depth 10, int16, int16 buffer of 375, 20 new trees <= 32 leaves.
Records per block the accuracies and the CPU time of the embedding call (PC, one core, only indicative).
Writes results/embed_sweep.csv and results/embed_sweep_summary.csv.
Usage (in the container): python src/embed_sweep.py [--jobs 19]
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
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as P  # noqa: E402
import rf_size  # noqa: E402
import selfcal_sweep as S  # noqa: E402
import shift_sweep as SH  # noqa: E402
import zscore_sweep as Z  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
N, DEPTH, PREC, BUF, MLN, IT = SH.N, SH.DEPTH, SH.PREC, SH.BUF, SH.MLN, SH.IT
EMBEDS = ['tsne', 'none', 'ldacal5', 'ldacal3', 'ldabuf5', 'pca5']
TIMES = []                                                           # CPU seconds of each embedding call (per worker)


class Linear:
    """stands in for TSNE(...): fit_transform(X) returns a linear projection of the buffer rows"""

    def __init__(self, embed, lda_cal=None, mdl_os=None):
        self.embed, self.lda_cal, self.mdl_os = embed, lda_cal, mdl_os

    def fit_transform(self, X):
        t0 = time.process_time()
        if self.embed.startswith('ldacal'):
            Zx = self.lda_cal.transform(X)
        elif self.embed == 'pca5':
            Zx = PCA(n_components=5, random_state=0).fit_transform(X)
        else:                                                        # ldabuf5: LDA <-> K-Means on the buffer
            lab = P.predict(self.mdl_os, X, PREC)
            for _ in range(3):
                if len(np.unique(lab)) < 2:
                    break
                lda = LinearDiscriminantAnalysis(n_components=min(5, len(np.unique(lab)) - 1)).fit(X, lab)
                Zx = lda.transform(X)
                cls = np.unique(lab)
                km = KMeans(n_clusters=len(cls), init=np.stack([Zx[lab == c].mean(0) for c in cls]), n_init=1,
                            random_state=0).fit(Zx)
                lab = cls[km.labels_]
        TIMES.append(time.process_time() - t0)
        return Zx


def run(dataset, subject, seed, shift, embed):
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), PREC), None)
    np.random.seed(seed * 1000 + subject)
    Xc_raw, yc, blocks, k_est = Z.load(dataset, subject, shift)
    mu, sd = Xc_raw.mean(0), Xc_raw.std(0)
    Xc = (Xc_raw - mu) / sd
    pre = P.load_pretrain(S.DATASETS[dataset][0])
    n_pre, n_app = N // 2, N - N // 2
    n_upd = int(round(S.REPLACE_FRAC * n_app))
    pruned = P.prune(rf_size.truncate_depth(copy.deepcopy(pre), DEPTH), Xc, yc)
    app = P.train_rf(Xc, yc, n_app, DEPTH, None)
    mdl_os = emg_functions.append(P.subset(pruned, range(n_pre)), app)
    mdl_sc = copy.deepcopy(mdl_os)
    if embed == 'tsne':
        tsne = S.tsne_with(IT, S.PERPLEXITY)

        def timed(**kw):
            obj = tsne(**kw)
            ft = obj.fit_transform

            def f(X):
                t0 = time.process_time()
                r = ft(X)
                TIMES.append(time.process_time() - t0)
                return r
            obj.fit_transform = f
            return obj
        emg_functions.TSNE = timed
    elif embed != 'none':
        lda_cal = None
        if embed.startswith('ldacal'):
            lda_cal = LinearDiscriminantAnalysis(n_components=int(embed[-1])).fit(S.q16(Xc), yc)
        emg_functions.TSNE = lambda **kw: Linear(embed, lda_cal, mdl_os)
    feat_buf, lab_buf = np.zeros((0, Xc.shape[1])), np.zeros((0,))
    rows = []
    for b, (X_raw, y) in enumerate(blocks):
        X = (X_raw - mu) / sd
        lab_os, lab_sc = P.predict(mdl_os, X, PREC), P.predict(mdl_sc, X, PREC)
        TIMES.clear()
        feat_buf, lab_buf = emg_functions.buffer_update(BUF, feat_buf, lab_buf, S.q16(X), lab_sc)
        feat_sel, lab_pseudo, lab_buf = emg_functions.manifold_clustering(
            feat_buf, list(S.LABELS), S.MIN_SAMPLE_CLASS, mdl_os, 'kmeans',
            embedding=None if embed == 'none' else 'tsne')
        rows.append(dict(dataset=dataset, subject=subject, seed=seed, shift=shift, embed=embed, block=b, k_est=k_est,
                         acc_fixed=np.mean(lab_os == y), acc_adapt=np.mean(lab_sc == y),
                         embed_cpu_s=sum(TIMES) if TIMES else np.nan))
        if len(lab_pseudo) >= 10:
            new = P.train_rf(np.concatenate([feat_sel, S.q16(Xc)]), np.concatenate([lab_pseudo, yc]), n_upd, DEPTH,
                             None, MLN)
            idx_remain = np.concatenate([np.arange(n_pre), np.random.permutation(range(n_pre, N))[:n_app - n_upd]])
            mdl_sc = emg_functions.replace(mdl_sc, new, idx_remain)
    return rows


def summarize(acc):
    ps = acc.groupby(['dataset', 'shift', 'embed', 'subject'])[['acc_fixed', 'acc_adapt']].mean() * 100
    tm = acc.groupby(['dataset', 'shift', 'embed']).embed_cpu_s.mean()
    out = []
    for (ds, sh), g in ps.groupby(level=[0, 1]):
        ref = g.xs('tsne', level='embed').droplevel([0, 1])
        for e in EMBEDS:
            if e not in g.index.get_level_values('embed'):
                continue
            cur = g.xs(e, level='embed').droplevel([0, 1])
            d = cur.acc_adapt - ref.acc_adapt
            g_ = cur.acc_adapt - cur.acc_fixed
            out.append(dict(dataset=ds, shift=sh, embed=e, n_subjects=len(cur), fixed=cur.acc_fixed.mean(),
                            adapt=cur.acc_adapt.mean(), gain=g_.mean(),
                            gain_p=wilcoxon(cur.acc_adapt, cur.acc_fixed).pvalue if len(d) > 5 and np.any(g_ != 0) else np.nan,
                            vs_tsne=d.mean(), better_than_tsne=int((d > 0).sum()),
                            vs_tsne_p=wilcoxon(cur.acc_adapt, ref.acc_adapt).pvalue if len(d) > 5 and np.any(d != 0) else np.nan,
                            embed_cpu_s=tm.loc[(ds, sh, e)]))
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--embed', nargs='+', default=EMBEDS, choices=EMBEDS)
    ap.add_argument('--shifts', type=float, nargs='+', default=[0, 0.5])
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--demo-seeds', type=int, default=10)
    ap.add_argument('--subjects', type=int, nargs='+', default=list(range(20)))
    ap.add_argument('--no-demo', action='store_true')
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--suffix', default='')
    args = ap.parse_args()
    t0 = time.time()
    import check_features_c as FC
    FC.lib()
    Parallel(n_jobs=args.jobs)(delayed(SH.prepare)(s, sh) for sh in args.shifts for s in args.subjects)
    tasks = [('arm_position', s, seed, sh, e) for sh in args.shifts for e in args.embed for seed in args.seeds
             for s in args.subjects]
    if not args.no_demo:
        tasks += [('demo', 0, seed, 0.0, e) for e in args.embed for seed in range(args.demo_seeds)]
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(run)(*t) for t in tasks)
    acc = pd.DataFrame([r for rows in res for r in rows])
    acc.to_csv(os.path.join(OUT, f'embed_sweep{args.suffix}.csv'), index=False, float_format='%.4f')
    s = summarize(acc)
    s.to_csv(os.path.join(OUT, f'embed_sweep_summary{args.suffix}.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 250)
    print(s.round(3).to_string(index=False))
    print(f'took {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
