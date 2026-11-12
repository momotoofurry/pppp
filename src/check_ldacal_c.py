"""C LDA re-calibration (src/c/ldacal.c, float32) against its float64 reference (lda_anchor.OasLDA): predictions per
window on the development data, and the Cortex-M7 object size. Exploratory (report 35.10).

Per subject and shift (LDA has no randomness), base stream, anchors and scoring as leaf_sweep.py, two modes:
  r    ld_reset before every anchor                  (LDAr_oas)
  cum  day-1 calibration, then every anchor is added (LDAcum_oas)
Both sides get the same Q5.10 rows. float32 against float64 is not bit-exact, so the check is the share of
windows with the same prediction and the accuracy of both; the shrinkage rho of every fit is compared too.
Writes results/ldacal_c_check.csv, ldacal_c_summary.csv; with --arm also arm_ldacal_size.csv.
Usage (in the container): python src/check_ldacal_c.py [--arm] [--jobs 19]
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
import lda_anchor as LA  # noqa: E402
import leaf_sweep as LS  # noqa: E402
import pipeline as P  # noqa: E402
import zscore_sweep as ZW  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
CSRC = os.path.join(P.ROOT, 'src', 'c')
LIB = os.path.join(P.ROOT, 'build', 'c', 'libldacal.so')
ARM_FLAGS = ['-mcpu=cortex-m7', '-mthumb', '-mfpu=fpv5-d16', '-mfloat-abi=hard', '-Os', '-ffunction-sections',
             '-fdata-sections', '-std=c99', '-Wall', '-fstack-usage']


def build():
    src = os.path.join(CSRC, 'ldacal.c')
    dep = [src, src[:-1] + 'h']
    if not os.path.exists(LIB) or os.path.getmtime(LIB) < max(os.path.getmtime(d) for d in dep):
        os.makedirs(os.path.dirname(LIB), exist_ok=True)
        subprocess.run(['gcc', '-O2', '-std=c99', '-Wall', '-Wextra', '-Werror', '-fPIC', '-shared', '-o', LIB, src,
                        '-lm'], check=True)
    lib = ctypes.CDLL(LIB)
    lib.ld_add.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.ld_predict.argtypes = [ctypes.c_void_p]
    lib.ld_shrinkage.restype = ctypes.c_float
    lib.ld_static_bytes.restype = ctypes.c_uint
    return lib


def q(X):
    return np.ascontiguousarray(P.quantize(X))


def job(subject, shift):
    lib = build()
    Xc_raw, yc, blocks, _ = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    rows = []
    for mode in ('r', 'cum'):
        ref = LA.OasLDA()
        lib.ld_reset()
        if mode == 'cum':
            Z = LA.zs(Xc_raw)
            ref.add(Z, yc)
            for row, c in zip(q(Z), yc):
                lib.ld_add(row.ctypes.data, int(c))
        n = agree = ok_py = ok_c = 0
        drho = 0.0
        for b, (X, y) in enumerate(blocks):
            y = y.astype(np.int64)
            a, u = LS.anchor_split(y)
            mu, sd = X[a].mean(0), X[a].std(0)
            Za, Zu = (X[a] - mu) / sd, (X[u] - mu) / sd
            if mode == 'r':
                ref = LA.OasLDA()
                lib.ld_reset()
            ref.add(Za, y[a])
            ref.fit()
            for row, c in zip(q(Za), y[a]):
                lib.ld_add(row.ctypes.data, int(c))
            assert lib.ld_fit() == 0
            drho = max(drho, abs(lib.ld_shrinkage() - ref.rho))
            pp = ref.predict(Zu)
            pc = np.array([lib.ld_predict(row.ctypes.data) for row in q(Zu)])
            if b >= 1:
                n += len(pp)
                agree += int(np.sum(pp == pc))
                ok_py += int(np.sum(pp == y[u]))
                ok_c += int(np.sum(pc == y[u]))
        rows.append(dict(subject=subject, shift=shift, mode=mode, windows=n, agree=agree, acc_py=ok_py / n * 100,
                         acc_c=ok_c / n * 100, max_rho_diff=drho, rho_last=ref.rho))
    return rows


def extra_checks(lib):
    out = []
    lib.ld_reset()
    out.append(('ld_fit refuses when a class has no window', lib.ld_fit() == -1))
    rng = np.random.default_rng(0)
    for c in range(6):                                       # one identical row per class: zero within-class scatter
        row = np.ascontiguousarray((rng.normal(size=80) * 1024).astype(np.int16))
        lib.ld_add(row.ctypes.data, c)
    r = lib.ld_fit()
    out.append(('zero covariance: refused (-2), no crash', r == -2))
    return out


def arm_size():
    d = os.path.join(P.ROOT, 'build', 'arm_ldacal')
    os.makedirs(d, exist_ok=True)
    obj = os.path.join(d, 'ldacal.o')
    subprocess.run(['arm-none-eabi-gcc'] + ARM_FLAGS + ['-c', os.path.join(CSRC, 'ldacal.c'), '-o', obj], check=True)
    out = subprocess.run(['arm-none-eabi-size', obj], check=True, capture_output=True, text=True).stdout.split('\n')[1].split()
    su = [int(line.split('\t')[1]) for line in open(obj[:-1] + 'su')]
    return pd.DataFrame([dict(text=int(out[0]), data=int(out[1]), bss=int(out[2]), max_stack_frame=max(su))])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--arm', action='store_true')
    args = ap.parse_args()
    import check_features_c as FC
    import check_ldacal_c as M
    FC.lib()
    lib = build()
    print('static bytes (PC build):', lib.ld_static_bytes())
    checks = extra_checks(lib)
    for name, ok in checks:
        print('PASS' if ok else 'FAIL', name)
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(M.job)(s, sh) for sh in (0.0, 0.5) for s in range(20))
    df = pd.DataFrame([r for rows in res for r in rows])
    df.to_csv(os.path.join(OUT, 'ldacal_c_check.csv'), index=False, float_format='%.6g')
    sm = df.groupby(['shift', 'mode']).agg(runs=('agree', 'size'), windows=('windows', 'sum'), agree=('agree', 'sum'),
                                           acc_py=('acc_py', 'mean'), acc_c=('acc_c', 'mean'),
                                           max_rho_diff=('max_rho_diff', 'max'), rho_last=('rho_last', 'mean')).reset_index()
    sm['agree_pct'] = sm.agree / sm.windows * 100
    sm.to_csv(os.path.join(OUT, 'ldacal_c_summary.csv'), index=False, float_format='%.6g')
    pd.set_option('display.width', 200)
    print(sm.to_string(index=False))
    if args.arm:
        a = arm_size()
        a.to_csv(os.path.join(OUT, 'arm_ldacal_size.csv'), index=False)
        print(a.to_string(index=False))


if __name__ == '__main__':
    main()
