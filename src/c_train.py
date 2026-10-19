"""ctypes wrappers for the C tree trainer (src/c/rf_train.c) and K-Means (src/c/kmeans.c).

train_rf(X, y, n_trees, max_depth, max_leaf_nodes): drop-in for pipeline.train_rf in self-calibration. X must be
on the Q5.10 grid (int16 buffer + int16 calibration set); it is quantised to int16 exactly as stored on the MCU.
One seed per tree is drawn from numpy's global RNG. Returns the upstream model dict (left/right/feature/
threshold/value/classes); thresholds are the int16 split values / 1024, so `x < thr` gives the same split in
float64, float32 and int16 prediction.
CKMeans: drop-in for sklearn KMeans(n_clusters, init=<centres>, n_init=1) in manifold_clustering.
build() compiles build/c/libtrain.so (PC check; NMAX 1600 so every buffer size fits).
"""
import ctypes
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as P  # noqa: E402

CSRC = os.path.join(P.ROOT, 'src', 'c')
LIB = os.path.join(P.ROOT, 'build', 'c', 'libtrain.so')
NMAX, MAX_LEAVES, CLASSES = 1600, 32, 6
MAX_NODES = 2 * MAX_LEAVES - 1
MAX_FEATURES = int(np.sqrt(80))          # sklearn max_features='sqrt' -> 8


class Tree(ctypes.Structure):
    _fields_ = [('n_nodes', ctypes.c_int), ('left', ctypes.c_int16 * MAX_NODES), ('right', ctypes.c_int16 * MAX_NODES),
                ('feature', ctypes.c_uint8 * MAX_NODES), ('thr', ctypes.c_int16 * MAX_NODES),
                ('cls', ctypes.c_uint8 * MAX_NODES), ('count', (ctypes.c_uint16 * CLASSES) * MAX_NODES)]


def build(cc='gcc'):
    src = [os.path.join(CSRC, f) for f in ['rf_train.c', 'kmeans.c']]
    deps = src + [s[:-1] + 'h' for s in src]
    if os.path.exists(LIB) and os.path.getmtime(LIB) >= max(os.path.getmtime(s) for s in deps):
        return LIB
    os.makedirs(os.path.dirname(LIB), exist_ok=True)
    subprocess.run([cc, '-O2', '-std=c99', '-Wall', '-fPIC', '-shared', f'-DRFT_NMAX={NMAX}', f'-DKM_NMAX={NMAX}',
                    f'-DRFT_MAX_LEAVES={MAX_LEAVES}', '-o', LIB] + src + ['-lm'], check=True)
    return LIB


_lib = None


def lib():
    global _lib
    if _lib is None:
        _lib = ctypes.CDLL(build())
        _lib.rft_train.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_uint32, ctypes.POINTER(Tree)]
        _lib.km_fit.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int,
                                ctypes.c_float, ctypes.c_void_p]
    return _lib


def tree_dict(t):
    n = t.n_nodes
    left = np.array(t.left[:n], dtype=np.int64)
    right = np.array(t.right[:n], dtype=np.int64)
    leaf = left < 0
    feat = np.where(leaf, -2, np.array(t.feature[:n], dtype=np.int64))
    thr = np.where(leaf, -2.0, np.array(t.thr[:n], dtype=np.float64) / (1 << P.Q_SHIFT))
    value = np.array([list(t.count[i]) for i in range(n)], dtype=np.float64)[:, None, :]
    return left, right, feat, thr, value


def train_rf(X, y, n_trees, max_depth, max_leaf_nodes):
    Xq = np.ascontiguousarray(P.quantize(X))
    assert np.array_equal(Xq.astype(np.float64) / (1 << P.Q_SHIFT), np.asarray(X, dtype=np.float64)), \
        'C training needs Q5.10 data (use --buffer-int16)'
    yy = np.ascontiguousarray(np.asarray(y, dtype=np.uint8))
    n = len(Xq)
    rows = (ctypes.c_void_p * n)(*[Xq.ctypes.data + i * Xq.strides[0] for i in range(n)])
    seeds = np.random.randint(1, 2 ** 31 - 1, size=n_trees)
    out = {k: [] for k in ['left', 'right', 'feature', 'threshold', 'value']}
    t = Tree()
    for s in seeds:
        if lib().rft_train(rows, yy.ctypes.data, n, max_depth, max_leaf_nodes or MAX_LEAVES, MAX_FEATURES, int(s),
                           ctypes.byref(t)) != 0:
            raise ValueError(f'rft_train failed for n = {n}')
        for k, v in zip(['left', 'right', 'feature', 'threshold', 'value'], tree_dict(t)):
            out[k].append(v)
    out['classes'] = np.arange(CLASSES)
    return out


class CKMeans:
    """sklearn KMeans(n_clusters, init=centres, n_init=1, max_iter=300, tol=1e-4) via km_fit."""

    def __init__(self, n_clusters, init, random_state=None, n_init=1, max_iter=300, tol=1e-4):
        self.k, self.init, self.max_iter, self.tol = n_clusters, init, max_iter, tol

    def fit(self, X):
        x = np.ascontiguousarray(X, dtype=np.float32)
        ctr = np.ascontiguousarray(self.init, dtype=np.float32).copy()
        lab = np.zeros(len(x), dtype=np.uint8)
        it = lib().km_fit(x.ctypes.data, len(x), self.k, ctr.ctypes.data, self.max_iter, self.tol, lab.ctypes.data)
        if it < 0:
            raise ValueError('km_fit failed')
        self.labels_, self.cluster_centers_, self.n_iter_ = lab.astype(np.int64), ctr, it + 1
        return self
