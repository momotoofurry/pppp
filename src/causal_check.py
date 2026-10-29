"""Two validity checks of the firmware v2 evaluation (advisor review, 2026-10-30), C code as in check_adapt_c.py.

1. Causal start-up alignment. check_adapt_c.py estimates the rotation from ALL of test block 0 and then classifies
   and scores the same 300 windows ('leak'). In the firmware the alignment windows (RT_ALIGN_START / END) are
   neither classified nor buffered, so here the first N windows of block 0 only go to ad_align_push, and block 0
   is scored from window N on ('c30', 'c60', 'c100'). 'g0' / 'g5': the alignment sees only the Power (0) / Rest (5)
   windows of block 0 (start-up with one gesture; those windows are not scored).
2. Coordinates of the buffer. The buffer keeps int16 rows normalised with the statistics of the block they came
   from (and the calibration rows with the one-shot statistics), while ad_end_block moves the statistics.
     off   no z-score update (one-shot statistics)
     base  firmware v2: sc_end_block, then ad_end_block
     R1    as base, then the buffer is mapped to the new statistics (sc_rescale)
     R2    ad_end_block first, buffer mapped, then sc_end_block (new trees are trained in the statistics
           they will be used with)
     R3    as R2, calibration rows mapped too
Per subject x seed x offset: the one-shot model is built once (as check_adapt_c.run_c), every variant restarts
from sc_init / ad_init. Accuracy: blocks 1-10 (same windows for every variant) and all scored windows.
Writes results/causal_check.csv and causal_check_summary.csv.
Usage (in the container): python src/causal_check.py [--jobs 19]
"""
import argparse
import copy
import ctypes
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.stats import wilcoxon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_adapt_c as CA  # noqa: E402
import check_selfcal_c as CS  # noqa: E402
import export_c  # noqa: E402
import pipeline as P  # noqa: E402
import rf_size  # noqa: E402
import selfcal_sweep as S  # noqa: E402
import shift_sweep as SH  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
ALIGN = ['leak', 'c30', 'c60', 'c100', 'g0', 'g5']
UPD = ['off', 'base', 'R1', 'R2', 'R3']
SHIFTS = [0, 0.5, 1]


def build():
    lib = CA.build()
    lib.sc_rescale.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
    lib.ad_mean.restype = ctypes.POINTER(ctypes.c_float)
    lib.ad_var.restype = ctypes.POINTER(ctypes.c_float)
    return lib


def stats(lib):
    mu = np.ctypeslib.as_array(lib.ad_mean(), (80,)).astype(np.float64)
    var = np.ctypeslib.as_array(lib.ad_var(), (80,)).astype(np.float64)
    return mu, np.where(var > 0, 1 / np.sqrt(np.where(var > 0, var, 1)), 0.0)


def rescale(lib, old, with_cal):
    (mu0, inv0), (mu1, inv1) = old, stats(lib)
    scale = np.where(inv0 > 0, inv1 / np.where(inv0 > 0, inv0, 1), 0.0)
    offset = (mu0 - mu1) * inv1 * 1024.0
    s32, o32 = np.ascontiguousarray(scale, np.float32), np.ascontiguousarray(offset, np.float32)
    lib.sc_rescale(s32.ctypes.data, o32.ctypes.data, int(with_cal))


def run(subject, seed, shift):
    lib = build()
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), SH.PREC), None)
    np.random.seed(seed * 1000 + subject)                            # as check_adapt_c.run_c
    z = np.load(SH.prepare(subject, shift))
    Xc_raw, yc = z['Xc'], z['yc']
    blocks = [(np.ascontiguousarray(z[f'X{b}'], dtype=np.float32), z[f'y{b}']) for b in range(P.N_BLOCKS)]
    mu, var = Xc_raw.mean(0), Xc_raw.var(0)
    Xc = (Xc_raw - mu) / np.sqrt(var)
    pre = P.load_pretrain(S.DATASETS['arm_position'][0])
    pruned = P.prune(rf_size.truncate_depth(copy.deepcopy(pre), SH.DEPTH), Xc, yc)
    app = P.train_rf(Xc, yc, 50, SH.DEPTH, None)
    mdl = rf_size.compact_forest(emg_functions.append(P.subset(pruned, range(50)), app))
    roots, feat, thr, left, right = export_c.table_arrays(mdl, 'int16')
    arrs = [np.ascontiguousarray(a, dtype=t) for a, t in
            [(roots, np.uint32), (feat, np.uint8), (thr, np.int16), (left, np.uint16), (right, np.uint16)]]
    m = CS.Model(*[a.ctypes.data for a in arrs])
    cal = np.ascontiguousarray(P.quantize(Xc))
    caly = np.ascontiguousarray(yc.astype(np.uint8))
    mu32 = np.ascontiguousarray(mu, dtype=np.float32)
    inv32 = np.ascontiguousarray(1.0 / np.sqrt(var), dtype=np.float32)
    calf = np.ascontiguousarray(Xc_raw, dtype=np.float32)
    X0, y0 = blocks[0]
    rows = []
    al = np.zeros(80, np.float32)
    q = np.zeros(80, np.int16)
    for align in ALIGN:
        if align == 'leak':
            a_idx, skip = np.arange(len(y0)), np.zeros(len(y0), bool)
        elif align.startswith('c'):
            a_idx = np.arange(int(align[1:]))
            skip = np.isin(np.arange(len(y0)), a_idx)
        else:
            a_idx = np.flatnonzero(y0 == int(align[1:]))
            skip = np.isin(np.arange(len(y0)), a_idx)
        for upd in UPD:
            sc_seed = seed * 1000 + subject + 1
            lib.sc_init(ctypes.byref(m), cal.ctypes.data, caly.ctypes.data, len(cal), sc_seed)
            lib.ad_init(mu32.ctypes.data, inv32.ctypes.data, calf.ctypes.data, len(calf))
            lib.ad_align_reset()
            for i in a_idx:
                lib.ad_align_push(X0[i].ctypes.data)
            k = lib.ad_align_finish()
            for b, (X, y) in enumerate(blocks):
                keep = ~skip if b == 0 else np.ones(len(y), bool)
                pred, pos = np.full(len(y), -1), np.full(len(y), -1)
                for i in np.flatnonzero(keep):
                    lib.ad_map(X[i].ctypes.data, al.ctypes.data)
                    lib.ad_normalize(al.ctypes.data, q.ctypes.data)
                    pos[i] = lib.sc_predict_oneshot(q.ctypes.data)
                    pred[i] = lib.sc_push(q.ctypes.data)
                    if upd != 'off':
                        lib.ad_observe(al.ctypes.data, int(pred[i]))
                st, ast = CS.Stats(), CA.AdStats()
                if upd in ('off', 'base', 'R1'):
                    lib.sc_end_block(ctypes.byref(st))
                    if upd != 'off':
                        old = stats(lib)
                        lib.ad_end_block(ctypes.byref(ast))
                        if upd == 'R1' and ast.updated:
                            rescale(lib, old, False)
                else:
                    old = stats(lib)
                    lib.ad_end_block(ctypes.byref(ast))
                    if ast.updated:
                        rescale(lib, old, upd == 'R3')
                    lib.sc_end_block(ctypes.byref(st))
                rows.append(dict(subject=subject, seed=seed, shift=shift, align=align, upd=upd, block=b, k_est=k,
                                 n=int(keep.sum()), n_fixed_ok=int((pos == y)[keep].sum()),
                                 n_adapt_ok=int((pred == y)[keep].sum()), clustered=st.clustered,
                                 ad_updated=ast.updated))
    return rows


def summarise(df):
    def acc(g, col, blocks):
        g = g[g.block.isin(blocks)]
        return g[col].sum() / g.n.sum() * 100
    later, every = range(1, P.N_BLOCKS), range(P.N_BLOCKS)
    per = []
    for key, g in df.groupby(['shift', 'align', 'upd', 'subject']):
        per.append(dict(zip(['shift', 'align', 'upd', 'subject'], key),
                        adapt_1_10=np.mean([acc(s, 'n_adapt_ok', later) for _, s in g.groupby('seed')]),
                        adapt_all=np.mean([acc(s, 'n_adapt_ok', every) for _, s in g.groupby('seed')]),
                        fixed_1_10=np.mean([acc(s, 'n_fixed_ok', later) for _, s in g.groupby('seed')]),
                        k_est=g.k_est.mode().iloc[0]))
    per = pd.DataFrame(per)
    wide = per.pivot_table(index=['shift', 'subject'], columns=['align', 'upd'],
                           values=['adapt_1_10', 'adapt_all', 'fixed_1_10', 'k_est'])
    out = []
    for sh in sorted(per['shift'].unique()):
        w = wide.loc[sh]
        for al in ALIGN:
            for up in UPD:
                a = w['adapt_1_10'][al][up]
                d_ref = a - w['adapt_1_10']['leak']['base']
                d_base = a - w['adapt_1_10'][al]['base']
                out.append(dict(shift=sh, align=al, upd=up, adapt_1_10=a.mean(), adapt_all=w['adapt_all'][al][up].mean(),
                        fixed_1_10=w['fixed_1_10'][al][up].mean(),
                        k_same_as_leak=int((w['k_est'][al][up] == w['k_est']['leak']['base']).sum()),
                        vs_leak_base=d_ref.mean(), vs_leak_base_better=int((d_ref > 0).sum()),
                        vs_leak_base_worse=int((d_ref < 0).sum()),
                        vs_leak_base_p=wilcoxon(d_ref).pvalue if np.any(d_ref != 0) else 1.0,
                        vs_same_align_base=d_base.mean(), vs_same_align_base_better=int((d_base > 0).sum()),
                        vs_same_align_base_worse=int((d_base < 0).sum()),
                        vs_same_align_base_p=wilcoxon(d_base).pvalue if np.any(d_base != 0) else 1.0))
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--subjects', type=int, default=20)
    args = ap.parse_args()
    build()
    for s in range(args.subjects):                                   # feature cache, sequential
        for sh in SHIFTS:
            SH.prepare(s, sh)
    jobs = [(s, seed, sh) for s in range(args.subjects) for seed in range(3) for sh in SHIFTS]
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(run)(*j) for j in jobs)
    df = pd.DataFrame([r for rs in res for r in rs])
    df.to_csv(os.path.join(OUT, 'causal_check.csv'), index=False)
    sm = summarise(df)
    sm.to_csv(os.path.join(OUT, 'causal_check_summary.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 250)
    print(sm.round(3).to_string(index=False))
    y0 = np.load(SH.prepare(0, 0))['y0']
    print('block 0 label order (subject 0, first 100 windows):', ''.join(str(int(v)) for v in y0[:100]))


if __name__ == '__main__':
    main()
