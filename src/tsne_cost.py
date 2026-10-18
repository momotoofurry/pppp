"""Cost of the t-SNE step of self-calibration vs. buffer size, measured on the PC (single thread).

For each buffer size, the buffer is built exactly as in self-calibration (subject s, 100 trees / depth 10
/ int16 model, int16 buffer, test blocks pushed with the model's predictions until the buffer is full) and
the upstream t-SNE call is timed (sklearn TSNE: 3-D, perplexity 10, Barnes-Hut angle 0.5, init='random',
learning_rate='auto', same as emg_functions.manifold_clustering). Records wall time, the iterations
actually run (n_iter_), the final KL divergence, and the number of neighbours used. Also counts, from
the sklearn Barnes-Hut algorithm, a rough work model per iteration (n x neighbours attractive terms +
n x log2(n) octree interactions), which scales the PC number to other buffer sizes; it is NOT an MCU
cycle count — that has to be measured on the board.
--iters times each buffer with these t-SNE iteration counts (sklearn max_iter, default 1000 = upstream; the
same TSNE input and seed for every count), --perplexities with these perplexities (default 10 = upstream;
neighbours = 3 x perplexity + 1). --sizes picks the buffer sizes.
Writes results/tsne_cost<suffix>.csv. Usage (in the container): python src/tsne_cost.py [--subjects 0 1 2]
       python src/tsne_cost.py --sizes 375 --iters 250 500 1000 --suffix _iter
       python src/tsne_cost.py --sizes 375 --iters 500 1000 --perplexities 3 5 7 10 --suffix _px
"""
import argparse
import os
import sys
import time

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as P  # noqa: E402
import selfcal_sweep as S  # noqa: E402
from pipeline import emg_functions  # noqa: E402
import copy  # noqa: E402
import rf_size  # noqa: E402
from sklearn.manifold import TSNE  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
SIZES = [1500, 1000, 750, 500, 375, 250]


def buffer_for(subject, buf, seed=0):
    np.random.seed(seed * 1000 + subject)
    Xc, yc, blocks = P.load_subject(subject)
    pre = P.load_pretrain()
    pruned = P.prune(rf_size.truncate_depth(copy.deepcopy(pre), 10), Xc, yc)
    app = P.train_rf(Xc, yc, 50, 10, None)
    mdl = emg_functions.append(P.subset(pruned, range(50)), app)
    fb, lb = np.zeros((0, Xc.shape[1])), np.zeros((0,))
    for X, _ in blocks:
        fb, lb = emg_functions.buffer_update(buf, fb, lb, S.q16(X), P.predict(mdl, X, 'int16'))
        if len(lb) >= buf:
            break
    # class-balance as manifold_clustering does before t-SNE (min class count per class)
    lab = P.predict(mdl, fb, 'int16')
    m = min(np.sum(lab == c) for c in S.LABELS)
    sel = np.concatenate([fb[lab == c][:m] for c in S.LABELS])
    return sel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--subjects', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--sizes', type=int, nargs='+', default=SIZES)
    ap.add_argument('--iters', type=int, nargs='+', default=[S.TSNE_ITER])
    ap.add_argument('--perplexities', type=float, nargs='+', default=[S.PERPLEXITY])
    ap.add_argument('--suffix', default='')
    args = ap.parse_args()
    threadpool_limits(1)
    rows = []
    for s in args.subjects:
        for buf in args.sizes:
            X = buffer_for(s, buf)
            n = len(X)
            for px in args.perplexities:
                for it in args.iters:
                    np.random.seed(0)
                    ts = TSNE(n_components=3, learning_rate='auto', init='random', perplexity=px, n_jobs=1, max_iter=it)
                    t0 = time.process_time()
                    ts.fit_transform(X)
                    cpu = time.process_time() - t0
                    k = min(n - 1, int(3.0 * px + 1))
                    work = ts.n_iter_ * (n * k + n * np.log2(n))
                    rows.append(dict(subject=s, buffer=buf, perplexity=px, max_iter=it, n_tsne=n, neighbours=k,
                                     n_iter=ts.n_iter_, kl=ts.kl_divergence_, cpu_s=cpu, work_units=work))
                    print(rows[-1], flush=True)
    df = pd.DataFrame(rows)
    if args.perplexities == [S.PERPLEXITY]:
        df = df.drop(columns='perplexity')   # same columns as before the options
    if args.iters == [S.TSNE_ITER]:
        df = df.drop(columns='max_iter')
    df.to_csv(os.path.join(OUT, f'tsne_cost{args.suffix}.csv'), index=False, float_format='%.5g')
    key = ['buffer'] + [c for c in ['perplexity', 'max_iter'] if c in df]
    g = df.groupby(key, sort=False).agg(n_tsne=('n_tsne', 'mean'), n_iter=('n_iter', 'mean'), kl=('kl', 'mean'),
                                        cpu_s=('cpu_s', 'mean'), work_units=('work_units', 'mean'))
    g['cpu_s_rel_first'] = g.cpu_s / g.cpu_s.iloc[0]
    print(g.round(3).to_string())


if __name__ == '__main__':
    main()
