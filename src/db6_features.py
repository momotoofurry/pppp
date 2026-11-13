"""NinaPro DB6 (Palermo et al. 2017): C features of the first electrode ring, streamed over each whole session, plus a
compact copy of the data needed to redo it (report 35.31). Read-only input, nothing is modified.

Input  /dl/ninapro_a, /dl/ninapro_b: S{s}_D{d}_T{t}.mat (MATLAB v5), emg 16 columns at 2 kHz (volts), restimulus,
       rerepetition. Ring 1 = columns 0-7 (columns 8-9 are empty in every file, column 7 has a low gain).
Output /db6/raw/S{s}_D{d}_T{t}.npz      emg8 float32 (n x 8, columns 0-7 unchanged), restimulus int8, rerepetition int8
       /db6/features/S{s}_D{d}_T{t}.npz F float32 (W x 80, upstream order rms wl ssc zc mav skw vcf mdf mnf pkf x 8
                                         channels, src/c/features.c streamed over the session: window w = samples
                                         200 w .. 200 w + 399), lab int8 (restimulus if constant over the window else
                                         -1), rep int8 (rerepetition likewise), seg int16 (restimulus segment number
                                         likewise)
Usage (in the container): python src/db6_features.py [--jobs 6]
"""
import argparse
import glob
import os
import re
import sys

import numpy as np
import scipy.io as sio
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_features_c as FC  # noqa: E402

RING1 = list(range(8))
WIN, STEP = 400, 200


def files():
    out = {}
    for f in glob.glob('/dl/ninapro_[ab]/**/S*_D*_T*.mat', recursive=True):
        if '__MACOSX' in f:
            continue
        m = re.match(r'S(\d+)_D(\d)_T(\d)\.mat$', os.path.basename(f))
        out[tuple(int(g) for g in m.groups())] = f
    return dict(sorted(out.items()))


def one(key, path):
    name = 'S%d_D%d_T%d' % key
    fo = f'/db6/features/{name}.npz'
    m = sio.loadmat(path, variable_names=['emg', 'restimulus', 'rerepetition'])
    emg = np.asarray(m['emg'], dtype=np.float32)
    rs = np.asarray(m['restimulus']).ravel().astype(np.int8)
    rr = np.asarray(m['rerepetition']).ravel().astype(np.int8)
    assert emg.shape[1] == 16 and len(rs) == len(emg) == len(rr), (emg.shape, rs.shape)
    x = np.ascontiguousarray(emg[:, RING1].T)                       # 8 x n, channel-major as fe_recording expects
    n = x.shape[1]
    nw = (n - WIN) // STEP + 1
    F = np.zeros((nw, 80), dtype=np.float32)
    L = FC.lib()
    assert L.fe_recording(x.ctypes.data, n, F.ctypes.data, nw) == nw
    seg = np.r_[0, np.cumsum(rs[1:] != rs[:-1])].astype(np.int32)
    s0, s1 = np.arange(nw) * STEP, np.arange(nw) * STEP + WIN - 1
    pure = seg[s0] == seg[s1]
    lab = np.where(pure, rs[s0], -1).astype(np.int8)
    rep = np.where(pure, rr[s0], -1).astype(np.int8)
    sg = np.where(pure, seg[s0], -1).astype(np.int16)
    np.savez_compressed(f'/db6/raw/{name}.npz', emg8=np.ascontiguousarray(emg[:, RING1]), restimulus=rs, rerepetition=rr)
    np.savez(fo, F=F, lab=lab, rep=rep, seg=sg)
    order = [int(rs[i]) for i in np.flatnonzero(np.r_[True, rs[1:] != rs[:-1]])][:12]
    gl = [np.mean([np.sum((lab == c) & (rep == r)) for r in range(1, 13)]) for c in np.unique(rs) if c > 0]
    return (f'{name}: {n / 2000 / 60:5.2f} min, {nw} windows, {pure.mean() * 100:4.1f} % pure, first segments {order}, '
            f'mean pure windows per repetition {np.round(gl, 1).tolist()}, ch std uV {np.round(emg[:, RING1].std(0) * 1e6, 1).tolist()}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=6)
    args = ap.parse_args()
    fs = files()
    print(len(fs), 'session files')
    assert len(fs) == 100, len(fs)
    FC.lib()
    for line in Parallel(n_jobs=args.jobs, verbose=0)(delayed(one)(k, p) for k, p in fs.items()):
        print(line, flush=True)


if __name__ == '__main__':
    main()
