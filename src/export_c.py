"""Stage 3.1: export candidate RF configurations to C headers, plus test data and Python references.

Model = subject 0, seed 0, built exactly as in compression_sweep.py (truncate -> prune -> keep
first N//2 pre-trained trees -> append N - N//2 calibration trees), then compacted (pruned,
unreachable nodes removed).

For each configuration, writes build/<cfg>/:
  emlearn_model.h  emlearn output. float32 -> method='inline' (if/else code);
                   int16 -> method='loadable' (node table); thresholds pre-quantised to Q5.10
  rf_model.h       our own table: struct-of-arrays, internal nodes only, leaves inlined in the
                   child index (bit 15 set -> leaf, low bits = class), per-tree root offsets
  ref_pred.bin     int32 Python reference predictions on the test set, same arithmetic as the C
                   code: float32 features/thresholds, or int16 Q5.10, and `x < thr` goes left
  ref_pred_f64.bin int32 predictions of the original float64 model (upstream semantics)
  ref_pred_le.bin  same as ref_pred.bin but with `x <= thr` (sklearn's direction), for comparison
and build/test_X.bin (float32, n x 80), build/test_y.bin (int32), src/c/sample_input.h.

Usage: .venv/Scripts/python src/export_c.py
"""
import copy
import json
import os
import sys
import types

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as P  # noqa: E402
import rf_size  # noqa: E402

BUILD = os.path.join(P.ROOT, 'build')
CSRC = os.path.join(P.ROOT, 'src', 'c')
SUBJECT, SEED = 0, 0
CONFIGS = {
    'full_f32':     dict(max_depth=None, n_trees=400, precision='float32'),
    'd10_n400_i16': dict(max_depth=10, n_trees=400, precision='int16'),
    'd10_n100_i16': dict(max_depth=10, n_trees=100, precision='int16'),
}


def build_model(max_depth, n_trees, Xc, yc, pre):
    pruned = P.prune(rf_size.truncate_depth(copy.deepcopy(pre), max_depth), Xc, yc)
    n_pre = 200 if n_trees == 400 else n_trees // 2
    app = P.train_rf(Xc, yc, n_trees - n_pre, max_depth, SEED * 100000 + SUBJECT * 100 + (max_depth or 0))
    pre_part = P.subset(pruned, range(n_pre))
    mdl = {k: pre_part[k] + app[k] for k in ['left', 'right', 'feature', 'threshold', 'value']}
    mdl['classes'] = pre['classes']
    return rf_size.compact_forest(mdl)


def stored_thresholds(mdl, precision):
    """Thresholds exactly as they are stored in C (float32 values, or Q5.10 integers)."""
    if precision == 'int16':
        return [P.quantize(t).astype(np.float64) for t in mdl['threshold']]
    return [t.astype(np.float32).astype(np.float64) for t in mdl['threshold']]


def emlearn_header(mdl, precision, path):
    import emlearn

    class FakeRFClassifier:  # duck-typed sklearn forest: emlearn only reads these attributes
        pass

    est = FakeRFClassifier()
    est.estimators_ = []
    for l, r, f, t, v in zip(mdl['left'], mdl['right'], mdl['feature'],
                             stored_thresholds(mdl, precision), mdl['value']):
        tree = types.SimpleNamespace(children_left=l, children_right=r, feature=f, threshold=t,
                                     value=v, node_count=len(l))
        est.estimators_.append(types.SimpleNamespace(tree_=tree, n_features_in_=80, n_classes_=6))
    if precision == 'int16':
        w = emlearn.trees.Wrapper(est, method='loadable', dtype='int16_t')
    else:
        w = emlearn.trees.Wrapper(est, method='inline', dtype='float')
    w.save(name='rfmodel', file=path, include_proba=False)
    nodes, roots, leaves = w.forest_
    return dict(emlearn_nodes=len(nodes), emlearn_leaves=len(leaves))


def table_arrays(mdl, precision):
    """Our table format (see rf_predict.h): roots, feat, thr (stored values), left, right."""
    feat, thr, left, right, roots = [], [], [], [], []
    thr_all = stored_thresholds(mdl, precision)
    cls_all = P.leaf_labels(mdl)
    for l, r, f, t, cls in zip(mdl['left'], mdl['right'], mdl['feature'], thr_all, cls_all):
        internal = np.flatnonzero(l >= 0)                # pre-order, so children come after parents
        if len(internal) == 0:                           # whole tree pruned to a single leaf
            roots.append(0x80000000 | int(cls[0]))
            continue
        assert internal[0] == 0 and len(internal) < 0x8000
        idx = -np.ones(len(l), dtype=np.int64)
        idx[internal] = np.arange(len(internal))

        def enc(c):
            return 0x8000 | int(cls[c]) if l[c] < 0 else int(idx[c])

        roots.append(len(feat))
        for n in internal:
            feat.append(int(f[n]))
            thr.append(t[n])
            left.append(enc(l[n]))
            right.append(enc(r[n]))
    return roots, feat, thr, left, right


def table_header(mdl, precision, path):
    roots, feat, thr, left, right = table_arrays(mdl, precision)
    is16 = precision == 'int16'
    fmt = (lambda v: str(int(v))) if is16 else (lambda v: repr(float(np.float32(v))) + 'f')
    for v in thr:  # float literals must round-trip to the exact float32 value
        assert is16 or np.float32(float(fmt(v)[:-1])) == np.float32(v)

    def arr(ctype, name, vals, f=str, per_line=16):
        lines = [', '.join(f(v) for v in vals[i:i + per_line]) for i in range(0, len(vals), per_line)]
        return f'static const {ctype} {name}[{len(vals)}] = {{\n  ' + ',\n  '.join(lines) + '\n};\n'

    with open(path, 'w') as fh:
        fh.write('/* Generated by src/export_c.py - do not edit. */\n#pragma once\n#include <stdint.h>\n\n')
        fh.write(f'#define RF_N_TREES {len(roots)}\n#define RF_N_FEATURES 80\n#define RF_N_CLASSES 6\n')
        fh.write(f'#define RF_N_INTERNAL {len(feat)}\n#define RF_INT16 {int(is16)}\n#define RF_Q_SHIFT {P.Q_SHIFT}\n')
        fh.write(f'typedef {"int16_t" if is16 else "float"} rf_value_t;\n\n')
        fh.write(arr('uint32_t', 'rf_roots', roots, lambda v: f'0x{v:08x}u', 8))
        fh.write(arr('uint8_t', 'rf_feat', feat))
        fh.write(arr('rf_value_t', 'rf_thr', thr, fmt, 8))
        fh.write(arr('uint16_t', 'rf_left', left))
        fh.write(arr('uint16_t', 'rf_right', right))
    return dict(table_internal=len(feat),
                table_bytes=len(roots) * 4 + len(feat) * (1 + (2 if is16 else 4) + 4))


def main():
    os.makedirs(BUILD, exist_ok=True)
    Xc, yc, blocks = P.load_subject(SUBJECT)
    X = np.concatenate([b[0] for b in blocks])
    y = np.concatenate([b[1] for b in blocks]).astype(np.int32)
    X32 = X.astype(np.float32)
    X32.tofile(os.path.join(BUILD, 'test_X.bin'))
    y.tofile(os.path.join(BUILD, 'test_y.bin'))
    pre = P.load_pretrain()
    info = {}
    for name, cfg in CONFIGS.items():
        out = os.path.join(BUILD, name)
        os.makedirs(out, exist_ok=True)
        mdl = build_model(cfg['max_depth'], cfg['n_trees'], Xc, yc, pre)
        prec = cfg['precision']
        ref = P.predict(mdl, X32, prec).astype(np.int32)
        ref.tofile(os.path.join(out, 'ref_pred.bin'))
        P.predict(mdl, X32, prec, op='<=').astype(np.int32).tofile(os.path.join(out, 'ref_pred_le.bin'))
        f64 = P.predict(mdl, X).astype(np.int32)
        f64.tofile(os.path.join(out, 'ref_pred_f64.bin'))
        st = rf_size.forest_stats(mdl)
        info[name] = dict(cfg, n_samples=len(y), acc_ref=float(np.mean(ref == y)), acc_f64=float(np.mean(f64 == y)),
                          nodes=sum(s['nodes'] for s in st), internal=sum(s['internal'] for s in st),
                          mean_leaf_depth=float(np.mean([s['mean_leaf_depth'] for s in st])),
                          stage2_compact_bytes=rf_size.forest_bytes(st, prec)['compact'],
                          **table_header(mdl, prec, os.path.join(out, 'rf_model.h')),
                          **emlearn_header(mdl, prec, os.path.join(out, 'emlearn_model.h')))
        print(name, json.dumps(info[name]))
        if name == 'd10_n100_i16':  # one feature vector embedded in the MCU demo main.c
            with open(os.path.join(CSRC, 'sample_input.h'), 'w') as fh:
                fh.write('/* Generated by src/export_c.py: subject 0, testing block 0, window 0. */\n#pragma once\n')
                fh.write(f'#define SAMPLE_LABEL {int(y[0])}\n')
                fh.write('static const float sample_features[80] = {\n  ' +
                         ', '.join(repr(float(v)) + 'f' for v in X32[0]) + '\n};\n')
    with open(os.path.join(BUILD, 'export_info.json'), 'w') as fh:
        json.dump(info, fh, indent=1)


if __name__ == '__main__':
    main()
