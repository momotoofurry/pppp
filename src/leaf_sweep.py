"""Leaf refresh: label-free adaptation of the forest WITHOUT a sample buffer, K-Means or new trees, and a start-up
anchor that decides per session whether the adapted model is used at all. Exploratory PC prototype (Python only;
the frozen firmware and its C code are not touched).

Idea
  leaf refresh  The tree structure and thresholds stay as they are after the one-shot calibration. Every leaf of the
                refreshed trees keeps 6 counters. During a block each window is routed to its leaf in every tree and
                the counter of the forest's own majority vote for that window (pseudo-label, no labels) is increased.
                At the block end the label of a leaf becomes argmax(w0 * onehot(label after one-shot) + counters):
                a leaf changes its class once the new evidence outweighs the prior w0. Counters are multiplied by
                `decay` at every block end. Device cost: 6 counters per leaf; no buffer, no clustering, no training.
  anchor        The first trial of every gesture in a block (6 x 10 = 60 labelled windows) stands for the cued
                start-up sequence of a session. The adapted model and the day-1 model are both scored on it; the
                block is then classified with the adapted model only if it was not worse on the anchor (column
                acc_sel). Anchor windows are never scored and never used for adaptation, in any condition.

Conditions (all on the same one-shot model per subject / seed; MCU setting of shift_sweep.py: 100 trees, depth 10,
int16; scored on the non-anchor windows of every block)
  F        fixed one-shot model, day-1 z-score
  Z        fixed model + class-balanced z-score update (zscore_sweep.py bal0.3, classes = the model's predictions)
  A        Z + self-calibration as zscore_sweep.py with embed='none' (375-row int16 buffer, K-Means on the 80
           features, 20 new trees with <= 32 leaves per block): the Python counterpart of firmware v2, without the
           R3 buffer mapping of the C code
  L...     Z + leaf refresh; name L<trees>_w<w0>_d<decay>: trees = app (the 50 appended trees) or all (100)
  Lall_w4_d1_noz   leaf refresh without the z-score update
  Lall_w4_d1_nog   without the cls5 guard
  R        re-calibration at every block from the anchor (z-score, pruning and 50 new trees from its 60 labelled
           windows): what 12 s of labelled data per session buys
All adaptive conditions except *_nog use the firmware's cls5 guard (no update when fewer than 5 predicted classes
have >= 5 windows in the block).
Streams: base (blocks as recorded) and rest2 (blocks 1.. keep only Rest, Tripod, Open; stress_check.py).
Electrode offsets (--shifts) as zscore_sweep.py: raw-EMG rotation with the integer start-up alignment estimated from
block 0 (the non-causal version; the same for every condition).

Writes results/leaf_sweep.csv (per subject / seed / shift / stream / condition / block), leaf_sweep_summary.csv
(blocks 1..10, subjects with seeds averaged, paired t CI) and leaf_sweep_leaves.csv (reachable leaves per model,
for the RAM of the counters).
Usage (in the container): python src/leaf_sweep.py [--shifts 0 0.5] [--jobs 19]
"""
import argparse
import copy
import os
import sys
import time

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as P  # noqa: E402
import rf_size  # noqa: E402
import selfcal_sweep as S  # noqa: E402
import shift_sweep as SH  # noqa: E402
import zscore_sweep as ZW  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
N, DEPTH, PREC, BUF, MLN = SH.N, SH.DEPTH, SH.PREC, SH.BUF, SH.MLN
N_PRE = N // 2
N_APP = N - N_PRE
N_UPD = int(round(S.REPLACE_FRAC * N_APP))
K = 6
A_Z = 0.3
MIN_WIN = 5
REST2 = (5, 2, 4)
ANCHOR_WIN = 10                     # windows per trial
LEAF_GRID = [(tr, w0, d) for tr in ('app', 'all') for w0 in (1, 4, 16) for d in (1.0, 0.5)]
DEFAULT = ('all', 4, 1.0)


def lname(tr, w0, d):
    return f'L{tr}_w{w0}_d{d:g}'


# second round (after the first results): the cued start-up sequence as TRAINING signal instead of as a judge, and a
# one-byte-per-leaf version of the refresh. All on all 100 trees, with the z-score update.
#   LA_a<a>      leaf refresh (w0 4, no decay) + every labelled anchor window adds a to its true class in its leaves,
#                at the start of the block (before the block is classified)
#   LAonly_a<a>  anchor counts only, no pseudo-labels (what the labels alone give without retraining)
#   ..._za       the z-score is first moved towards the anchor's statistics (same rule, a = 0.3; the anchor is
#                class-balanced by construction)
#   M_w<w0>      one byte per leaf (label + confidence 0..31), streaming, no block, no guard, no class weights:
#                pseudo-label == leaf label -> confidence + 1, else - 1; below 0 the leaf takes the pseudo-label
#   MA_w<w0>_a<a>  M + every labelled anchor window applied a times
#   B_w<w0>      two bytes per leaf, streaming, no block, no guard, no class weights: a challenger class and a signed
#                margin = (windows pseudo-labelled challenger) - (windows pseudo-labelled as the one-shot label),
#                clamped to +-127. The leaf answers the challenger while margin > w0, otherwise its one-shot label,
#                so the one-shot label is never forgotten. A third class takes the challenger's place only while
#                margin <= 0. (M failed in the first test: runs of 10 windows of one gesture flip leaves back and
#                forth, since M keeps no memory of the one-shot label.)
#   BA_w<w0>_a<a>  B + every labelled anchor window applied a times
#   ..._k<k>     counters only on the 50 appended trees + the first k pre-trained trees (RAM knob; default all 100)
CMAX = 31
MMAX = 127
NEW = {'LA_a2': dict(kind='cnt', anc=2, pseudo=True, za=False), 'LA_a8': dict(kind='cnt', anc=8, pseudo=True, za=False),
       'LA_a8_za': dict(kind='cnt', anc=8, pseudo=True, za=True),
       'LAonly_a8': dict(kind='cnt', anc=8, pseudo=False, za=False),
       'LAonly_a8_za': dict(kind='cnt', anc=8, pseudo=False, za=True),
       'M_w4': dict(kind='byte', w0=4, anc=0, za=False), 'M_w16': dict(kind='byte', w0=16, anc=0, za=False),
       'MA_w4_a4': dict(kind='byte', w0=4, anc=4, za=False), 'MA_w16_a4': dict(kind='byte', w0=16, anc=4, za=False),
       'MA_w16_a4_za': dict(kind='byte', w0=16, anc=4, za=True),
       'LA_a8_za_k0': dict(kind='cnt', anc=8, pseudo=True, za=True, k=0),
       'LA_a8_za_k10': dict(kind='cnt', anc=8, pseudo=True, za=True, k=10),
       'LA_a8_za_k25': dict(kind='cnt', anc=8, pseudo=True, za=True, k=25),
       'LAonly_a8_za_k0': dict(kind='cnt', anc=8, pseudo=False, za=True, k=0),
       'LAonly_a8_za_k10': dict(kind='cnt', anc=8, pseudo=False, za=True, k=10),
       'B_w4': dict(kind='two', w0=4, anc=0, za=False), 'B_w16': dict(kind='two', w0=16, anc=0, za=False),
       'BA_w4_a4': dict(kind='two', w0=4, anc=4, za=False), 'BA_w16_a4': dict(kind='two', w0=16, anc=4, za=False),
       'BA_w4_a4_za': dict(kind='two', w0=4, anc=4, za=True), 'BA_w16_a4_za': dict(kind='two', w0=16, anc=4, za=True)}
CONDS = (['F', 'Z', 'A'] + [lname(*g) for g in LEAF_GRID] + [lname(*DEFAULT) + '_noz', lname(*DEFAULT) + '_nog', 'R']
         + list(NEW) + ['Rcum'])


def thr_q(mdl):
    return [P.quantize(t) for t in mdl['threshold']]


def leaves(mdl, thr, X):
    """leaf node id of every window in every tree (list of n-vectors); same routing as pipeline.predict int16"""
    Xp = P.quantize(X)
    n = len(Xp)
    rows = np.arange(n)
    out = []
    for left, right, feat, t in zip(mdl['left'], mdl['right'], mdl['feature'], thr):
        node = np.zeros(n, dtype=np.int64)
        active = left[node] > 0
        while active.any():
            idx = rows[active]
            nd = node[idx]
            node[idx] = np.where(Xp[idx, feat[nd]] < t[nd], left[nd], right[nd])
            active[idx] = left[node[idx]] > 0
        out.append(node)
    return out


def n_reachable_leaves(left, right):
    stack, n = [0], 0
    while stack:
        i = stack.pop()
        if left[i] > 0:
            stack += [int(left[i]), int(right[i])]
        else:
            n += 1
    return n


def vote(nodes, labs):
    v = np.zeros((len(nodes[0]), K), dtype=np.int32)
    rows = np.arange(len(nodes[0]))
    for node, lab in zip(nodes, labs):
        v[rows, lab[node]] += 1
    return np.argmax(v, axis=1), v


def guard_ok(pred):
    return np.sum(np.bincount(pred, minlength=K) >= MIN_WIN) >= 5


def anchor_split(y):
    """indices of the first trial of every gesture (the cued start-up sequence) and of the rest of the block"""
    a = []
    for c in range(K):
        i = int(np.argmax(y == c))
        assert np.all(y[i:i + ANCHOR_WIN] == c)
        a.extend(range(i, i + ANCHOR_WIN))
    a = np.array(a)
    return a, np.setdiff1d(np.arange(len(y)), a)


def one_shot(Xc, yc, pre):
    pruned = P.prune(rf_size.truncate_depth(copy.deepcopy(pre), DEPTH), Xc, yc)
    app = P.train_rf(Xc, yc, N_APP, DEPTH, None)
    return emg_functions.append(P.subset(pruned, range(N_PRE)), app)


def run_static(cond, mdl, Xc_raw, blocks):
    """F, Z and the leaf-refresh conditions (fixed tree structure). blocks: (X_raw anchor, y anchor, X_raw use, y use)"""
    mu0, var0 = Xc_raw.mean(0), Xc_raw.var(0)
    mu, var = mu0.copy(), var0.copy()
    thr = thr_q(mdl)
    lab0 = P.leaf_labels(mdl)
    lab = [x.copy() for x in lab0]
    leaf = cond.startswith('L')
    zs = cond != 'F' and not cond.endswith('_noz')
    guard = not cond.endswith('_nog')
    if leaf:
        part = cond.split('_')
        tr, w0, d = part[0][1:], float(part[1][1:]), float(part[2][1:])
        trees = range(N_PRE, N) if tr == 'app' else range(N)
        cnt = {t: np.zeros((len(lab0[t]), K)) for t in trees}
    rows = []
    for b, (Xa, ya, Xu, yu) in enumerate(blocks):
        sd = np.sqrt(var)
        nodes = leaves(mdl, thr, (Xu - mu) / sd)
        pred, _ = vote(nodes, lab)
        # anchor: adapted state vs day-1 state on the cued sequence, then the block with the better one
        if len(ya):
            pa, _ = vote(leaves(mdl, thr, (Xa - mu) / sd), lab)
            p0a, _ = vote(leaves(mdl, thr, (Xa - mu0) / np.sqrt(var0)), lab0)
            acc_a, acc_a0 = np.mean(pa == ya), np.mean(p0a == ya)
        else:                                                        # no cued sequence before this block
            acc_a = acc_a0 = np.nan
        if not acc_a < acc_a0:
            pred_sel = pred
        else:
            pred_sel, _ = vote(leaves(mdl, thr, (Xu - mu0) / np.sqrt(var0)), lab0)
        rows.append(dict(block=b, acc=np.mean(pred == yu), acc_sel=np.mean(pred_sel == yu), anc=acc_a, anc0=acc_a0,
                         n=len(yu), flipped=sum(int(np.sum(lab[t] != lab0[t])) for t in range(N)) if leaf else 0))
        if guard and not guard_ok(pred):
            continue
        if leaf:
            cls = np.bincount(pred, minlength=K)
            w = len(pred) / (np.sum(cls > 0) * cls[pred])            # class-balanced: every predicted class weighs the same
            for t in trees:
                cnt[t] *= d
                np.add.at(cnt[t], (nodes[t], pred), w)
                score = cnt[t].copy()
                score[np.arange(len(lab0[t])), lab0[t]] += w0
                lab[t] = np.argmax(score, axis=1)
        if zs:
            st = ZW.balanced_stats(Xu, pred)
            if st is not None:
                mu = (1 - A_Z) * mu + A_Z * st[0]
                var = (1 - A_Z) * var + A_Z * st[1]
    return rows


def run_anchor(cond, mdl, Xc_raw, blocks):
    """second-round conditions (NEW): anchor labels as training signal; counters (cnt) or one byte per leaf (byte)"""
    p = NEW[cond]
    mu, var = Xc_raw.mean(0), Xc_raw.var(0)
    thr = thr_q(mdl)
    lab0 = P.leaf_labels(mdl)
    off = np.concatenate([[0], np.cumsum([len(x) for x in lab0])])[:-1]      # global leaf index = off[tree] + node
    lab = np.concatenate(lab0).copy()
    base = lab.copy()
    sel = np.r_[0:p.get('k', N_PRE), N_PRE:N]                                # trees with counters
    if p['kind'] == 'cnt':
        cnt = np.zeros((len(lab), K))
    elif p['kind'] == 'byte':
        conf = np.full(len(lab), p['w0'], dtype=np.int64)
    else:
        ch, mar = base.copy(), np.zeros(len(lab), dtype=np.int64)

    def route(X):
        return np.stack(leaves(mdl, thr, (X - mu) / np.sqrt(var)), axis=1) + off     # n x trees

    def relabel():
        score = cnt.copy()
        score[np.arange(len(base)), base] += 4.0                                     # w0 = 4
        lab[:] = np.argmax(score, axis=1)

    def byte_step(g, c):
        same = lab[g] == c
        conf[g] = np.where(same, np.minimum(conf[g] + 1, CMAX), conf[g] - 1)
        flip = g[conf[g] < 0]
        lab[flip], conf[flip] = c, 0

    def two_step(g, c):
        isb, isc = base[g] == c, ch[g] == c
        take = g[~isb & ~isc & (mar[g] <= 0)]                                        # third class, challenger not ahead
        ch[take] = c
        mar[g] = np.clip(mar[g] + np.where(isb, -1, np.where(ch[g] == c, 1, 0)), -MMAX, MMAX)
        lab[g] = np.where(mar[g] > p['w0'], ch[g], base[g])

    step = two_step if p['kind'] == 'two' else byte_step
    rows = []
    for b, (Xa, ya, Xu, yu) in enumerate(blocks):
        if p['za'] and len(ya):
            st = ZW.balanced_stats(Xa, ya)
            mu = (1 - A_Z) * mu + A_Z * st[0]
            var = (1 - A_Z) * var + A_Z * st[1]
        Ga = route(Xa) if len(ya) else np.zeros((0, N), dtype=np.int64)
        if p['kind'] == 'cnt':
            np.add.at(cnt, (Ga[:, sel], ya[:, None]), float(p['anc']))
            relabel()
        else:
            for _ in range(p['anc']):
                for g, c in zip(Ga, ya):
                    step(g, c)
        G = route(Xu)
        if p['kind'] == 'cnt':
            pred = np.array([np.argmax(np.bincount(lab[g], minlength=K)) for g in G])
            if p['pseudo'] and guard_ok(pred):
                cls = np.bincount(pred, minlength=K)
                w = len(pred) / (np.sum(cls > 0) * cls[pred])
                np.add.at(cnt, (G[:, sel], pred[:, None]), w[:, None] * np.ones((1, len(sel))))
                relabel()
        else:
            pred = np.zeros(len(G), dtype=np.int64)
            for i, g in enumerate(G):                                                # streaming: classify, then update
                pred[i] = np.argmax(np.bincount(lab[g], minlength=K))
                step(g, pred[i])
        rows.append(dict(block=b, acc=np.mean(pred == yu), acc_sel=np.mean(pred == yu), anc=np.nan, anc0=np.nan,
                         n=len(yu), flipped=int(np.sum(lab != base))))
        if p['kind'] != 'cnt' or guard_ok(pred):
            st = ZW.balanced_stats(Xu, pred)
            if st is not None:
                mu = (1 - A_Z) * mu + A_Z * st[0]
                var = (1 - A_Z) * var + A_Z * st[1]
    return rows


def run_retrain(mdl_os, Xc_raw, yc, blocks):
    """A: zscore_sweep.run with zs = bal0.3, embed = 'none', plus the cls5 guard and the anchor selection"""
    mu0, var0 = Xc_raw.mean(0), Xc_raw.var(0)
    mu, var = mu0.copy(), var0.copy()
    Xc = (Xc_raw - mu0) / np.sqrt(var0)
    mdl = copy.deepcopy(mdl_os)
    feat_buf, lab_buf = np.zeros((0, Xc.shape[1])), np.zeros((0,))
    rows = []
    for b, (Xa, ya, Xu, yu) in enumerate(blocks):
        X = (Xu - mu) / np.sqrt(var)
        pred = P.predict(mdl, X, PREC)
        acc_a = acc_a0 = np.nan
        if len(ya):
            pa = P.predict(mdl, (Xa - mu) / np.sqrt(var), PREC)
            p0a = P.predict(mdl_os, (Xa - mu0) / np.sqrt(var0), PREC)
            acc_a, acc_a0 = np.mean(pa == ya), np.mean(p0a == ya)
        pred_sel = pred if not acc_a < acc_a0 else P.predict(mdl_os, (Xu - mu0) / np.sqrt(var0), PREC)
        rows.append(dict(block=b, acc=np.mean(pred == yu), acc_sel=np.mean(pred_sel == yu), anc=acc_a, anc0=acc_a0,
                         n=len(yu), flipped=0))
        if not guard_ok(pred):
            continue
        feat_buf, lab_buf = emg_functions.buffer_update(BUF, feat_buf, lab_buf, S.q16(X), pred)
        feat_sel, lab_pseudo, lab_buf = emg_functions.manifold_clustering(
            feat_buf, list(S.LABELS), S.MIN_SAMPLE_CLASS, mdl_os, 'kmeans', embedding=None)
        if len(lab_pseudo) >= 10:
            new = P.train_rf(np.concatenate([feat_sel, S.q16(Xc)]), np.concatenate([lab_pseudo, yc]), N_UPD, DEPTH,
                             None, MLN)
            keep = np.concatenate([np.arange(N_PRE), np.random.permutation(range(N_PRE, N))[:N_APP - N_UPD]])
            mdl = emg_functions.replace(mdl, new, keep)
        st = ZW.balanced_stats(Xu, pred)
        if st is not None:
            mu = (1 - A_Z) * mu + A_Z * st[0]
            var = (1 - A_Z) * var + A_Z * st[1]
    return rows


def run_recal(pre, blocks, cum=None):
    """R: a new one-shot calibration from the anchor of every block. Rcum (cum = day-1 calibration, raw): the same,
    trained on the day-1 calibration and ALL anchors so far, each normalised with its own statistics - the
    retraining counterpart of the anchor counters, which also accumulate over the sessions"""
    rows = []
    pool = [] if cum is None else [((cum[0] - cum[0].mean(0)) / cum[0].std(0), cum[1])]
    for b, (Xa, ya, Xu, yu) in enumerate(blocks):
        if not len(ya):                                              # no new anchor: keep the last model
            acc = np.mean(P.predict(mdl, (Xu - mu) / sd, PREC) == yu)
            rows.append(dict(block=b, acc=acc, acc_sel=acc, anc=np.nan, anc0=np.nan, n=len(yu), flipped=0))
            continue
        mu, sd = Xa.mean(0), Xa.std(0)
        if cum is None:
            mdl = one_shot((Xa - mu) / sd, ya, pre)
        else:
            pool.append(((Xa - mu) / sd, ya))
            mdl = one_shot(np.concatenate([x for x, _ in pool]), np.concatenate([y for _, y in pool]), pre)
        acc = np.mean(P.predict(mdl, (Xu - mu) / sd, PREC) == yu)
        rows.append(dict(block=b, acc=acc, acc_sel=acc, anc=np.nan, anc0=np.nan, n=len(yu), flipped=0))
    return rows


def run(subject, seed, shift, conds):
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), PREC), None)
    np.random.seed(seed * 1000 + subject)
    Xc_raw, yc, blocks, k_est = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    mu, sd = Xc_raw.mean(0), Xc_raw.std(0)
    pre = P.load_pretrain(S.DATASETS['arm_position'][0])
    mdl_os = one_shot((Xc_raw - mu) / sd, yc, pre)
    X0 = (blocks[0][0] - mu) / sd                                    # routing check against pipeline.predict
    assert np.array_equal(vote(leaves(mdl_os, thr_q(mdl_os), X0), P.leaf_labels(mdl_os))[0], P.predict(mdl_os, X0, PREC))
    n_leaf = [n_reachable_leaves(l, r) for l, r in zip(mdl_os['left'], mdl_os['right'])]
    info = dict(subject=subject, seed=seed, shift=shift, leaves_pre=sum(n_leaf[:N_PRE]), leaves_app=sum(n_leaf[N_PRE:]),
                leaves_pre_max=max(n_leaf[:N_PRE]), leaves_app_max=max(n_leaf[N_PRE:]))
    out = []
    for stream in ('base', 'rest2'):
        blk = []
        for b, (X, y) in enumerate(blocks):
            y = y.astype(np.int64)
            a, u = anchor_split(y)
            if stream == 'rest2' and b > 0:
                u = u[np.isin(y[u], REST2)]
            blk.append((X[a], y[a], X[u], y[u]))
        for cond in conds:
            np.random.seed(seed * 1000 + subject + 1)                # same RNG state for every condition
            if cond == 'A':
                rows = run_retrain(mdl_os, Xc_raw, yc, blk)
            elif cond == 'R':
                rows = run_recal(pre, blk)
            elif cond == 'Rcum':
                rows = run_recal(pre, blk, (Xc_raw, yc))
            elif cond in NEW:
                rows = run_anchor(cond, mdl_os, Xc_raw, blk)
            else:
                rows = run_static(cond, mdl_os, Xc_raw, blk)
            out += [dict(subject=subject, seed=seed, shift=shift, stream=stream, cond=cond, k_est=k_est, **r)
                    for r in rows]
    return out, info


def ci(d):
    m, se = d.mean(), d.std(ddof=1) / np.sqrt(len(d))
    h = stats.t.ppf(0.975, len(d) - 1) * se
    return m, m - h, m + h


def summarize(acc):
    a = acc[acc.block >= 1]
    ps = a.groupby(['shift', 'stream', 'cond', 'subject'])[['acc', 'acc_sel']].mean() * 100
    out = []
    for (sh, st), g in ps.groupby(level=[0, 1]):
        g = g.droplevel([0, 1])
        f, z = g.xs('F').acc, g.xs('Z').acc
        for cond in [c for c in CONDS if c in g.index.get_level_values('cond')]:
            cur = g.xs(cond)
            row = dict(shift=sh, stream=st, cond=cond, n=len(cur), acc=cur.acc.mean(), acc_sel=cur.acc_sel.mean())
            for name, x, ref in [('vsF', cur.acc, f), ('vsZ', cur.acc, z), ('sel_vsF', cur.acc_sel, f)]:
                d = x - ref
                row[name], row[name + '_lo'], row[name + '_hi'] = ci(d) if len(d) > 1 and np.any(d != 0) else (d.mean(),) * 3
                row[name + '_worst'] = d.min()
                row[name + '_better'], row[name + '_worse'] = int((d > 0).sum()), int((d < 0).sum())
            out.append(row)
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--shifts', type=float, nargs='+', default=[0, 0.5])
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--subjects', type=int, nargs='+', default=list(range(20)))
    ap.add_argument('--conds', nargs='+', default=CONDS)
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--suffix', default='')
    ap.add_argument('--add', action='store_true', help='add --conds to the existing leaf_sweep.csv (runs are seeded per condition)')
    args = ap.parse_args()
    t0 = time.time()
    import check_features_c as FC
    FC.lib()
    Parallel(n_jobs=args.jobs)(delayed(SH.prepare)(s, sh) for sh in args.shifts for s in args.subjects)
    tasks = [(s, seed, sh, args.conds) for sh in args.shifts for seed in args.seeds for s in args.subjects]
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(run)(*t) for t in tasks)
    acc = pd.DataFrame([r for rows, _ in res for r in rows])
    path = os.path.join(OUT, f'leaf_sweep{args.suffix}.csv')
    if args.add and os.path.exists(path):                                # keep the conditions already there
        old = pd.read_csv(path)
        acc = pd.concat([old[~old.cond.isin(args.conds)], acc], ignore_index=True)
    acc.to_csv(os.path.join(OUT, f'leaf_sweep{args.suffix}.csv'), index=False, float_format='%.4f')
    pd.DataFrame([i for _, i in res]).to_csv(os.path.join(OUT, f'leaf_sweep_leaves{args.suffix}.csv'), index=False)
    s = summarize(acc)
    s.to_csv(os.path.join(OUT, f'leaf_sweep_summary{args.suffix}.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 250)
    cols = ['shift', 'stream', 'cond', 'acc', 'vsF', 'vsF_lo', 'vsF_hi', 'vsF_worst', 'vsZ', 'vsZ_lo', 'vsZ_hi',
            'acc_sel', 'sel_vsF', 'sel_vsF_worst']
    print(s[cols].round(2).to_string(index=False))
    print(f'took {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
