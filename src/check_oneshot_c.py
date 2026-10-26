"""On-device one-shot calibration (src/c/oneshot.c) vs the upstream Python, on the PC.

The firmware modules (oneshot.c, selfcal.c, tsne.c, kmeans.c, rf_train.c) are built with the MCU sizes into
build/c/libfirmware.so. The pre-trained table is what the MCU keeps in Flash: the 66-participant model
truncated to depth 10, first 50 trees, compacted, thresholds as Q5.10 (export_c.table_arrays).

Part 1, pruning decisions (all 20 subjects): both sides get the same Q5.10 calibration rows. Python runs the
upstream emg_functions.prune on the same trees with every threshold T (Q5.10) replaced by (T - 0.5) / 1024, so
its `x <= thr` on the Q5.10 grid is exactly the MCU's `x < T`; C runs os_prune(). The sets of pruned nodes
(reachable internal nodes that became leaves) and their labels must be identical.

Part 2, end to end (20 subjects x seeds): the raw calibration features go into os_feature_buffer(), and
os_calibrate() computes the z-score statistics, prunes, trains 50 trees and writes the one-shot image through a
simulated Flash writer (a RAM array that must be erased (0xFF) wherever it is written: every byte is written
once). The image is turned into the model with os_model(); the 11 test blocks (raw features, z-scored and
quantised on the "MCU" with os_normalize) are streamed through sc_push / sc_end_block as in check_selfcal_c.py.
Compared (paired over 20 subjects, seed-averaged, Wilcoxon) with the sklearn pipeline of the same setting
(selfcal_sweep_iter.csv, 500 iterations) and with the one-shot model built in Python + C self-calibration
(selfcal_c_check.csv).
Writes results/oneshot_prune_check.csv, results/oneshot_c_check.csv, results/oneshot_c_summary.csv.
Usage (in the container): PYTHONPATH=src python src/check_oneshot_c.py [--seeds 0 1 2] [--jobs 20]
"""
import argparse
import copy
import ctypes
import os
import subprocess
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.stats import wilcoxon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_c  # noqa: E402
import pipeline as P  # noqa: E402
import rf_size  # noqa: E402
from pipeline import emg_functions  # noqa: E402

CSRC = os.path.join(P.ROOT, 'src', 'c')
LIB = os.path.join(P.ROOT, 'build', 'c', 'libfirmware.so')
OUT = os.path.join(P.ROOT, 'results')
SRC = ['oneshot.c', 'selfcal.c', 'tsne.c', 'kmeans.c', 'rf_train.c', 'decision.c']
N_PRE, N_APP, CAP = 50, 50, 128 * 1024        # one 128 KB Flash sector for the image
WRITE_FN = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32)


class Table(ctypes.Structure):
    _fields_ = [('roots', ctypes.c_void_p), ('feat', ctypes.c_void_p), ('thr', ctypes.c_void_p),
                ('left', ctypes.c_void_p), ('right', ctypes.c_void_p), ('n_internal', ctypes.c_uint32)]


class Model(ctypes.Structure):
    _fields_ = [('roots', ctypes.c_void_p), ('feat', ctypes.c_void_p), ('thr', ctypes.c_void_p),
                ('left', ctypes.c_void_p), ('right', ctypes.c_void_p), ('prune_bits', ctypes.c_void_p),
                ('prune', ctypes.c_void_p), ('n_prune', ctypes.c_int), ('app_nodes', ctypes.c_void_p),
                ('app_roots', ctypes.c_void_p)]


class Writer(ctypes.Structure):
    _fields_ = [('write', WRITE_FN), ('ctx', ctypes.c_void_p), ('capacity', ctypes.c_uint32)]


class OsStats(ctypes.Structure):
    _fields_ = [('n_pruned_nodes', ctypes.c_int), ('app_nodes', ctypes.c_int), ('app_leaves_max', ctypes.c_int),
                ('image_bytes', ctypes.c_uint32), ('scratch_bytes', ctypes.c_uint32)]


class ScStats(ctypes.Structure):
    _fields_ = [(k, ctypes.c_int) for k in ['buffer_n', 'n_selected', 'clustered', 'tsne_cells_max', 'ram_trees',
                                            'new_nodes_max']]


class Prune(ctypes.Structure):
    _fields_ = [('idx', ctypes.c_uint16), ('label', ctypes.c_uint8), ('pad', ctypes.c_uint8)]


def build(cc='gcc'):
    src = [os.path.join(CSRC, f) for f in SRC]
    deps = src + [s[:-1] + 'h' for s in src]
    if not os.path.exists(LIB) or os.path.getmtime(LIB) < max(os.path.getmtime(s) for s in deps):
        os.makedirs(os.path.dirname(LIB), exist_ok=True)
        # the earlier firmware (t-SNE, no input adaptation): this check's results files were made with it
        subprocess.run([cc, '-O2', '-std=c99', '-Wall', '-fPIC', '-shared', '-DSC_EMBED=1', '-DRT_ADAPT=0', '-o', LIB] + src
                       + ['-lm'], check=True)
    lib = ctypes.CDLL(LIB)
    lib.os_feature_buffer.restype = ctypes.c_void_p
    lib.os_calibrate.argtypes = [ctypes.POINTER(Table), ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32,
                                 ctypes.POINTER(Writer), ctypes.c_void_p, ctypes.POINTER(OsStats)]
    lib.os_model.argtypes = [ctypes.c_void_p, ctypes.POINTER(Table), ctypes.POINTER(Model)]
    lib.os_normalize.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    lib.os_prune.argtypes = [ctypes.POINTER(Table), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                             ctypes.c_int]
    lib.sc_init.argtypes = [ctypes.POINTER(Model), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32]
    lib.sc_push.argtypes = [ctypes.c_void_p]
    lib.sc_predict_oneshot.argtypes = [ctypes.c_void_p]
    lib.sc_end_block.argtypes = [ctypes.POINTER(ScStats)]
    lib.sc_push_votes.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.sc_votes_oneshot.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.dc_replay.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint16,
                              ctypes.c_uint8, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    return lib


def pre_trees():
    """The 50 pre-trained trees as kept on the MCU: depth 10, compacted (pre-order), plus the Q5.10 table."""
    pre = P.load_pretrain()
    comp = rf_size.compact_forest(P.subset(rf_size.truncate_depth(copy.deepcopy(pre), 10), range(N_PRE)))
    arrs = export_c.table_arrays(comp, 'int16')
    arrs = [np.ascontiguousarray(a, dtype=t) for a, t in
            zip(arrs, [np.uint32, np.uint8, np.int16, np.uint16, np.uint16])]
    return comp, arrs


def table_struct(arrs):
    return Table(*[a.ctypes.data for a in arrs], len(arrs[1]))


def python_prune_set(comp, Xq, y):
    """Upstream prune with thresholds (T - 0.5) / 1024, i.e. `x < T` on Q5.10 rows. Returns {global idx: label}."""
    m = copy.deepcopy(comp)
    m['threshold'] = [np.where(l >= 0, (P.quantize(t).astype(np.float64) - 0.5) / 1024, t)
                      for l, t in zip(m['left'], m['threshold'])]
    before = [l.copy() for l in m['left']]
    pr = emg_functions.prune(m, Xq.astype(np.float64) / 1024, y)
    out, base = {}, 0
    for t in range(N_PRE):
        lb = before[t]
        internal = np.flatnonzero(lb >= 0)
        idx = -np.ones(len(lb), dtype=np.int64)
        idx[internal] = np.arange(len(internal))
        order, _ = rf_size.reachable(pr['left'][t], pr['right'][t])
        for node in order:
            if lb[node] >= 0 and pr['left'][t][node] < 0:          # was internal, is a leaf now
                out[base + int(idx[node])] = int(np.argmax(pr['value'][t][node, 0, :]))
        base += len(internal)
    return out


def check_prune(subjects):
    lib = build()
    comp, arrs = pre_trees()
    tab = table_struct(arrs)
    rows = []
    for s in subjects:
        Xc, yc, _ = P.load_subject(s)
        Xq = np.ascontiguousarray(P.quantize(Xc))
        y8 = np.ascontiguousarray(yc.astype(np.uint8))
        buf = (Prune * 20000)()
        n = lib.os_prune(ctypes.byref(tab), Xq.ctypes.data, y8.ctypes.data, len(Xq), buf, 20000)
        c = {buf[i].idx: buf[i].label for i in range(n)}
        py = python_prune_set(comp, Xq, yc)
        rows.append(dict(subject=s, n_internal=len(arrs[1]), pruned_python=len(py), pruned_c=len(c),
                         identical=(py == c), only_python=len(set(py) - set(c)), only_c=len(set(c) - set(py)),
                         label_diff=sum(py[k] != c[k] for k in set(py) & set(c))))
        print(rows[-1], flush=True)
    return pd.DataFrame(rows)


def calibrate(lib, subject, seed):
    """One-shot calibration on the "MCU" for one subject: returns (flash image, sc_model_t, cal_q, labels, stats,
    bytes written) after sc_init. The ctypes objects the model points into are returned too (keep them alive)."""
    _, arrs = pre_trees()
    tab = table_struct(arrs)
    raw_c, yc = P.load_folder('arm_position', subject, 'calibration')     # raw (not normalised) features
    fb = (ctypes.c_float * (60 * 80)).from_address(lib.os_feature_buffer())
    np.ctypeslib.as_array(fb)[:raw_c.size] = raw_c.astype(np.float32).ravel()
    flash = np.full(CAP, 0xFF, dtype=np.uint8)
    written = np.zeros(CAP, dtype=bool)
    errors = []

    def write(_ctx, off, src, n):
        if off + n > CAP or written[off:off + n].any():
            errors.append((off, n))
            return -1
        flash[off:off + n] = np.frombuffer(ctypes.string_at(src, n), dtype=np.uint8)
        written[off:off + n] = True
        return 0

    cb = WRITE_FN(write)
    w = Writer(cb, None, CAP)
    cal_q = np.zeros((60, 80), dtype=np.int16)
    y8 = np.ascontiguousarray(yc.astype(np.uint8))
    st = OsStats()
    r = lib.os_calibrate(ctypes.byref(tab), y8.ctypes.data, len(raw_c), seed * 1000 + subject + 7, ctypes.byref(w),
                         cal_q.ctypes.data, ctypes.byref(st))
    assert r == 0 and not errors, (r, errors)
    m = Model()
    assert lib.os_model(flash.ctypes.data, ctypes.byref(tab), ctypes.byref(m)) == 0
    lib.sc_init(ctypes.byref(m), cal_q.ctypes.data, y8.ctypes.data, len(raw_c), seed * 1000 + subject + 1)
    return flash, m, st, int(written.sum()), (arrs, tab, cb, w, cal_q, y8)


def run(subject, seed):
    lib = build()
    flash, m, st, n_written, _keep = calibrate(lib, subject, seed)
    rows = []
    for b in range(P.N_BLOCKS):
        X, y = P.load_folder('arm_position', subject, f'testing_block{b}')
        X = np.ascontiguousarray(X.astype(np.float32))
        Xq = np.zeros((len(X), 80), dtype=np.int16)
        for i in range(len(X)):
            lib.os_normalize(flash.ctypes.data, X[i].ctypes.data, Xq[i].ctypes.data)
        os_pred = np.array([lib.sc_predict_oneshot(Xq[i].ctypes.data) for i in range(len(Xq))])
        pred = np.array([lib.sc_push(Xq[i].ctypes.data) for i in range(len(Xq))])
        sst = ScStats()
        lib.sc_end_block(ctypes.byref(sst))
        rows.append(dict(subject=subject, seed=seed, block=b, acc_oneshot=np.mean(os_pred == y),
                         acc_selfcal=np.mean(pred == y), n_pruned_nodes=st.n_pruned_nodes, app_nodes=st.app_nodes,
                         app_leaves_max=st.app_leaves_max, image_bytes=st.image_bytes,
                         scratch_bytes=st.scratch_bytes, flash_bytes_written=n_written,
                         clustered=sst.clustered))
    return rows


def paired(a, b):
    x = a - b
    return dict(diff=x.mean(), better=int((x > 0).sum()), worse=int((x < 0).sum()),
                p=wilcoxon(a, b).pvalue if np.any(x != 0) else 1.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--subjects', type=int, nargs='+', default=list(range(20)))
    ap.add_argument('--jobs', type=int, default=20)
    args = ap.parse_args()
    build()
    pr = check_prune(args.subjects)
    pr.to_csv(os.path.join(OUT, 'oneshot_prune_check.csv'), index=False)
    print('pruning identical for', int(pr.identical.sum()), 'of', len(pr), 'subjects')
    import check_oneshot_c as M
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(M.run)(s, sd) for sd in args.seeds for s in args.subjects)
    df = pd.DataFrame([r for rr in res for r in rr])
    df.to_csv(os.path.join(OUT, 'oneshot_c_check.csv'), index=False, float_format='%.4f')
    ref = pd.read_csv(os.path.join(OUT, 'selfcal_sweep_iter.csv'))
    ref = ref[ref.tsne_iter == 500]
    fw = pd.read_csv(os.path.join(OUT, 'selfcal_c_check.csv'))
    rows = []
    for col in ['acc_oneshot', 'acc_selfcal']:
        c = df.groupby('subject')[col].mean() * 100
        for name, d in [('sklearn pipeline (selfcal_sweep_iter, 500 it)', ref),
                        ('Python one-shot + C self-calibration (selfcal_c_check)', fw)]:
            r_ = d.groupby('subject')[col].mean() * 100
            rows.append(dict(metric=col, reference=name, c_oneshot=c.mean(), reference_value=r_.mean(), **paired(c, r_)))
    per_seed = df.groupby('seed')[['acc_oneshot', 'acc_selfcal']].mean() * 100
    summ = pd.DataFrame(rows)
    summ.to_csv(os.path.join(OUT, 'oneshot_c_summary.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 250)
    print(per_seed.round(2).to_string())
    print(summ.round(3).to_string(index=False))
    print(df[['n_pruned_nodes', 'app_nodes', 'app_leaves_max', 'image_bytes', 'scratch_bytes', 'flash_bytes_written']]
          .agg(['mean', 'max']).round(1).to_string())


if __name__ == '__main__':
    main()
