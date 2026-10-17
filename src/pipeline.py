"""Fast re-implementation of the upstream one-shot pipeline (prune + append, no self-calibration).

- Features are loaded and normalised exactly as in main_replay_arm_position.py.
- Pruning calls the upstream emg_functions.prune unchanged.
- Prediction is a vectorised version of emg_functions.get_predictions (same `<` comparison,
  same hard majority vote, ties -> lowest class index); verify_predict() checks it is identical.
"""
import copy
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.join(ROOT, 'external', 'self-calibrating-rf')
sys.path.insert(0, REPO)
import emg_functions  # noqa: E402

FEATS = ['rms', 'wl', 'ssc', 'zc', 'mav', 'skw', 'vcf', 'mdf', 'mnf', 'pkf']  # upstream order
N_BLOCKS = 11
Q_SHIFT = 10            # int16 fixed point: Q5.10, value = round(x * 1024), range +-32


def load_folder(dataset, subject, folder):
    fp = os.path.join(REPO, f'features_{dataset}', str(subject), folder)
    label = np.load(os.path.join(REPO, f'dataset_{dataset}', str(subject), folder, 'label.npy'))
    f = [np.load(os.path.join(fp, f'feature_{k}.npy')) for k in FEATS]
    nwin = f[0].shape[1]
    X = np.concatenate([np.reshape(a, (-1, 8), 'C') for a in f], axis=1)
    return X, np.repeat(label, nwin)


def load_subject(subject, dataset='arm_position', n_blocks=N_BLOCKS):
    """Returns normalised calibration (Xc, yc) and a list of normalised test blocks [(X, y), ...]."""
    Xc, yc = load_folder(dataset, subject, 'calibration')
    mu, sd = Xc.mean(0), Xc.std(0)
    blocks = []
    for b in range(n_blocks):
        X, y = load_folder(dataset, subject, f'testing_block{b}')
        blocks.append(((X - mu) / sd, y))
    return (Xc - mu) / sd, yc, blocks


def load_pretrain(name='model_pretrain_with_66_participants.joblib'):
    import joblib
    return emg_functions.get_sklearn_rf_parameters(joblib.load(os.path.join(REPO, 'model_pretrain', name)))


def leaf_labels(mdl):
    """Per tree: class label of every node (argmax of value), as int."""
    cls = np.asarray(mdl['classes'])
    return [cls[np.argmax(v[:, 0, :], axis=1)].astype(np.int64) for v in mdl['value']]


def quantize(x):
    return np.clip(np.round(np.asarray(x) * (1 << Q_SHIFT)), -32768, 32767).astype(np.int16)


def predict(mdl, X, precision='float64', op='<'):
    """Vectorised hard-vote prediction. precision: float64 (upstream), float32 or int16 (Q5.10)."""
    if precision == 'float32':
        Xp, thr = X.astype(np.float32), [t.astype(np.float32) for t in mdl['threshold']]
    elif precision == 'int16':
        Xp, thr = quantize(X), [quantize(t) for t in mdl['threshold']]
    else:
        Xp, thr = X, mdl['threshold']
    n = len(Xp)
    labels = leaf_labels(mdl)
    votes = np.zeros((n, int(np.max(mdl['classes'])) + 1), dtype=np.int32)
    rows = np.arange(n)
    for left, right, feat, t, lab in zip(mdl['left'], mdl['right'], mdl['feature'], thr, labels):
        node = np.zeros(n, dtype=np.int64)
        active = left[node] > 0
        while active.any():
            idx = rows[active]
            nd = node[idx]
            x = Xp[idx, feat[nd]]
            go_left = (x < t[nd]) if op == '<' else (x <= t[nd])
            node[idx] = np.where(go_left, left[nd], right[nd])
            active[idx] = left[node[idx]] > 0
        votes[rows, lab[node]] += 1
    return np.argmax(votes, axis=1)


def subset(mdl, idx):
    out = {k: [mdl[k][i] for i in idx] for k in ['left', 'right', 'feature', 'threshold', 'value']}
    out['classes'] = mdl['classes']
    return out


def train_rf(X, y, n_trees, max_depth, seed):
    from sklearn.ensemble import RandomForestClassifier
    rf = RandomForestClassifier(n_estimators=n_trees, max_depth=max_depth, random_state=seed)
    rf.fit(X, y)
    return emg_functions.get_sklearn_rf_parameters(rf)


def prune(mdl, Xc, yc):
    return emg_functions.prune(copy.deepcopy(mdl), Xc, yc)


def verify_predict(subject=0):
    """Check predict() == upstream get_predictions on the pre-trained and on a pruned+appended model."""
    Xc, yc, blocks = load_subject(subject)
    X = np.concatenate([b[0] for b in blocks[:2]])
    pre = load_pretrain()
    m = emg_functions.append(prune(pre, Xc, yc), train_rf(Xc, yc, 200, None, 0))
    for name, mdl in [('pretrained', pre), ('pruned+appended', m)]:
        ref, _ = emg_functions.get_predictions(mdl, X)
        ours = predict(mdl, X)
        print(f'{name}: {len(X)} samples, identical = {np.array_equal(ref, ours)}')
        for p in ['float32', 'int16']:
            print(f'  {p} vs float64 agreement: {np.mean(predict(mdl, X, p) == ours) * 100:.2f}%')
        print(f'  "<=" vs "<" agreement: {np.mean(predict(mdl, X, op="<=") == ours) * 100:.2f}%')


if __name__ == '__main__':
    verify_predict()
