"""How many EMG channels does the self-calibrating RF need? 2-fold cross-validation on the arm_position data.

The 66-participant pre-trained model cannot be reduced to fewer channels (its trees split on all 80 features), so
for every channel subset the pre-trained forest is re-trained, on the other fold, with that subset's features only:
  fold A: pre-train on subjects 10-19 (group B), test on subjects 0-9 (group A); fold B: the other way round.
  Pre-training data = calibration + all 11 test blocks of each training subject, normalised per subject with its own
  calibration statistics (as pipeline.load_subject); 200 trees, max_depth None, bootstrap with 1,888 rows per tree
  (the per-tree sample count of the 66-participant model, max_samples = 0.01 of 188.8 k windows), max_features sqrt.
The test subjects then go through the recommended MCU setting exactly as selfcal_sweep.py:
  100 trees, depth 10, int16; one-shot = truncate + prune the pre-trained forest with the calibration data, keep 50,
  append 50 calibration trees; self-calibration with a 375-row int16 buffer, t-SNE (500 iterations) + K-Means,
  20 new trees with <= 32 leaves per block. Same RNG use as selfcal_sweep.run_subject.
Channel c (0-7) has the features at columns c, c+8, ..., c+72 (pipeline.FEATS order).
Reference variant 'all8_pre66' runs the same setting with the authors' 66-participant model (no cross-validation),
so the effect of the smaller pre-training pool (10 subjects) is visible next to the effect of fewer channels.
Writes results/channel_sweep.csv (per subject/block/seed), results/channel_sweep_summary.csv.
Usage (in the container): python src/channel_sweep.py [--seeds 0 1 2] [--jobs 20] [--sets all8 opp15 ...]
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
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
N_FEAT = len(P.FEATS)
# channel subsets (0-based); evenly spaced around the ring by index. The physical neighbourhood of the indices is
# not documented by the authors (channels 0-3 and 4-7 each form a chain of correlated neighbours).
SETS = {   # names use the 1-based channel numbers of the data set
    'all8': [0, 1, 2, 3, 4, 5, 6, 7],
    'drop1-5': [1, 2, 3, 5, 6, 7], 'drop2-6': [0, 2, 3, 4, 6, 7], 'drop3-7': [0, 1, 3, 4, 5, 7],
    'drop4-8': [0, 1, 2, 4, 5, 6],
    'ch1357': [0, 2, 4, 6], 'ch2468': [1, 3, 5, 7],
    'ch1-5': [0, 4], 'ch3-7': [2, 6],
}
FOLDS = {'A': (list(range(0, 10)), list(range(10, 20))), 'B': (list(range(10, 20)), list(range(0, 10)))}  # test, pretrain
N, DEPTH, PREC, BUF, MLN, IT = 100, 10, 'int16', 375, 32, 500
PRE_TREES, PRE_ROWS = 200, 1888


def cols(ch):
    return [f * 8 + c for f in range(N_FEAT) for c in ch]


def pretrain(train_subjects, ch, seed):
    from sklearn.ensemble import RandomForestClassifier
    Xs, ys = [], []
    for s in train_subjects:
        Xc, yc, blocks = P.load_subject(s)
        Xs += [Xc] + [b[0] for b in blocks]
        ys += [yc] + [b[1] for b in blocks]
    X, y = np.concatenate(Xs)[:, cols(ch)], np.concatenate(ys)
    rf = RandomForestClassifier(n_estimators=PRE_TREES, max_samples=PRE_ROWS, random_state=seed, n_jobs=1)
    rf.fit(X, y)
    return emg_functions.get_sklearn_rf_parameters(rf), len(y)


def run_subject(subject, set_name, ch, pre, seed, fold):
    """selfcal_sweep.run_subject for the recommended setting, on the channel subset `ch`, with pre-trained `pre`"""
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), PREC), None)
    emg_functions.TSNE = S.tsne_with(IT, S.PERPLEXITY)
    np.random.seed(seed * 1000 + subject)
    Xc, yc, blocks = P.load_subject(subject)
    k = cols(ch)
    Xc = Xc[:, k]
    blocks = [(X[:, k], y) for X, y in blocks]
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
        rows.append(dict(set=set_name, n_channels=len(ch), channels=' '.join(str(c + 1) for c in ch), fold=fold,
                         seed=seed, subject=subject, block=b,
                         acc_oneshot=np.mean(lab_os == y), acc_selfcal=np.mean(lab_sc == y)))
        feat_buf, lab_buf = emg_functions.buffer_update(BUF, feat_buf, lab_buf, S.q16(X), lab_sc)
        feat_sel, lab_pseudo, lab_buf = emg_functions.manifold_clustering(
            feat_buf, list(S.LABELS), S.MIN_SAMPLE_CLASS, mdl_os, 'kmeans', embedding='tsne')
        new = P.train_rf(np.concatenate([feat_sel, S.q16(Xc)]), np.concatenate([lab_pseudo, yc]), n_upd, DEPTH, None, MLN)
        idx_remain = np.concatenate([np.arange(n_pre), np.random.permutation(range(n_pre, N))[:n_app - n_upd]])
        mdl_sc = emg_functions.replace(mdl_sc, new, idx_remain)
    return rows


def job(set_name, ch, seed, fold):
    """one (channel set, seed, fold): pre-train on the training fold, run all its test subjects"""
    if fold == 'pre66':
        pre, n_rows = P.load_pretrain(), None
        test = list(range(20))
    else:
        test, train = FOLDS[fold]
        pre, n_rows = pretrain(train, ch, seed * 100 + (0 if fold == 'A' else 1))
    rows = []
    for s in test:
        rows += run_subject(s, set_name, ch, pre, seed, fold)
    for r in rows:
        r['pretrain_rows'] = n_rows
    return rows


def ram_bytes(n_ch, buf=BUF, n_cal=60, classes=6):
    """the dimension-dependent RAM items of analyze_leaf_buffer.ram(), for n_ch channels (int16 buffer): buffer +
    calibration set, K-Means centres, feature extraction state (scales with the channel count)"""
    dim = N_FEAT * n_ch
    feat = (400 * 8 * 4 + 4 * 2 * 8 * 4 + 2 * 512 * 4 + 257 * 4) * n_ch / 8
    return buf * dim * 2 + n_cal * dim * 2 + 2 * classes * dim * 4 + feat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--jobs', type=int, default=20)
    ap.add_argument('--sets', nargs='+', default=list(SETS))
    ap.add_argument('--no-pre66', action='store_true', help='skip the reference run with the authors\' model')
    ap.add_argument('--suffix', default='')
    args = ap.parse_args()
    t0 = time.time()
    tasks = [(n, SETS[n], seed, fold) for n in args.sets for seed in args.seeds for fold in FOLDS]
    if not args.no_pre66:
        tasks += [('all8_pre66', SETS['all8'], seed, 'pre66') for seed in args.seeds]
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(job)(*t) for t in tasks)
    acc = pd.DataFrame([r for rows in res for r in rows])
    acc.to_csv(os.path.join(OUT, f'channel_sweep{args.suffix}.csv'), index=False, float_format='%.4f')

    per_subj = acc.groupby(['set', 'subject'])[['acc_oneshot', 'acc_selfcal']].mean() * 100
    ref = per_subj.loc['all8'] if 'all8' in per_subj.index.get_level_values(0) else None
    rows = []
    for name, g in acc.groupby('set', sort=False):
        per_seed = g.groupby('seed')[['acc_oneshot', 'acc_selfcal']].mean() * 100
        ps = per_subj.loc[name]
        n_ch = int(g.n_channels.iloc[0])
        row = dict(set=name, n_channels=n_ch, channels=g.channels.iloc[0],
                   pretrain='authors 66' if name == 'all8_pre66' else '10 (2-fold)',
                   acc_oneshot=per_seed.acc_oneshot.mean(), acc_selfcal=per_seed.acc_selfcal.mean(),
                   gain=(per_seed.acc_selfcal - per_seed.acc_oneshot).mean(),
                   selfcal_seed_min=per_seed.acc_selfcal.min(), selfcal_seed_max=per_seed.acc_selfcal.max(),
                   n_seeds=len(per_seed), n_subjects=len(ps),
                   ram_dim_dependent_KB=ram_bytes(n_ch) / 1024,
                   ram_saved_vs_8ch_KB=(ram_bytes(8) - ram_bytes(n_ch)) / 1024)
        if ref is not None and name not in ('all8', 'all8_pre66'):
            for m in ['acc_oneshot', 'acc_selfcal']:
                d = ps[m] - ref[m]
                row[f'{m}_diff_vs_all8'] = d.mean()
                row[f'{m}_better_vs_all8'] = int((d > 0).sum())
                row[f'{m}_p_vs_all8'] = wilcoxon(ps[m], ref[m]).pvalue if np.any(d != 0) else 1.0
        rows.append(row)
    s = pd.DataFrame(rows)
    s.to_csv(os.path.join(OUT, f'channel_sweep_summary{args.suffix}.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 250)
    print(s.round(3).to_string(index=False))
    print(f'took {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
