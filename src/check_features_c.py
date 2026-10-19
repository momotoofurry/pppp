"""C feature extraction (src/c/features.c, float32, streaming) vs the upstream features, on the raw EMG.

For every subject / folder / trial of dataset_arm_position the raw recording (8 x 4000, float32) is streamed
sample by sample through the C code from a zero state (as upstream filters each trial from zi=None); windows
9..18 are kept, as upstream. The features are written to build/features_c/<subject>/<folder>/feature_<f>.npy
in the upstream layout (trials x 10 windows x 8 channels), so selfcal_sweep.py --features-dir build/features_c
can use them. Compared with features_arm_position/ per feature: continuous ones by relative error, counts
(SSC, ZC) and frequency bins (MDF, PKF) by exact agreement and by how far they move.
Writes results/features_c_check.csv. Usage (in the container): python src/check_features_c.py
"""
import ctypes
import os
import subprocess
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as P  # noqa: E402

CSRC = os.path.join(P.ROOT, 'src', 'c')
LIB = os.path.join(P.ROOT, 'build', 'c', 'libfeatures.so')
OUT_DIR = os.path.join(P.ROOT, 'build', 'features_c')
OUT = os.path.join(P.ROOT, 'results')
FEATS = P.FEATS                                    # upstream order: rms wl ssc zc mav skw vcf mdf mnf pkf
NWIN, W0 = 19, 9


def lib():
    src = os.path.join(CSRC, 'features.c')
    if not os.path.exists(LIB) or os.path.getmtime(LIB) < max(os.path.getmtime(src), os.path.getmtime(src[:-1] + 'h')):
        os.makedirs(os.path.dirname(LIB), exist_ok=True)
        subprocess.run(['gcc', '-O2', '-std=c99', '-Wall', '-fPIC', '-shared', '-o', LIB, src, '-lm'], check=True)
    L = ctypes.CDLL(LIB)
    L.fe_recording.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    L.fe_static_bytes.restype = ctypes.c_uint
    L.fe_init()
    return L


def main():
    L = lib()
    ref_dir = os.path.join(P.REPO, 'features_arm_position')
    raw_dir = os.path.join(P.REPO, 'dataset_arm_position')
    rows = []
    for subject in range(20):
        for folder in sorted(os.listdir(os.path.join(raw_dir, str(subject)))):
            data = np.load(os.path.join(raw_dir, str(subject), folder, 'data.npy')).astype(np.float32)
            out = np.zeros((len(data), NWIN, 80), dtype=np.float32)
            for t, rec in enumerate(data):
                rec = np.ascontiguousarray(rec)
                w = L.fe_recording(rec.ctypes.data, rec.shape[1], out[t].ctypes.data, NWIN)
                assert w == NWIN, w
            od = os.path.join(OUT_DIR, str(subject), folder)
            os.makedirs(od, exist_ok=True)
            for k, f in enumerate(FEATS):
                c = out[:, W0:, k * 8:(k + 1) * 8].astype(np.float64)
                np.save(os.path.join(od, f'feature_{f}.npy'), c)
                u = np.load(os.path.join(ref_dir, str(subject), folder, f'feature_{f}.npy'))
                d = np.abs(c - u)
                rows.append(dict(subject=subject, folder=folder, feature=f, n=u.size,
                                 exact=np.mean(c == u), rel_med=np.median(d / np.maximum(np.abs(u), 1e-30)),
                                 rel_max=np.max(d / np.maximum(np.abs(u), 1e-30)), abs_max=d.max(),
                                 abs_mean=d.mean(), ref_abs_mean=np.abs(u).mean()))
        print('subject', subject, 'done', flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, 'features_c_check.csv'), index=False, float_format='%.6g')
    g = df.groupby('feature', sort=False)
    s = pd.DataFrame({'values': g.n.sum(), 'exact_pct': g.apply(lambda x: np.average(x.exact, weights=x.n)) * 100,
                      'rel_err_median': g.rel_med.median(), 'rel_err_max': g.rel_max.max(), 'abs_err_max': g.abs_max.max(),
                      'abs_err_mean': g.apply(lambda x: np.average(x.abs_mean, weights=x.n)),
                      'ref_abs_mean': g.apply(lambda x: np.average(x.ref_abs_mean, weights=x.n))})
    pd.set_option('display.width', 200)
    print(s.to_string(float_format=lambda v: f'{v:.3g}'))
    print('static bytes of features.c:', L.fe_static_bytes())


if __name__ == '__main__':
    main()
