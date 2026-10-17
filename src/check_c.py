"""Stage 3.3: compile the C models with the PC gcc and check predictions against Python.

For every configuration in export_c.CONFIGS, builds two executables (our table runtime and
emlearn), runs them on build/test_X.bin and compares with the Python references.
Writes results/c_check.csv and, for mismatching samples, results/c_check_mismatch_<cfg>_<impl>.csv.

Usage: .venv/Scripts/python src/check_c.py [--cc gcc] [--configs full_f32 ...]
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_c  # noqa: E402

ROOT = export_c.P.ROOT
BUILD = export_c.BUILD
CSRC = export_c.CSRC
OUT = os.path.join(ROOT, 'results')


def emlearn_dir():
    import emlearn
    return os.path.dirname(emlearn.__file__)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cc', default=shutil.which('gcc') or 'gcc')
    ap.add_argument('--configs', nargs='+', default=list(export_c.CONFIGS))
    args = ap.parse_args()
    ver = subprocess.run([args.cc, '--version'], capture_output=True, text=True).stdout.splitlines()[0]
    print('compiler:', args.cc, '|', ver)

    X = np.fromfile(os.path.join(BUILD, 'test_X.bin'), dtype=np.float32).reshape(-1, 80)
    y = np.fromfile(os.path.join(BUILD, 'test_y.bin'), dtype=np.int32)
    rows = []
    for cfg in args.configs:
        d = os.path.join(BUILD, cfg)
        i16 = export_c.CONFIGS[cfg]['precision'] == 'int16'
        ref = np.fromfile(os.path.join(d, 'ref_pred.bin'), dtype=np.int32)
        ref_le = np.fromfile(os.path.join(d, 'ref_pred_le.bin'), dtype=np.int32)
        f64 = np.fromfile(os.path.join(d, 'ref_pred_f64.bin'), dtype=np.int32)
        for impl in ['table', 'emlearn']:
            exe = os.path.join(d, f'test_{impl}.exe')
            cmd = [args.cc, '-std=c99', '-O2', '-Wall', '-I', d, '-I', CSRC,
                   os.path.join(CSRC, 'test_pc.c'), '-o', exe, '-lm']
            if impl == 'table':
                cmd.insert(-3, os.path.join(CSRC, 'rf_predict.c'))
            else:
                cmd[4:4] = ['-DUSE_EMLEARN', '-I', emlearn_dir()]
            if i16:
                cmd.insert(1, '-DFEATURES_INT16')
            t0 = time.time()
            r = subprocess.run(cmd, capture_output=True, text=True)
            t_build = time.time() - t0
            if r.returncode != 0:
                print(cfg, impl, 'BUILD FAILED\n', r.stderr[-3000:])
                rows.append(dict(config=cfg, impl=impl, build='failed'))
                continue
            warn = r.stderr.count('warning:')
            out = os.path.join(d, f'pred_{impl}.bin')
            subprocess.run([exe, os.path.join(BUILD, 'test_X.bin'), out], check=True, capture_output=True)
            c = np.fromfile(out, dtype=np.int32)
            mism = np.flatnonzero(c != ref)
            row = dict(config=cfg, impl=impl, build='ok', build_s=round(t_build, 1), warnings=warn,
                       n=len(c), match_python_pct=100 * np.mean(c == ref), n_mismatch=len(mism),
                       acc_c_pct=100 * np.mean(c == y), acc_python_pct=100 * np.mean(ref == y),
                       match_python_float64_pct=100 * np.mean(c == f64),
                       python_lt_vs_le_match_pct=100 * np.mean(ref == ref_le))
            rows.append(row)
            print(row)
            if len(mism):
                pd.DataFrame(dict(sample=mism, c_pred=c[mism], python_pred=ref[mism], label=y[mism])).to_csv(
                    os.path.join(OUT, f'c_check_mismatch_{cfg}_{impl}.csv'), index=False)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, 'c_check.csv'), index=False, float_format='%.3f')
    print(df.to_string(index=False))


if __name__ == '__main__':
    main()
