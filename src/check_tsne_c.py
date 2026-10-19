"""C Barnes-Hut t-SNE (src/c/tsne.c) vs sklearn TSNE on real self-calibration buffers, PC, single thread.

For every subject: the buffer is built as in tsne_cost.py (100 trees / depth 10 / int16 model, int16 buffer of
375, test blocks pushed with the model's predictions until full), class-balanced as manifold_clustering does,
with the true label of every row carried along. sklearn and C get the same initial embedding (1e-4 x standard
normal, seed 0) and the same settings (3-D, perplexity 10, angle 0.5). Compared:
  - exact KL(P || Q) of the final embedding (P: sklearn's sparse kNN P; Q: exact Student-t, dof 2, all pairs),
    i.e. how good each embedding is under the objective both minimise
  - pseudo-labels after the upstream steps (StandardScaler, K-Means initialised at the group centres of the
    model labels): agreement between C and sklearn, and accuracy of each against the true labels
  - CPU time (process_time) of the t-SNE call
Writes results/tsne_c_check.csv. Usage (in the container): python src/check_tsne_c.py [--iters 500 1000]
"""
import argparse
import copy
import os
import sys
import time

import numpy as np
import pandas as pd
import sklearn.preprocessing
from scipy.spatial.distance import pdist, squareform
from sklearn.cluster import KMeans
from sklearn.manifold import TSNE, _t_sne
from sklearn.neighbors import NearestNeighbors
from threadpoolctl import threadpool_limits

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import c_tsne  # noqa: E402
import pipeline as P  # noqa: E402
import rf_size  # noqa: E402
import selfcal_sweep as S  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')


def buffer_with_truth(subject, buf=375, seed=0):
    np.random.seed(seed * 1000 + subject)
    Xc, yc, blocks = P.load_subject(subject)
    pre = P.load_pretrain()
    pruned = P.prune(rf_size.truncate_depth(copy.deepcopy(pre), 10), Xc, yc)
    app = P.train_rf(Xc, yc, 50, 10, None)
    mdl = emg_functions.append(P.subset(pruned, range(50)), app)
    fb, lb = np.zeros((0, Xc.shape[1] + 1)), np.zeros((0,))
    for X, y in blocks:
        fb, lb = emg_functions.buffer_update(buf, fb, lb, np.c_[S.q16(X), y], P.predict(mdl, X, 'int16'))
        if len(lb) >= buf:
            break
    feat, truth = fb[:, :-1], fb[:, -1].astype(int)
    lab = P.predict(mdl, feat, 'int16')
    m = min(np.sum(lab == c) for c in S.LABELS)
    idx = np.concatenate([np.where(lab == c)[0][:m] for c in S.LABELS])
    return feat[idx], lab[idx], truth[idx]


def exact_kl(X, Y, perplexity=10.0):
    n = len(X)
    k = min(n - 1, int(3.0 * perplexity + 1))
    d = NearestNeighbors(n_neighbors=k).fit(X).kneighbors_graph(mode='distance')
    d.data **= 2
    Pm = _t_sne._joint_probabilities_nn(d, perplexity, 0).toarray()
    q = (1.0 + squareform(pdist(Y, 'sqeuclidean')) / 2.0) ** -1.5
    np.fill_diagonal(q, 0.0)
    q /= q.sum()
    m = Pm > 0
    return float(np.sum(Pm[m] * np.log(Pm[m] / np.maximum(q[m], 1e-300))))


def pseudo(Y, lab):
    Z = sklearn.preprocessing.StandardScaler().fit_transform(Y)
    km = KMeans(n_clusters=6, init=emg_functions.findGroupCenter(Z, lab), random_state=0, n_init=1).fit(Z)
    out = km.labels_.copy()
    if len(np.unique(out)) != 6:
        return lab.copy()
    return np.asarray(S.LABELS)[out]   # cluster c is initialised at class c's centre (upstream relabelling)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--subjects', type=int, nargs='+', default=list(range(20)))
    ap.add_argument('--iters', type=int, nargs='+', default=[500, 1000])
    args = ap.parse_args()
    threadpool_limits(1)
    rows = []
    for s in args.subjects:
        X, lab, truth = buffer_with_truth(s)
        Xq = P.quantize(X)
        assert np.array_equal(Xq.astype(np.float64) / 1024, X)   # buffer is on the Q5.10 grid
        rng = np.random.RandomState(0)
        init = 1e-4 * rng.standard_normal(size=(len(X), 3)).astype(np.float32)
        for it in args.iters:
            t0 = time.process_time()
            ys = TSNE(n_components=3, learning_rate='auto', init=init.copy(), perplexity=10, max_iter=it,
                      n_jobs=1).fit_transform(X)
            t_sk = time.process_time() - t0
            t0 = time.process_time()
            yc, st = c_tsne.run(Xq, it, 10.0, init)
            t_c = time.process_time() - t0
            ps, pc = pseudo(ys, lab), pseudo(yc.astype(np.float64), lab)
            rows.append(dict(subject=s, max_iter=it, n=len(X), kl_sklearn=exact_kl(X, ys), kl_c=exact_kl(X, yc),
                             agree_c_vs_sklearn=np.mean(ps == pc) * 100, acc_model=np.mean(lab == truth) * 100,
                             acc_pseudo_sklearn=np.mean(ps == truth) * 100, acc_pseudo_c=np.mean(pc == truth) * 100,
                             cpu_sklearn_s=t_sk, cpu_c_s=t_c, c_iters=st.n_iter, c_cells_max=st.cells_max,
                             c_overflow=st.cell_overflow, c_depth_max=st.tree_depth_max))
            print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in rows[-1].items()}, flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, 'tsne_c_check.csv'), index=False, float_format='%.5g')
    pd.set_option('display.width', 250)
    print(df.groupby('max_iter').mean(numeric_only=True).drop(columns='subject').round(3).to_string())
    print('static bytes (TSNE_NMAX 1500):', c_tsne.lib().tsne_static_bytes())


if __name__ == '__main__':
    main()
