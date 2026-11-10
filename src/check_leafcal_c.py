"""C leaf counters (src/c/leafcal.c) against the Python prototype (leaf_sweep.py, LAonly_a8_za and its _k variants):
window-by-window predictions on the development data, the 255 saturation, the capacity check, and the Cortex-M7
object size. Exploratory (report 35); the frozen firmware does not contain leafcal.c.

Per subject / seed / shift, base stream, anchors as leaf_sweep.py. Both sides get the same Q5.10 rows: the z-score
(day-1 statistics, moved towards the anchor's statistics before each block and towards the block's class-balanced
statistics after it) is computed in Python in float64 for both; the C side uses the C predictions for that update,
so any difference would show up as a disagreement.
  --k 50 25 10 0   counters on the 50 appended trees + the first k pre-trained trees (50 = all trees)
Writes results/leafcal_c_check.csv (per run) and leafcal_c_summary.csv; with --arm also arm_leafcal_size.csv
(arm-none-eabi-gcc -Os, object file of leafcal.c with LC_MAX_LEAVES = the largest need of that k, rounded up to
a multiple of 256: text / data / bss and the largest stack frame from -fstack-usage).
Usage (in the container): python src/check_leafcal_c.py [--arm] [--jobs 19]
"""
import argparse
import ctypes
import os
import subprocess
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_c  # noqa: E402
import leaf_sweep as LS  # noqa: E402
import pipeline as P  # noqa: E402
import rf_size  # noqa: E402
import selfcal_sweep as S  # noqa: E402
import zscore_sweep as ZW  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
CSRC = os.path.join(P.ROOT, 'src', 'c')
LIB = os.path.join(P.ROOT, 'build', 'c', 'libleafcal.so')
ARM_FLAGS = ['-mcpu=cortex-m7', '-mthumb', '-mfpu=fpv5-d16', '-mfloat-abi=hard', '-Os', '-ffunction-sections',
             '-fdata-sections', '-std=c99', '-Wall', '-fstack-usage']


class Model(ctypes.Structure):
    _fields_ = [(n, ctypes.c_void_p) for n in ('roots', 'feat', 'thr', 'left', 'right', 'leaf_base')]


def build():
    src = os.path.join(CSRC, 'leafcal.c')
    dep = [src, src[:-1] + 'h']
    if not os.path.exists(LIB) or os.path.getmtime(LIB) < max(os.path.getmtime(d) for d in dep):
        os.makedirs(os.path.dirname(LIB), exist_ok=True)
        subprocess.run(['gcc', '-O2', '-std=c99', '-Wall', '-Wextra', '-Werror', '-fPIC', '-shared', '-o', LIB, src],
                       check=True)
    lib = ctypes.CDLL(LIB)
    lib.lc_init.argtypes = [ctypes.POINTER(Model)]
    lib.lc_learn.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.lc_predict.argtypes = [ctypes.c_void_p]
    lib.lc_static_bytes.restype = ctypes.c_uint
    return lib


def tables(mdl, k):
    """leafcal.h tables of the one-shot model; counters on trees 0..k-1 and on the appended trees"""
    mdl = rf_size.compact_forest(mdl)
    thr_all = export_c.stored_thresholds(mdl, 'int16')
    cls_all = P.leaf_labels(mdl)
    feat, thr, left, right, roots, base = [], [], [], [], [], [0]
    for t, (l, r, f, th, cls) in enumerate(zip(mdl['left'], mdl['right'], mdl['feature'], thr_all, cls_all)):
        internal = np.flatnonzero(l >= 0)
        leaf = np.flatnonzero(l < 0)
        base.append(base[-1] + (len(leaf) if (t < k or t >= LS.N_PRE) else 0))
        if len(internal) == 0:
            roots.append(0x80000000 | int(cls[0]))
            continue
        assert internal[0] == 0 and len(internal) < 0x8000 and len(leaf) < 4096
        idx = -np.ones(len(l), dtype=np.int64)
        idx[internal] = np.arange(len(internal))
        lidx = -np.ones(len(l), dtype=np.int64)
        lidx[leaf] = np.arange(len(leaf))

        def enc(c):
            return 0x8000 | (int(lidx[c]) << 3) | int(cls[c]) if l[c] < 0 else int(idx[c])

        roots.append(len(feat))
        for n in internal:
            feat.append(int(f[n]))
            thr.append(th[n])
            left.append(enc(l[n]))
            right.append(enc(r[n]))
    assert base[-1] < 65536
    arrs = [np.ascontiguousarray(a, dtype=d) for a, d in
            [(roots, np.uint32), (feat, np.uint8), (thr, np.int16), (left, np.uint16), (right, np.uint16),
             (base, np.uint16)]]
    return arrs, Model(*[a.ctypes.data for a in arrs])


def q(X):
    return np.ascontiguousarray(P.quantize(X))


def run_c(lib, mdl, k, Xc_raw, blocks):
    arrs, m = tables(mdl, k)
    assert lib.lc_init(ctypes.byref(m)) == 0
    mu, var = Xc_raw.mean(0), Xc_raw.var(0)
    preds = []
    for Xa, ya, Xu, yu in blocks:
        if len(ya):
            st = ZW.balanced_stats(Xa, ya)
            mu = (1 - LS.A_Z) * mu + LS.A_Z * st[0]
            var = (1 - LS.A_Z) * var + LS.A_Z * st[1]
            qa = q((Xa - mu) / np.sqrt(var))
            for row, c in zip(qa, ya):
                lib.lc_learn(row.ctypes.data, int(c))
        qu = q((Xu - mu) / np.sqrt(var))
        pred = np.array([lib.lc_predict(row.ctypes.data) for row in qu], dtype=np.int64)
        preds.append(pred)
        if LS.guard_ok(pred):
            st = ZW.balanced_stats(Xu, pred)
            if st is not None:
                mu = (1 - LS.A_Z) * mu + LS.A_Z * st[0]
                var = (1 - LS.A_Z) * var + LS.A_Z * st[1]
    return preds, int(arrs[-1][-1])


def cond_name(k):
    return 'LAonly_a8_za' if k == LS.N_PRE else f'LAonly_a8_za_k{k}'


def job(subject, seed, shift, ks):
    lib = build()
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), LS.PREC), None)
    np.random.seed(seed * 1000 + subject)
    Xc_raw, yc, blocks, _ = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    mu, sd = Xc_raw.mean(0), Xc_raw.std(0)
    mdl = LS.one_shot((Xc_raw - mu) / sd, yc, P.load_pretrain(S.DATASETS['arm_position'][0]))
    blk = []
    for X, y in blocks:
        y = y.astype(np.int64)
        a, u = LS.anchor_split(y)
        blk.append((X[a], y[a], X[u], y[u]))
    rows = []
    for k in ks:
        LS.NEW.setdefault(cond_name(k), dict(kind='cnt', anc=8, pseudo=False, za=True, k=k))
        ref = []
        LS.run_anchor(cond_name(k), mdl, Xc_raw, blk, ref)
        got, leaves = run_c(lib, mdl, k, Xc_raw, blk)
        y = np.concatenate([b[3] for b in blk[1:]])
        r, g = np.concatenate(ref[1:]), np.concatenate(got[1:])
        rows.append(dict(subject=subject, seed=seed, shift=shift, k=k, windows=int(sum(len(x) for x in ref)),
                         agree=int(sum(int(np.sum(a == b)) for a, b in zip(ref, got))), leaves=leaves,
                         acc_py=np.mean(r == y) * 100, acc_c=np.mean(g == y) * 100))
    return rows


def extra_checks(lib):
    """255 saturation and capacity, on a tiny hand-made forest: tree 0 = one split on feature 0 (left leaf class 0,
    right leaf class 1), the other 99 trees single leaves of class 0 without counters"""
    roots = np.array([0] + [0x80000000] * 99, dtype=np.uint32)
    feat, thr = np.array([0], dtype=np.uint8), np.array([0], dtype=np.int16)
    left, right = np.array([0x8000 | (0 << 3) | 0], dtype=np.uint16), np.array([0x8000 | (1 << 3) | 1], dtype=np.uint16)
    base = np.array([0] + [2] * 100, dtype=np.uint16)
    m = Model(*[a.ctypes.data for a in (roots, feat, thr, left, right, base)])
    assert lib.lc_init(ctypes.byref(m)) == 0
    x = np.zeros(80, dtype=np.int16)
    x[0] = 5                                                 # right leaf, one-shot class 1
    v = (ctypes.c_uint16 * 6)()
    out = []
    lib.lc_votes.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.lc_votes(x.ctypes.data, v)
    out.append(('one-shot class before learning', v[1] == 1 and v[0] == 99))
    lib.lc_learn(x.ctypes.data, 3)
    lib.lc_votes(x.ctypes.data, v)
    out.append(('one window of another class takes the leaf (2*1 > 1)', v[3] == 1 and v[1] == 0))
    lib.lc_learn(x.ctypes.data, 1)
    lib.lc_votes(x.ctypes.data, v)
    out.append(('equal counts: the one-shot class wins', v[1] == 1 and v[3] == 0))
    for _ in range(1000):
        lib.lc_learn(x.ctypes.data, 3)
    lib.lc_votes(x.ctypes.data, v)
    out.append(('1000 more windows (counter halves at 255): still the learned class', v[3] == 1))
    for _ in range(600):
        lib.lc_learn(x.ctypes.data, 1)
    lib.lc_votes(x.ctypes.data, v)
    out.append(('then 600 windows of the one-shot class: it wins again', v[1] == 1))
    lib.lc_reset()
    lib.lc_votes(x.ctypes.data, v)
    out.append(('lc_reset: back to the one-shot model', v[1] == 1 and v[0] == 99))
    big = base.copy()
    big[-1] = 65535
    mb = Model(*[a.ctypes.data for a in (roots, feat, thr, left, right, big)])
    out.append(('lc_init refuses a model that needs more counter rows than LC_MAX_LEAVES', lib.lc_init(ctypes.byref(mb)) == -1))
    return out


def arm_size(need):
    """object size of leafcal.c for Cortex-M7 with LC_MAX_LEAVES = need of each k"""
    rows = []
    d = os.path.join(P.ROOT, 'build', 'arm_leafcal')
    os.makedirs(d, exist_ok=True)
    for k, n in need.items():
        cap = int(-(-n // 256) * 256)
        obj = os.path.join(d, f'leafcal_k{k}.o')
        subprocess.run(['arm-none-eabi-gcc'] + ARM_FLAGS + [f'-DLC_MAX_LEAVES={cap}', '-c', os.path.join(CSRC, 'leafcal.c'),
                                                            '-o', obj], check=True)
        out = subprocess.run(['arm-none-eabi-size', obj], check=True, capture_output=True, text=True).stdout.split('\n')[1].split()
        su = [int(line.split('\t')[1]) for line in open(obj[:-1] + 'su')]
        rows.append(dict(k=k, leaves_needed_max=n, LC_MAX_LEAVES=cap, text=int(out[0]), data=int(out[1]), bss=int(out[2]),
                         max_stack_frame=max(su), leaf_base_table=2 * (LS.N + 1)))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--k', type=int, nargs='+', default=[50, 25, 10, 0])
    ap.add_argument('--shifts', type=float, nargs='+', default=[0, 0.5])
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--subjects', type=int, nargs='+', default=list(range(20)))
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--arm', action='store_true')
    args = ap.parse_args()
    lib = build()
    print('static bytes (PC build, default LC_MAX_LEAVES):', lib.lc_static_bytes())
    checks = extra_checks(lib)
    for name, ok in checks:
        print('PASS' if ok else 'FAIL', name)
    import check_leafcal_c as M                          # workers import the module instead of pickling __main__
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(M.job)(s, seed, sh, args.k) for sh in args.shifts
                                                for seed in args.seeds for s in args.subjects)
    df = pd.DataFrame([r for rows in res for r in rows])
    df.to_csv(os.path.join(OUT, 'leafcal_c_check.csv'), index=False, float_format='%.4f')
    sm = df.groupby(['shift', 'k']).agg(runs=('agree', 'size'), windows=('windows', 'sum'), agree=('agree', 'sum'),
                                        leaves_mean=('leaves', 'mean'), leaves_max=('leaves', 'max'),
                                        acc_py=('acc_py', 'mean'), acc_c=('acc_c', 'mean')).reset_index()
    sm['agree_pct'] = sm.agree / sm.windows * 100
    sm['extra_checks_passed'] = f'{sum(ok for _, ok in checks)}/{len(checks)}'
    sm.to_csv(os.path.join(OUT, 'leafcal_c_summary.csv'), index=False, float_format='%.6g')
    pd.set_option('display.width', 200)
    print(sm.to_string(index=False))
    if args.arm:
        a = arm_size(df.groupby('k').leaves.max().to_dict())
        a.to_csv(os.path.join(OUT, 'arm_leafcal_size.csv'), index=False)
        print(a.to_string(index=False))


if __name__ == '__main__':
    main()
