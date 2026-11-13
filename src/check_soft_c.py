"""Soft task labels in the C LDA module (ld_soft_q, ld_decay, ld_add_soft in src/c/ldacal.c) against the float64
reference of task_sim2.py (learn_soft on lda_anchor.OasLDA). Exploratory (report 35.22).

Per subject (shift 0 and 0.5): day-1 calibration on both sides; then per block 1-10 one cued pass (forgetting 0.97,
hard labels, as lda_context2.learn) and 30 commands. A command = 10 windows of a gesture trial; the system's
expected gesture is the true one with probability 0.8, otherwise a random other one (to exercise the prior); the
valid set is the expected one plus two random others. Each side computes its own q with its own model (C:
ld_soft_q; Python: task_sim2's formula), then forgets (0.97) and learns the windows with q, then refits. Compared:
q of every command (max abs difference, same argmax), predictions on the held-out trials 3-4 of each block (share
of equal predictions) and the accuracy of both.
Writes results/soft_c_check.csv and prints the Cortex-M7 object size of ldacal.c (text, bss).
Usage (in the container): python src/check_soft_c.py [--jobs 19]
"""
import argparse
import ctypes
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_ldacal_c as CL  # noqa: E402
import lda_anchor as LA  # noqa: E402
import lda_context2 as C2  # noqa: E402
import leaf_guard as LG  # noqa: E402
import leaf_sweep as LS  # noqa: E402
import pipeline as P  # noqa: E402
import task_sim2 as T2  # noqa: E402
import zscore_sweep as ZW  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
FP = ctypes.POINTER(ctypes.c_float)


def lib():
    L = CL.build()
    L.ld_add_soft.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    L.ld_decay.argtypes = [ctypes.c_float]
    L.ld_soft_q.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_float, ctypes.c_void_p]
    return L


def prior_of(exp, valid):
    pr = np.full(LS.K, T2.P_INVALID)
    others = [c for c in valid if c != exp]
    pr[exp] = 1 - T2.EPS if others else 1 - T2.P0
    for c in others:
        pr[c] = T2.EPS / len(others)
    pr[T2.REST] = T2.P0
    return pr


def job(subject, shift):
    L = lib()
    Xc_raw, yc, blocks, _ = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    mu, sd = Xc_raw.mean(0), Xc_raw.std(0)
    Zc = (Xc_raw - mu) / sd
    ref = LA.OasLDA()
    ref.add(Zc, yc)
    ref.fit()
    L.ld_reset()
    for row, c in zip(CL.q(Zc), yc):
        L.ld_add(row.ctypes.data, int(c))
    assert L.ld_fit() == 0
    rng = np.random.default_rng(subject)
    dq, same_arg, ncmd, n, agree, ok_py, ok_c = 0.0, 0, 0, 0, 0, 0, 0
    for b, (X, y) in enumerate(blocks):
        if b == 0:
            continue
        y = np.asarray(y).astype(np.int64)
        Z = (np.asarray(X, dtype=np.float64) - mu) / sd
        tr = [LG.trials(y, c) for c in range(LS.K)]
        for c in range(LS.K):                                 # one cued pass
            Zt = Z[tr[c][0]]
            C2.learn(ref, Zt, c)
            L.ld_decay(C2.DECAY)
            for row in CL.q(Zt):
                L.ld_add(row.ctypes.data, c)
            assert L.ld_fit() == 0
        for _ in range(30):
            g = int(rng.integers(5))
            Zt = Z[tr[g][int(rng.integers(3))]]
            exp = g if rng.random() < 0.8 else int(rng.choice([c for c in range(5) if c != g]))
            valid = [exp] + list(rng.choice([c for c in range(5) if c != exp], 2, replace=False))
            pr = prior_of(exp, valid)
            s = ref.scores(Zt).mean(0)
            qp = pr * np.exp(T2.BETA * (s - s.max()))
            qp /= qp.sum()
            rows = np.ascontiguousarray(CL.q(Zt))
            prc = np.ascontiguousarray(pr.astype(np.float32))
            qc = np.zeros(LS.K, np.float32)
            L.ld_soft_q(rows.ctypes.data, len(rows), prc.ctypes.data, T2.BETA, qc.ctypes.data)
            dq = max(dq, float(np.max(np.abs(qc - qp))))
            same_arg += int(np.argmax(qc) == np.argmax(qp))
            ncmd += 1
            ref.G = C2.DECAY * ref.G
            ref.s = C2.DECAY * ref.s
            ref.n = C2.DECAY * ref.n
            Zq = LA.OasLDA.q(Zt)
            ref.G += Zq.T @ Zq
            ref.s += np.outer(qp, Zq.sum(0))
            ref.n += qp * len(Zq)
            ref.fit()
            L.ld_decay(C2.DECAY)
            for row in rows:
                L.ld_add_soft(row.ctypes.data, qc.ctypes.data)
            assert L.ld_fit() == 0
        pi = np.concatenate([i for c in range(LS.K) for i in tr[c][3:5]])
        pp = ref.predict(Z[pi])
        pc = np.array([L.ld_predict(r.ctypes.data) for r in CL.q(Z[pi])])
        n += len(pi)
        agree += int(np.sum(pp == pc))
        ok_py += int(np.sum(pp == y[pi]))
        ok_c += int(np.sum(pc == y[pi]))
    return dict(subject=subject, shift=shift, commands=ncmd, max_q_diff=dq, q_argmax_same=same_arg / ncmd * 100,
                windows=n, agree_pct=agree / n * 100, acc_py=ok_py / n * 100, acc_c=ok_c / n * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    args = ap.parse_args()
    import check_features_c as FC
    import check_soft_c as M
    FC.lib()
    lib()
    df = pd.DataFrame(Parallel(n_jobs=args.jobs)(delayed(M.job)(s, sh) for sh in (0.0, 0.5) for s in range(20)))
    df.to_csv(os.path.join(OUT, 'soft_c_check.csv'), index=False, float_format='%.6g')
    pd.set_option('display.width', 200)
    print(df.groupby('shift').agg(subjects=('subject', 'size'), commands=('commands', 'sum'), max_q_diff=('max_q_diff', 'max'),
                                  q_argmax_same=('q_argmax_same', 'min'), agree_min=('agree_pct', 'min'),
                                  agree_mean=('agree_pct', 'mean'), acc_py=('acc_py', 'mean'), acc_c=('acc_c', 'mean')).to_string())
    a = CL.arm_size()
    a.to_csv(os.path.join(OUT, 'arm_ldacal_soft_size.csv'), index=False)
    print('Cortex-M7 ldacal.o with the soft-label functions:')
    print(a.to_string(index=False))


if __name__ == '__main__':
    main()
