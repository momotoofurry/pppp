"""Where does the one-shot accuracy of the on-device calibration differ from the sklearn pipeline? (ablation)

One-shot model = 50 pruned pre-trained trees (depth 10) + 50 trees trained on the 60 calibration rows, predicted
in int16 (Q5.10), 20 subjects x seeds, the 11 test blocks. Each variant changes one thing of the sklearn
pipeline (selfcal_sweep.py, same numpy seeds):
  sklearn         prune on the float z-scored rows / float thresholds (`<=`), sklearn trees on float rows
  prune_q16       prune on Q5.10 rows with the MCU rule x < T (thresholds (T - 0.5) / 1024)
  trees_c         trees from src/c/rf_train.c on the Q5.10 rows (own RNG, midpoint thresholds)
  trees_sk_q16    sklearn trees, but trained on the Q5.10 rows
  prune_q16+trees_c  both (the firmware, apart from the float32 z-score)
Writes results/oneshot_ablation.csv and _summary.csv. Usage: PYTHONPATH=src python src/diag_oneshot.py
"""
import copy
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.stats import wilcoxon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import c_train  # noqa: E402
import pipeline as P  # noqa: E402
import rf_size  # noqa: E402
import selfcal_sweep as S  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
VARIANTS = ['sklearn', 'prune_q16', 'trees_c', 'trees_sk_q16', 'prune_q16+trees_c']


def q16_thresholds(m):
    m = copy.deepcopy(m)
    m['threshold'] = [np.where(l >= 0, (P.quantize(t).astype(np.float64) - 0.5) / 1024, t)
                      for l, t in zip(m['left'], m['threshold'])]
    return m


def run(subject, seed):
    pre = P.load_pretrain()
    Xc, yc, blocks = P.load_subject(subject)
    Xq = S.q16(Xc)
    X = np.concatenate([b[0] for b in blocks])
    y = np.concatenate([b[1] for b in blocks])
    trunc = rf_size.truncate_depth(copy.deepcopy(pre), 10)
    rows = []
    for v in VARIANTS:
        np.random.seed(seed * 1000 + subject)                       # as selfcal_sweep.run_subject
        if 'prune_q16' in v:
            comp = rf_size.compact_forest(P.subset(trunc, range(50)))
            pr_part = emg_functions.prune(q16_thresholds(comp), Xq, yc)
            # predict with the stored Q5.10 thresholds (the -0.5 LSB copy was only for the `<=` of prune)
            pr_part['threshold'] = [np.where(l >= 0, t0, -2.0) for l, t0 in zip(pr_part['left'], comp['threshold'])]
        else:
            pr_part = P.subset(P.prune(trunc, Xc, yc), range(50))
        if 'trees_c' in v:
            app = c_train.train_rf(Xq, yc, 50, 10, 32)
        elif v == 'trees_sk_q16':
            app = P.train_rf(Xq, yc, 50, 10, None)
        else:
            app = P.train_rf(Xc, yc, 50, 10, None)
        mdl = emg_functions.append(P.subset(pr_part, range(50)), app)
        rows.append(dict(subject=subject, seed=seed, variant=v, acc_oneshot=np.mean(P.predict(mdl, X, 'int16') == y)))
    return rows


def main():
    c_train.build()
    res = Parallel(n_jobs=20, verbose=5)(delayed(run)(s, sd) for sd in [0, 1, 2] for s in range(20))
    df = pd.DataFrame([r for rr in res for r in rr])
    df.to_csv(os.path.join(OUT, 'oneshot_ablation.csv'), index=False, float_format='%.5f')
    ref = df[df.variant == 'sklearn'].groupby('subject').acc_oneshot.mean() * 100
    out = []
    for v in VARIANTS:
        a = df[df.variant == v].groupby('subject').acc_oneshot.mean() * 100
        d = a - ref
        out.append(dict(variant=v, acc_oneshot=a.mean(), diff=d.mean(), better=int((d > 0).sum()),
                        worse=int((d < 0).sum()), p=wilcoxon(a, ref).pvalue if (d != 0).any() else 1.0))
    s = pd.DataFrame(out)
    s.to_csv(os.path.join(OUT, 'oneshot_ablation_summary.csv'), index=False, float_format='%.4g')
    print(s.round(3).to_string(index=False))


if __name__ == '__main__':
    main()
