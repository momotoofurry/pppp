"""Can the order of the authors' channels 1-8 be read from the signals? Two questions, on dataset_arm_position:

A. Which channels are neighbours (ring order, not documented by the authors)?
   Neighbouring electrodes share crosstalk, so their band-passed raw EMG correlate more. Per subject: 4th-order
   Butterworth 10-500 Hz (as upstream feature extraction, lfilter), Pearson correlation of the 8 channels for every
   trial of calibration + all test blocks, mean over trials (Fisher z). The ring order is the Hamiltonian cycle with
   the largest summed neighbour correlation (all 2,520 cycles of 8 nodes). Reported for the mean over subjects and
   per subject (how often the subject's best cycle equals the group's, and how often each pair is adjacent in it).
   The order assumed by shift_sweep.py (1-2-...-8-1) is scored the same way.

B. Can a scrambled channel order be recovered (as with a pilot recording whose placement is known)?
   Leave one subject out: the subject's channels are shuffled (10 random permutations + identity); the reference
   is built from the other 19 subjects only. Matching methods:
     gesture  per channel and gesture: mean log RMS / WL and mean MNF over the subject's labelled windows
              (calibration + all blocks); log features centred per channel over gestures (relative pattern) plus the
              channel's mean log RMS centred over channels; distance to the reference mean, each dimension divided
              by its across-subject std; best one-to-one assignment (linear, Hungarian).
     corr     match the subject's correlation matrix (A) to the reference mean: maximise
              sum_ij C_test[i, j] * C_ref[p(i), p(j)] over all 8! = 40,320 permutations.
     both     z-scored sum of the two scores, all 8! permutations.
     model    the 50 best permutations of 'both', re-ranked by the accuracy of the authors' 66-participant model
              (200 trees, float, no one-shot; the 20 arm_position participants are not in its training set) on
              the subject's labelled windows after re-ordering.
   Per permutation: all 8 correct, number of correct channels, and the 66-participant model's accuracy with the
   recovered vs the true order.
Writes results/channel_order_corr.csv (mean correlation matrix), channel_order_ring.csv (part A),
channel_order_match.csv (part B, one row per subject / permutation / method), channel_order_summary.csv.
Usage (in the container): python src/channel_order.py [--perms 10] [--jobs 19]
"""
import argparse
import itertools
import os
import sys
import time

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy import signal
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as P  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
FS = 2000
FOLDERS = ['calibration'] + [f'testing_block{b}' for b in range(P.N_BLOCKS)]
LOGF = [P.FEATS.index(f) for f in ('rms', 'wl')]
LINF = [P.FEATS.index('mnf')]
RMS = P.FEATS.index('rms')
PERMS = np.array(list(itertools.permutations(range(8))))            # 40,320 x 8
TOP_MODEL = 50


def corr_matrix(subject):
    b, a = signal.butter(4, (10 * 2 / FS, 500 * 2 / FS), btype='bandpass')
    zs = []
    for folder in FOLDERS:
        data = np.load(os.path.join(P.REPO, 'dataset_arm_position', str(subject), folder, 'data.npy'))
        for rec in data:
            x = signal.lfilter(b, a, rec, axis=-1)
            c = np.clip(np.corrcoef(x), -0.999999, 0.999999)
            zs.append(np.arctanh(c))
    return np.tanh(np.mean(zs, axis=0))


def cycles():
    """all Hamiltonian cycles of 8 nodes, starting at node 0, each direction once (2,520)"""
    out = []
    for p in itertools.permutations(range(1, 8)):
        if p[0] < p[-1]:
            out.append((0,) + p)
    return out


def cycle_score(C, cyc):
    return sum(C[cyc[i], cyc[(i + 1) % 8]] for i in range(8))


def ring_name(cyc):
    return '-'.join(str(c + 1) for c in cyc)


def subject_data(subject):
    """labelled unnormalised features (all folders) and the per-subject fingerprint"""
    Xs, ys = zip(*[P.load_folder('arm_position', subject, f) for f in FOLDERS])
    X, y = np.concatenate(Xs), np.concatenate(ys)
    return X, y


def fingerprint(X, y):
    """(8, d) per-channel descriptor; columns of X are feature * 8 + channel"""
    g = np.unique(y)
    parts = []
    for f in LOGF:
        m = np.stack([np.log(np.maximum(X[y == k, f * 8:(f + 1) * 8], 1e-12)).mean(0) for k in g], axis=1)  # 8 x G
        parts.append(m - m.mean(1, keepdims=True))                   # relative gesture pattern per channel
    for f in LINF:
        parts.append(np.stack([X[y == k, f * 8:(f + 1) * 8].mean(0) for k in g], axis=1))
    lr = np.log(np.maximum(X[:, RMS * 8:(RMS + 1) * 8], 1e-12)).mean(0)
    parts.append((lr - lr.mean())[:, None])                          # channel's overall level vs the others
    return np.concatenate(parts, axis=1)


def permute_cols(X, perm):
    """recording whose channel i is original channel perm[i]: column f*8 + i <- f*8 + perm[i]"""
    return X[:, [f * 8 + perm[i] for f in range(len(P.FEATS)) for i in range(8)]]


def standardize(v):
    return (v - v.mean()) / v.std()


def match_one(subject, seed, n_perm, fps, cms):
    """leave `subject` out; `fps` / `cms`: fingerprints / correlation matrices of all subjects"""
    others = [s for s in range(len(fps)) if s != subject]
    ref_fp = np.mean([fps[s] for s in others], axis=0)
    sd = np.std([fps[s] for s in others], axis=0) + 1e-9
    ref_c = np.mean([cms[s] for s in others], axis=0)
    X, y = subject_data(subject)
    mu, sdx = X.mean(0), X.std(0)
    pre = P.load_pretrain()
    rng = np.random.default_rng(seed * 1000 + subject)
    perms = [np.arange(8)] + [rng.permutation(8) for _ in range(n_perm)]
    acc_cache = {}

    def acc_with(order):
        """model accuracy when channel i of the model reads original channel order[i]"""
        key = tuple(order)
        if key not in acc_cache:
            Xo = permute_cols(X, order)
            acc_cache[key] = float(np.mean(P.predict(pre, (Xo - permute_cols(mu[None], order)) /
                                                      permute_cols(sdx[None], order), 'float64') == y))
        return acc_cache[key]

    rows = []
    acc_true = acc_with(np.arange(8))
    for k, perm in enumerate(perms):
        # scrambled recording: its channel i is original channel perm[i]
        fp = fingerprint(permute_cols(X, perm), y)
        C = cms[subject][np.ix_(perm, perm)]
        # cost[i, j]: scrambled channel i vs reference position j
        cost = (((fp[:, None, :] - ref_fp[None, :, :]) / sd[None]) ** 2).sum(-1)
        s_gest = -cost[np.arange(8)[None, :], PERMS].sum(1)          # PERMS[q][i] = position assigned to channel i
        s_corr = np.einsum('qij,ij->q', ref_c[PERMS[:, :, None], PERMS[:, None, :]], C)
        s_both = standardize(s_gest) + standardize(s_corr)
        r_, c_ = linear_sum_assignment(cost)
        est = {'gesture': c_[np.argsort(r_)], 'corr': PERMS[np.argmax(s_corr)], 'both': PERMS[np.argmax(s_both)]}
        top = PERMS[np.argsort(-s_both)[:TOP_MODEL]]
        inv_acc = []
        for q in top:                                                # q[i] = position of scrambled channel i
            order = np.empty(8, int)
            order[q] = perm                                          # position q[i] reads original perm[i]
            inv_acc.append(acc_with(order))
        est['model'] = top[int(np.argmax(inv_acc))]
        for m, q in est.items():
            order = np.empty(8, int)
            order[q] = perm
            rows.append(dict(subject=subject, perm_id=k, perm=''.join(str(v + 1) for v in perm), method=m,
                             n_correct=int(np.sum(q == perm)), all_correct=bool(np.all(q == perm)),
                             acc_true_order=acc_true, acc_recovered=acc_with(order),
                             true_in_top=bool(any(np.all(t == perm) for t in top))))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--perms', type=int, default=10)
    ap.add_argument('--subjects', type=int, nargs='+', default=list(range(20)))
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--suffix', default='')
    args = ap.parse_args()
    t0 = time.time()
    n = 20
    cms = Parallel(n_jobs=args.jobs)(delayed(corr_matrix)(s) for s in range(n))
    print(f'correlations done after {time.time() - t0:.0f} s', flush=True)

    # ---------------------------------------------------------------- A: ring order
    Cm = np.mean(cms, axis=0)
    pd.DataFrame(Cm, index=range(1, 9), columns=range(1, 9)).to_csv(os.path.join(OUT, f'channel_order_corr{args.suffix}.csv'),
                                                                   float_format='%.4f')
    cyc = cycles()
    sc = np.array([cycle_score(Cm, c) for c in cyc])
    order = np.argsort(-sc)
    best = cyc[order[0]]
    per_best = [cyc[int(np.argmax([cycle_score(C, c) for c in cyc]))] for C in cms]
    adj = np.zeros((8, 8), int)
    for c in per_best:
        for i in range(8):
            a_, b_ = c[i], c[(i + 1) % 8]
            adj[a_, b_] += 1
            adj[b_, a_] += 1
    assumed = tuple(range(8))
    ring = [dict(rank=r + 1, ring=ring_name(cyc[i]), score=sc[i],
                 n_subjects_best=sum(c == cyc[i] for c in per_best)) for r, i in enumerate(order[:10])]
    ring.append(dict(rank=int(np.where(np.array([c == assumed for c in cyc])[order])[0][0]) + 1,
                     ring=ring_name(assumed) + ' (assumed)', score=cycle_score(Cm, assumed),
                     n_subjects_best=sum(c == assumed for c in per_best)))
    pd.DataFrame(ring).to_csv(os.path.join(OUT, f'channel_order_ring{args.suffix}.csv'), index=False, float_format='%.4f')
    print('mean correlation (channels 1-8):')
    print(pd.DataFrame(Cm, index=range(1, 9), columns=range(1, 9)).round(2).to_string())
    print('best rings:')
    print(pd.DataFrame(ring).to_string(index=False))
    print('per-subject best ring, how often each pair is adjacent (out of 20):')
    print(pd.DataFrame(adj, index=range(1, 9), columns=range(1, 9)).to_string())

    # ---------------------------------------------------------------- B: recover a scrambled order
    fps = [fingerprint(*subject_data(s)) for s in range(n)]
    res = Parallel(n_jobs=args.jobs, verbose=5)(
        delayed(match_one)(s, 0, args.perms, fps, cms) for s in args.subjects)
    m = pd.DataFrame([r for rows in res for r in rows])
    m.to_csv(os.path.join(OUT, f'channel_order_match{args.suffix}.csv'), index=False, float_format='%.4f')
    g = m.groupby('method', sort=False)
    s = pd.DataFrame({'all_correct_pct': g.all_correct.mean() * 100, 'n_correct_mean': g.n_correct.mean(),
                      'subjects_all_perms_correct': g.apply(lambda d: int(d.groupby('subject').all_correct.all().sum())),
                      'acc_true_order': g.acc_true_order.mean() * 100, 'acc_recovered': g.acc_recovered.mean() * 100,
                      'acc_loss_max': g.apply(lambda d: ((d.acc_true_order - d.acc_recovered) * 100).max()),
                      'true_in_top50_pct': g.true_in_top.mean() * 100, 'n': g.size()})
    s.to_csv(os.path.join(OUT, f'channel_order_summary{args.suffix}.csv'), float_format='%.4g')
    pd.set_option('display.width', 200)
    print(s.round(2).to_string())
    print(f'took {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
