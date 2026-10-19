"""End-to-end check of the on-device self-calibration firmware logic (src/c/selfcal.c) on the PC.

The C module is built with the MCU sizes (buffer 375, t-SNE / K-Means 375 points, training 440 rows, 32-leaf
trees, 500 t-SNE iterations) into build/c/libselfcal.so. For every subject x seed the one-shot model is built
exactly as in selfcal_sweep.py (same numpy seed: truncate to depth 10, prune, keep 50 pre-trained trees,
append 50 calibration trees), compacted and exported to the Flash table format (export_c.table_arrays, int16).
Then the 11 test blocks are streamed in order, row by row as int16 Q5.10 (sc_push: the C code predicts with its
self-calibrated model and buffers the row), and sc_end_block() pseudo-labels, trains and replaces trees, all
with its own RNG. Recorded per block: one-shot and self-calibrated accuracy (C predictions), and the C one-shot predictions
are checked against pipeline.predict(int16) of the same model. CPU time of sc_end_block is PC time, not MCU time.
--dataset demo: the two-day demo recording (1 subject, 10 blocks); use --subjects 0 and more seeds.
Writes results/selfcal_c_check<suffix>.csv and prints the comparison with the Python-driven runs.
Usage (in the container): PYTHONPATH=src python src/check_selfcal_c.py [--seeds 0 1 2] [--jobs 20]
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_c  # noqa: E402
import pipeline as P  # noqa: E402
import rf_size  # noqa: E402
from pipeline import emg_functions  # noqa: E402

CSRC = os.path.join(P.ROOT, 'src', 'c')
LIB = os.path.join(P.ROOT, 'build', 'c', 'libselfcal.so')
OUT = os.path.join(P.ROOT, 'results')
SRC = ['selfcal.c', 'tsne.c', 'kmeans.c', 'rf_train.c']


class Model(ctypes.Structure):
    _fields_ = [('roots', ctypes.c_void_p), ('feat', ctypes.c_void_p), ('thr', ctypes.c_void_p),
                ('left', ctypes.c_void_p), ('right', ctypes.c_void_p)]


class Stats(ctypes.Structure):
    _fields_ = [(k, ctypes.c_int) for k in ['buffer_n', 'n_selected', 'clustered', 'tsne_cells_max', 'ram_trees',
                                            'new_nodes_max']]


def build(cc='gcc'):
    src = [os.path.join(CSRC, f) for f in SRC]
    deps = src + [s[:-1] + 'h' for s in src]
    if not os.path.exists(LIB) or os.path.getmtime(LIB) < max(os.path.getmtime(s) for s in deps):
        os.makedirs(os.path.dirname(LIB), exist_ok=True)
        subprocess.run([cc, '-O2', '-std=c99', '-Wall', '-fPIC', '-shared', '-o', LIB] + src + ['-lm'], check=True)
    lib = ctypes.CDLL(LIB)
    lib.sc_init.argtypes = [ctypes.POINTER(Model), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32]
    lib.sc_push.argtypes = [ctypes.c_void_p]
    lib.sc_end_block.argtypes = [ctypes.POINTER(Stats)]
    lib.sc_predict_oneshot.argtypes = [ctypes.c_void_p]
    lib.sc_static_bytes.restype = ctypes.c_uint
    return lib


def run(subject, seed, dataset='arm_position'):
    import selfcal_sweep as S
    lib = build()
    np.random.seed(seed * 1000 + subject)                  # as selfcal_sweep.run_subject
    Xc, yc, blocks = P.load_subject(subject, dataset, S.DATASETS[dataset][1])
    pre = P.load_pretrain(S.DATASETS[dataset][0])
    pruned = P.prune(rf_size.truncate_depth(copy.deepcopy(pre), 10), Xc, yc)
    app = P.train_rf(Xc, yc, 50, 10, None)
    mdl = rf_size.compact_forest(emg_functions.append(P.subset(pruned, range(50)), app))
    roots, feat, thr, left, right = export_c.table_arrays(mdl, 'int16')
    arrs = [np.ascontiguousarray(a, dtype=t) for a, t in
            [(roots, np.uint32), (feat, np.uint8), (thr, np.int16), (left, np.uint16), (right, np.uint16)]]
    m = Model(*[a.ctypes.data for a in arrs])
    cal = np.ascontiguousarray(P.quantize(Xc))
    caly = np.ascontiguousarray(yc.astype(np.uint8))
    lib.sc_init(ctypes.byref(m), cal.ctypes.data, caly.ctypes.data, len(cal), seed * 1000 + subject + 1)
    rows = []
    for b, (X, y) in enumerate(blocks):
        Xq = np.ascontiguousarray(P.quantize(X))
        os_c = np.array([lib.sc_predict_oneshot(Xq[i].ctypes.data) for i in range(len(Xq))])
        os_py = P.predict(mdl, X, 'int16')
        pred = np.array([lib.sc_push(Xq[i].ctypes.data) for i in range(len(Xq))])
        st = Stats()
        t0 = time.process_time()
        lib.sc_end_block(ctypes.byref(st))
        rows.append(dict(subject=subject, seed=seed, block=b, acc_oneshot=np.mean(os_c == y),
                         acc_selfcal=np.mean(pred == y), oneshot_c_equals_python=bool(np.array_equal(os_c, os_py)),
                         update_cpu_s=time.process_time() - t0, **{k: getattr(st, k) for k, _ in Stats._fields_}))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--subjects', type=int, nargs='+', default=list(range(20)))
    ap.add_argument('--jobs', type=int, default=20)
    ap.add_argument('--dataset', default='arm_position', choices=['arm_position', 'demo'])
    ap.add_argument('--suffix', default='')
    args = ap.parse_args()
    lib = build()
    import check_selfcal_c as M             # pickle the task by reference (ctypes classes are not picklable)
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(M.run)(s, sd, args.dataset) for sd in args.seeds
                                                for s in args.subjects)
    df = pd.DataFrame([r for rr in res for r in rr])
    df.to_csv(os.path.join(OUT, f'selfcal_c_check{args.suffix}.csv'), index=False, float_format='%.4f')
    per_seed = df.groupby('seed')[['acc_oneshot', 'acc_selfcal']].mean() * 100
    print(per_seed.round(2).to_string())
    print(f"one-shot {per_seed.acc_oneshot.mean():.2f}%  self-cal {per_seed.acc_selfcal.mean():.2f}%  "
          f"gain {(per_seed.acc_selfcal - per_seed.acc_oneshot).mean():+.2f}  "
          f"C one-shot == Python int16: {df.oneshot_c_equals_python.all()}")
    print(f"clustered {df.clustered.mean() * 100:.1f}% of updates, max RAM trees {df.ram_trees.max()}, "
          f"max new-tree internal nodes {df.new_nodes_max.max()}, max t-SNE cells {df.tsne_cells_max.max()}, "
          f"max selected {df.n_selected.max()}, PC sc_end_block CPU mean {df.update_cpu_s.mean():.3f} s")
    print('static bytes of selfcal.c state + work:', lib.sc_static_bytes())


if __name__ == '__main__':
    main()
