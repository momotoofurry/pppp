"""PC check of the new firmware chain against Python: start-up alignment + class-balanced z-score update
(src/c/adapt.c) + self-calibration without t-SNE (src/c/selfcal.c, SC_EMBED = 0: K-Means on the 80 int16 features).

Per subject x seed x electrode offset (arm_position, C features with the raw-EMG rotation of shift_sweep.py --raw):
  C:      ad_init(one-shot mean / 1/std, calibration features) -> the raw features of test block 0 go through
          ad_align_push / ad_align_finish (rotation k) -> every block row by row: ad_map -> ad_normalize (Q5.10) ->
          sc_push (prediction, buffered) -> ad_observe(prediction); end of block: sc_end_block, ad_end_block.
          The one-shot model is built in Python exactly as zscore_sweep.run (same numpy seed) and exported to the
          Flash table format (as check_selfcal_c.py); the C code uses its own RNG for the new trees.
  Python: zscore_sweep.run(zs = 'bal0.3' or 'none', embed = 'none'): the same steps with sklearn trees.
Variants: update = 1 (z-score update on) and 0 (one-shot statistics, alignment only).
Compared: the estimated rotation (C vs Python, must be identical) and the accuracies (paired Wilcoxon over
subjects; trees are random, so rows are not expected to be identical). CPU time of sc_end_block is PC time.
Writes results/adapt_c_check.csv and adapt_c_check_summary.csv.
Usage (in the container): python src/check_adapt_c.py [--jobs 19]
"""
import argparse
import copy
import ctypes
import os
import subprocess
import sys
import time

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.stats import wilcoxon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_selfcal_c as CS  # noqa: E402
import export_c  # noqa: E402
import pipeline as P  # noqa: E402
import rf_size  # noqa: E402
import selfcal_sweep as S  # noqa: E402
import shift_sweep as SH  # noqa: E402
import zscore_sweep as Z  # noqa: E402
from pipeline import emg_functions  # noqa: E402

CSRC = os.path.join(P.ROOT, 'src', 'c')
LIB = os.path.join(P.ROOT, 'build', 'c', 'libadapt.so')
OUT = os.path.join(P.ROOT, 'results')
SRC = ['selfcal.c', 'kmeans.c', 'rf_train.c', 'adapt.c']                # SC_EMBED = 0: no tsne.c


class AdStats(ctypes.Structure):
    _fields_ = [('classes_used', ctypes.c_int), ('updated', ctypes.c_int)]


def build(cc='gcc'):
    src = [os.path.join(CSRC, f) for f in SRC]
    deps = src + [s[:-1] + 'h' for s in src]
    if not os.path.exists(LIB) or os.path.getmtime(LIB) < max(os.path.getmtime(s) for s in deps):
        os.makedirs(os.path.dirname(LIB), exist_ok=True)
        subprocess.run([cc, '-O2', '-std=c99', '-Wall', '-fPIC', '-shared', '-DSC_EMBED=0', '-o', LIB] + src + ['-lm'],
                       check=True)
    lib = ctypes.CDLL(LIB)
    lib.sc_init.argtypes = [ctypes.POINTER(CS.Model), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32]
    lib.sc_push.argtypes = [ctypes.c_void_p]
    lib.sc_end_block.argtypes = [ctypes.POINTER(CS.Stats)]
    lib.sc_predict_oneshot.argtypes = [ctypes.c_void_p]
    lib.ad_init.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
    lib.ad_align_push.argtypes = [ctypes.c_void_p]
    lib.ad_map.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.ad_normalize.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.ad_observe.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.ad_end_block.argtypes = [ctypes.POINTER(AdStats)]
    lib.sc_static_bytes.restype = ctypes.c_uint
    lib.ad_static_bytes.restype = ctypes.c_uint
    return lib


def run_c(subject, seed, shift, update):
    lib = build()
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), SH.PREC), None)
    np.random.seed(seed * 1000 + subject)                            # as zscore_sweep.run
    z = np.load(SH.prepare(subject, shift))
    Xc_raw, yc = z['Xc'], z['yc']
    blocks = [(z[f'X{b}'], z[f'y{b}']) for b in range(P.N_BLOCKS)]
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
    lib.sc_init(ctypes.byref(m), cal.ctypes.data, caly.ctypes.data, len(cal), seed * 1000 + subject + 1)
    mu32 = np.ascontiguousarray(mu, dtype=np.float32)
    inv32 = np.ascontiguousarray(1.0 / np.sqrt(var), dtype=np.float32)
    calf = np.ascontiguousarray(Xc_raw, dtype=np.float32)
    lib.ad_init(mu32.ctypes.data, inv32.ctypes.data, calf.ctypes.data, len(calf))
    lib.ad_align_reset()
    for r in np.ascontiguousarray(blocks[0][0], dtype=np.float32):
        lib.ad_align_push(r.ctypes.data)
    k = lib.ad_align_finish()
    rows = []
    al = np.zeros(80, np.float32)
    q = np.zeros(80, np.int16)
    for b, (X_raw, y) in enumerate(blocks):
        X32 = np.ascontiguousarray(X_raw, dtype=np.float32)
        pred, pos = np.zeros(len(y), int), np.zeros(len(y), int)
        for i in range(len(y)):
            lib.ad_map(X32[i].ctypes.data, al.ctypes.data)
            lib.ad_normalize(al.ctypes.data, q.ctypes.data)
            pos[i] = lib.sc_predict_oneshot(q.ctypes.data)
            pred[i] = lib.sc_push(q.ctypes.data)
            if update:
                lib.ad_observe(al.ctypes.data, int(pred[i]))
        st = CS.Stats()
        t0 = time.process_time()
        lib.sc_end_block(ctypes.byref(st))
        cpu = time.process_time() - t0
        ast = AdStats()
        if update:
            lib.ad_end_block(ctypes.byref(ast))
        rows.append(dict(impl='c', subject=subject, seed=seed, shift=shift, update=update, block=b, k_est=k,
                         acc_fixed=np.mean(pos == y), acc_adapt=np.mean(pred == y), clustered=st.clustered,
                         n_selected=st.n_selected, new_nodes_max=st.new_nodes_max, update_cpu_s=cpu,
                         ad_updated=ast.updated, ad_classes=ast.classes_used))
    return rows


def run_py(subject, seed, shift, update):
    rows = Z.run('arm_position', subject, seed, shift, 'bal0.3' if update else 'none', embed='none')
    for r in rows:
        r.update(impl='python', update=update)
        del r['zs'], r['dataset']
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--shifts', type=float, nargs='+', default=[0, 0.5, 1])
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--subjects', type=int, nargs='+', default=list(range(20)))
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--suffix', default='')
    args = ap.parse_args()
    t0 = time.time()
    lib = build()
    import check_features_c as FC
    FC.lib()
    Parallel(n_jobs=args.jobs)(delayed(SH.prepare)(s, sh) for sh in args.shifts for s in args.subjects)
    import check_adapt_c as M                                        # pickle by reference
    tasks = [(f, s, sd, sh, u) for f in (M.run_c, M.run_py) for sh in args.shifts for u in (1, 0)
             for sd in args.seeds for s in args.subjects]
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(f)(s, sd, sh, u) for f, s, sd, sh, u in tasks)
    df = pd.DataFrame([r for rows in res for r in rows])
    df.to_csv(os.path.join(OUT, f'adapt_c_check{args.suffix}.csv'), index=False, float_format='%.4f')
    ps = df.groupby(['impl', 'shift', 'update', 'subject'])[['acc_fixed', 'acc_adapt']].mean() * 100
    kk = df[df.block == 0].groupby(['impl', 'shift', 'update', 'subject', 'seed']).k_est.first()
    out = []
    for sh in args.shifts:
        for u in (1, 0):
            c, p = ps.loc[('c', sh, u)], ps.loc[('python', sh, u)]
            d = c.acc_adapt - p.acc_adapt
            kc, kp = kk.loc[('c', sh, u)], kk.loc[('python', sh, u)]
            out.append(dict(shift=sh, update=u, c_fixed=c.acc_fixed.mean(), py_fixed=p.acc_fixed.mean(),
                            c_adapt=c.acc_adapt.mean(), py_adapt=p.acc_adapt.mean(), c_minus_py=d.mean(),
                            c_better=int((d > 0).sum()), p=wilcoxon(c.acc_adapt, p.acc_adapt).pvalue if np.any(d != 0) else 1.0,
                            k_same=int((kc.values == kp.values).sum()), k_runs=len(kc)))
    s = pd.DataFrame(out)
    s.to_csv(os.path.join(OUT, f'adapt_c_check_summary{args.suffix}.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 220)
    print(s.round(3).to_string(index=False))
    cdf = df[df.impl == 'c']
    print(f"C: clustered {cdf.clustered.mean() * 100:.1f}% of updates, z-score updated {cdf[cdf['update'] == 1].ad_updated.mean() * 100:.1f}% "
          f"of blocks, max new-tree internal nodes {cdf.new_nodes_max.max()}, PC sc_end_block CPU mean {cdf.update_cpu_s.mean():.4f} s")
    print('static bytes: selfcal.c', lib.sc_static_bytes(), ' adapt.c', lib.ad_static_bytes())
    print(f'took {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
