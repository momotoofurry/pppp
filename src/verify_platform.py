"""Cross-platform check: rerun a small slice of the experiments and compare with the committed results.

The committed results were produced on Windows (Python 3.12.3, same package versions). On another
platform (e.g. the Docker image) the RNG streams are identical, but BLAS / compiler differences can
change floating-point results, which t-SNE and RF training may amplify. This script measures that
instead of assuming it:
  1. vectorised predictor == upstream get_predictions (pipeline.verify_predict)
  2. compression sweep, subject 0, seed 0 (60 configs x 11 blocks) vs results/sweep_acc.csv
  3. self-calibration, subject 0, seed 0, 100 trees / depth 10 / int16 vs results/selfcal_sweep*.csv
     (--full adds the 400-tree float64 upstream-equivalent config)
  4. --features-ref DIR: compare every feature file in external/.../features_arm_position with DIR
     (e.g. a copy of the Windows features), max absolute and relative difference
Writes results/platform_check.csv. Usage: python src/verify_platform.py [--full] [--features-ref DIR]
"""
import argparse
import glob
import os
import platform
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compression_sweep  # noqa: E402
import pipeline as P  # noqa: E402
import selfcal_sweep  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')


def compare(name, ours, ref, key, cols):
    m = ours.merge(ref, on=key, suffixes=('', '_ref'), how='left', indicator=True)
    missing = int((m._merge != 'both').sum())
    out = []
    for c in cols:
        d = (m[c] - m[c + '_ref']).abs()
        out.append(dict(check=name, column=c, rows=len(m), missing_in_ref=missing,
                        exact_match_pct=100 * float(np.mean(np.isclose(m[c], m[c + '_ref'], rtol=0, atol=1e-4))),
                        max_abs_diff=float(d.max())))
        print(out[-1])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--full', action='store_true')
    ap.add_argument('--features-ref', default=None)
    args = ap.parse_args()
    # The sweeps ran inside joblib workers, which limit BLAS/OpenMP to 1 thread each. Self-calibration
    # (t-SNE -> K-Means -> retrained trees) changes with the thread count, so match it here.
    from threadpoolctl import threadpool_limits
    threadpool_limits(1)
    import scipy
    import sklearn
    print(f'platform: {platform.platform()} | python {platform.python_version()} | numpy {np.__version__} '
          f'| scipy {scipy.__version__} | sklearn {sklearn.__version__}')
    rows = []

    if args.features_ref:
        print('\n[0] features vs', args.features_ref)
        base = os.path.join(P.REPO, 'features_arm_position')
        worst_abs, worst_rel, n, n_exact = 0.0, 0.0, 0, 0
        for f in sorted(glob.glob(os.path.join(base, '*', '*', '*.npy'))):
            a, b = np.load(f), np.load(os.path.join(args.features_ref, os.path.relpath(f, base)))
            d = np.abs(a - b)
            worst_abs = max(worst_abs, float(d.max()))
            worst_rel = max(worst_rel, float(np.max(d / np.maximum(np.abs(b), 1e-12))))
            n_exact += int(np.array_equal(a, b))
            n += 1
        rows.append(dict(check='features_arm_position', column=f'{n_exact}/{n} files bit-identical', rows=n,
                         missing_in_ref=0, exact_match_pct=100 * n_exact / n, max_abs_diff=worst_abs,
                         max_rel_diff=worst_rel))
        print(rows[-1])

    print('\n[1] vectorised predict vs upstream get_predictions')
    P.verify_predict()

    print('\n[2] compression sweep, subject 0, seed 0')
    t0 = time.time()
    acc, _ = compression_sweep.run_subject(0, [0])
    ours = pd.DataFrame(acc).astype({'max_depth': str})
    ref = pd.read_csv(os.path.join(OUT, 'sweep_acc.csv'), dtype={'max_depth': str})
    ref = ref[(ref.subject == 0) & (ref.seed == 0)]
    rows += compare('compression_sweep s0 seed0', ours, ref,
                    ['subject', 'max_depth', 'n_trees', 'seed', 'precision', 'block'], ['accuracy', 'compact_B'])
    print(f'  ({time.time() - t0:.0f} s)')

    print('\n[3] self-calibration, subject 0, seed 0')
    cfgs = [(100, 10, 'int16')] + ([(400, None, 'float64')] if args.full else [])
    ref = pd.read_csv(os.path.join(OUT, 'selfcal_sweep.csv'), dtype={'max_depth': str}, keep_default_na=False)
    ref_t = pd.read_csv(os.path.join(OUT, 'selfcal_sweep_trees.csv'))
    for N, d, prec in cfgs:
        t0 = time.time()
        acc, tree = selfcal_sweep.run_subject(0, N, d, prec, 0)
        ours = pd.DataFrame(acc).astype({'max_depth': str})
        name = selfcal_sweep.cfg_name(N, d, prec)
        r = ref[(ref.config == name) & (ref.seed == 0) & (ref.subject == 0)]
        rows += compare(f'selfcal {name} s0 seed0', ours, r, ['config', 'seed', 'subject', 'block'],
                        ['acc_oneshot', 'acc_selfcal'])
        rt = ref_t[(ref_t.config == name) & (ref_t.seed == 0) & (ref_t.subject == 0)]
        rows += compare(f'selfcal trees {name} s0 seed0', pd.DataFrame([tree]), rt, ['config', 'seed', 'subject'],
                        ['app_nodes_mean', 'compact_B'])
        print(f'  ({time.time() - t0:.0f} s)')

    df = pd.DataFrame(rows)
    df.insert(0, 'platform', f'{platform.system()} py{platform.python_version()}')
    df.to_csv(os.path.join(OUT, 'platform_check.csv'), index=False, float_format='%.6g')
    ok = (df.exact_match_pct == 100).all()
    print('\nRESULT:', 'identical to committed results' if ok else 'DIFFERS from committed results (see table)')
    print(df.to_string(index=False))


if __name__ == '__main__':
    main()
