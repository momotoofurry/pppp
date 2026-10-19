"""ctypes wrapper for the C Barnes-Hut t-SNE (src/c/tsne.c), a drop-in for sklearn TSNE in manifold_clustering.

build() compiles build/c/libtsne.so with the host gcc (PC check; TSNE_NMAX 1500 so every buffer size fits).
CTSNE(max_iter, perplexity).fit_transform(X): X is the class-balanced buffer as float (Q5.10 values when the
buffer is int16) and is quantised to int16 exactly as it is stored on the MCU. The initial embedding is drawn
like sklearn's init='random' (1e-4 * standard normal from numpy's global RNG, cast to float32), so the RNG
stream of the rest of self-calibration is unchanged.
"""
import ctypes
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as P  # noqa: E402

CSRC = os.path.join(P.ROOT, 'src', 'c')
LIB = os.path.join(P.ROOT, 'build', 'c', 'libtsne.so')
NMAX = 1500


class Stats(ctypes.Structure):
    _fields_ = [('n_iter', ctypes.c_int), ('cells_max', ctypes.c_int), ('cell_overflow', ctypes.c_int),
                ('tree_depth_max', ctypes.c_int), ('grad_norm', ctypes.c_double)]


def build(cc='gcc'):
    src = [os.path.join(CSRC, 'tsne.c')]
    if os.path.exists(LIB) and os.path.getmtime(LIB) >= max(os.path.getmtime(s) for s in src + [src[0][:-1] + 'h']):
        return LIB
    os.makedirs(os.path.dirname(LIB), exist_ok=True)
    subprocess.run([cc, '-O2', '-std=c99', '-Wall', '-fPIC', '-shared', f'-DTSNE_NMAX={NMAX}', '-o', LIB] + src
                   + ['-lm'], check=True)
    return LIB


_lib = None


def lib():
    global _lib
    if _lib is None:
        _lib = ctypes.CDLL(build())
        _lib.tsne_run.restype = ctypes.c_int
        _lib.tsne_run.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_float, ctypes.c_int, ctypes.c_void_p,
                                  ctypes.c_void_p, ctypes.POINTER(Stats)]
    return _lib


def run(Xq, max_iter=1000, perplexity=10.0, init=None):
    """Xq: n x 80 int16. Returns (embedding n x 3 float32, Stats)."""
    Xq = np.ascontiguousarray(Xq, dtype=np.int16)
    n = len(Xq)
    if init is None:
        init = 1e-4 * np.random.standard_normal(size=(n, 3)).astype(np.float32)
    init = np.ascontiguousarray(init, dtype=np.float32)
    y = np.empty_like(init)
    st = Stats()
    r = lib().tsne_run(Xq.ctypes.data, n, perplexity, max_iter, init.ctypes.data, y.ctypes.data, ctypes.byref(st))
    if r != 0:
        raise ValueError(f'tsne_run failed for n = {n}')
    return y, st


class CTSNE:
    """Accepts (and ignores) the sklearn keyword arguments the upstream call passes."""
    last_stats = None

    def __init__(self, max_iter=1000, perplexity=10.0, **_):
        self.max_iter, self.perplexity = max_iter, perplexity

    def fit_transform(self, X):
        n = len(X)
        init = 1e-4 * np.random.standard_normal(size=(n, 3)).astype(np.float32)   # sklearn init='random'
        y, st = run(P.quantize(X), self.max_iter, self.perplexity, init)
        CTSNE.last_stats = st
        self.n_iter_ = st.n_iter
        return y.astype(np.float64)
