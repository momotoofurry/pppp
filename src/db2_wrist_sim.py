"""NinaPro DB2 Exercise B (file S<s>_E1_A1.mat) as a stand-in for the 9-gesture self-test (report 35.46, 2026-11-17):
how accurate are 9 / 7 / 5 gestures with 4 sensors and one short cued pass?

DB2: Delsys Trigno, 2 kHz, 12 electrodes: 1-8 equally spaced around the forearm at the radio-humeral joint, 9 on the
flexor digitorum superficialis, 10 on the extensor digitorum, 11-12 biceps / triceps. Each movement 6 repetitions of
5 s with 3 s rest. Labels: restimulus / rerepetition (relabelled).
Gesture mapping (Exercise B movement -> self-test gesture): 14 wrist extension -> WristExt, 13 wrist flexion ->
WristFlex, 15 radial deviation -> RadialDev, 16 ulnar deviation -> UlnarDev, 7 pointing index -> Point, 1 thumb up ->
ThumbUp, 5 abduction of all fingers -> HandOpen, 6 fist -> Fist, 0 -> Rest.
Sets: S9 all, S7 without Point / ThumbUp, S5 the 4 wrist directions + Rest (as selftest9_analysis).

Sensor configurations, each fed as 8 channels to the board's feature code (features.c via check_features_c):
  4ch   FDS (9) + EDC (10) + 2 ring electrodes, repeated twice (as the self-test's slots 16:15:11:5:16:15:11:5). The
        ring's orientation is not given, so all 28 ring pairs are run; reported: median over pairs (typical) and the
        best pair (optimistic, chosen on the test data).
  ring8 the 8 ring electrodes (reference: the original 8-sensor plan).
Model as on the board: cued pass = repetitions 1-2 of each gesture (DB2's relabelled holds last only 2-6.5 s, so one
repetition gives fewer than the self-test's 30 windows), windows from 0.5 s after onset, at most 30 (= one 4 s cue);
Rest = the first 30 rest windows at least 1 s from any movement. z-score from the cued windows, Q5.10, OAS LDA.
Test = repetitions 3-6, windows from 0.5 s after onset; Rest = up to 150 later rest windows >= 1 s from movements.
Measure: balanced accuracy (mean recall over the set's gestures), %.
Caveat: the test repetitions follow the cued pass within minutes on the same donning (no re-donning, no posture change),
so this is closer to the self-test's P0 than to a later day.

usage: python src/db2_wrist_sim.py --dir /db2 --subjects 1-10 [--out results/db2_wrist]
"""
import argparse
import itertools
import os
import sys

import numpy as np
import scipy.io as sio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lda_robust as LR  # noqa: E402
import selftest_analysis as SA  # noqa: E402

GESTURES = ['WristExt', 'WristFlex', 'RadialDev', 'UlnarDev', 'Point', 'ThumbUp', 'HandOpen', 'Fist', 'Rest']
DB2_MOVE = [14, 13, 15, 16, 7, 1, 5, 6, 0]          # Exercise B movement of each gesture
SETS = {'S9': list(range(9)), 'S7': [0, 1, 2, 3, 6, 7, 8], 'S5': [0, 1, 2, 3, 8]}
ORDER = ['S9', 'S7', 'S5']
FS, WIN, STEP = SA.FS, SA.WIN, SA.STEP
NF = 10                                              # features per channel (features.c), feature-major f * 8 + ch
FDS, EDC = 8, 9


def find_mat(root, s):
    for dp, _, fs in os.walk(os.path.join(root, f's{s}')):
        for f in fs:
            if f.upper() == f'S{s}_E1_A1.MAT':
                return os.path.join(dp, f)
    raise FileNotFoundError(f'S{s}_E1_A1.mat under {root}/s{s}')


def channel_features(emg):
    """10 board features per window for each of the 12 electrodes: (nw, 12, 10)"""
    out = []
    for block in (list(range(8)), [8, 9, 10, 11, 8, 9, 10, 11]):
        F = SA.features(emg[:, block].astype(np.float32))
        out.append(np.stack([F[:, [f * 8 + p for f in range(NF)]] for p in range(8)], axis=1))
    return np.concatenate([out[0], out[1][:, :4]], axis=1)


def window_labels(lab, rep, nw):
    st = np.arange(nw) * STEP
    a, b = lab[st], lab[st + WIN - 1]
    ra = rep[st]
    same = a == b
    # time since the label at the window start began, and distance to the nearest movement sample
    change = np.flatnonzero(np.diff(lab) != 0) + 1
    onset = np.zeros(len(lab), int)
    if len(change):
        idx = np.searchsorted(change, np.arange(len(lab)), side='right') - 1
        onset = np.where(idx >= 0, change[np.maximum(idx, 0)], 0)
    since = (st - onset[st]) / FS
    move = lab != 0
    nearest = np.full(len(lab), np.inf)
    mi = np.flatnonzero(move)
    if len(mi):
        pos = np.searchsorted(mi, np.arange(len(lab)))
        lo = mi[np.clip(pos - 1, 0, len(mi) - 1)]
        hi = mi[np.clip(pos, 0, len(mi) - 1)]
        nearest = np.minimum(np.abs(np.arange(len(lab)) - lo), np.abs(hi - np.arange(len(lab)))) / FS
    rest_ok = (a == 0) & same & (np.minimum(nearest[st], nearest[st + WIN - 1]) >= 1.0)
    return a, ra, same, since, rest_ok


def split_standard(a, ra, same, since, rest_ok):
    """sanity reference, the usual NinaPro split: train on all windows of repetitions 1, 3, 4, 6, test on 2 and 5"""
    cal, test = {}, {}
    rest = np.flatnonzero(rest_ok)
    half = np.arange(len(rest)) % 3 == 1
    for g, mv in enumerate(DB2_MOVE):
        if mv == 0:
            cal[g], test[g] = rest[~half], rest[half]
        else:
            ok = (a == mv) & same & (since >= 0.5)
            cal[g] = np.flatnonzero(ok & np.isin(ra, [1, 3, 4, 6]))
            test[g] = np.flatnonzero(ok & np.isin(ra, [2, 5]))
    return cal, test


def split(a, ra, same, since, rest_ok):
    cal, test = {}, {}
    for g, mv in enumerate(DB2_MOVE):
        if mv == 0:
            idx = np.flatnonzero(rest_ok)
            cal[g] = idx[:30]
            later = idx[30:]
            test[g] = later[np.linspace(0, len(later) - 1, min(150, len(later))).astype(int)] if len(later) else later
        else:
            ok = (a == mv) & same & (since >= 0.5)
            cal[g] = np.flatnonzero(ok & (ra <= 2) & (ra >= 1))[:30]
            test[g] = np.flatnonzero(ok & (ra >= 3))
    return cal, test


def fit_eval(X, cal, test, classes):
    rows = np.concatenate([cal[c] for c in classes])
    lab = np.concatenate([np.full(len(cal[c]), c) for c in classes])
    Xc = X[rows]
    mu, sd = Xc.mean(0), Xc.std(0)
    inv = np.where(sd > 0, 1.0 / np.where(sd > 0, sd, 1.0), 0.0)
    Zq = SA.q16((Xc - mu) * inv)
    K = len(classes)
    idx = np.array([classes.index(c) for c in lab])
    n = np.bincount(idx, minlength=K).astype(float)
    s = np.zeros((K, Zq.shape[1]))
    np.add.at(s, idx, Zq)
    m = s / n[:, None]
    N = n.sum()
    w, b = LR.oas_solve((Zq.T @ Zq - (m.T * n) @ m) / N, N, m)
    rec = []
    for c in classes:
        if len(test[c]) == 0:
            continue
        pr = np.array(classes)[np.argmax(SA.q16((X[test[c]] - mu) * inv) @ w.T + b, 1)]
        rec.append(np.mean(pr == c))
    return 100 * np.mean(rec)


def config_matrix(CF, chans):
    return np.concatenate([CF[:, chans, f] for f in range(NF)], axis=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--subjects', default='1-10')
    ap.add_argument('--out', default=None)
    ap.add_argument('--split', choices=['short', 'standard'], default='short',
                    help='short = the self-test cued pass (default); standard = reps 1,3,4,6 / 2,5 (sanity reference)')
    args = ap.parse_args()
    a_, b_ = (args.subjects.split('-') + [None])[:2]
    subs = list(range(int(a_), int(b_ or a_) + 1))
    lines = []

    def p(s=''):
        print(s, flush=True)
        lines.append(s)

    pairs = list(itertools.combinations(range(8), 2))
    res = {k: {s: [] for s in ORDER} for k in ('4ch_median', '4ch_best', 'ring8')}
    p('subject  set   4ch median   4ch best (pair)   ring8   chance   cued windows per gesture')
    for subj in subs:
        d = sio.loadmat(find_mat(args.dir, subj))
        emg = d['emg'].astype(np.float64)
        lab = (d['restimulus'] if 'restimulus' in d else d['stimulus']).ravel().astype(int)
        rep = (d['rerepetition'] if 'rerepetition' in d else d['repetition']).ravel().astype(int)
        CF = channel_features(emg)
        nw = CF.shape[0]
        cal, test = (split if args.split == 'short' else split_standard)(*window_labels(lab, rep, nw))
        counts = [len(cal[g]) for g in range(9)]
        for sname in ORDER:
            cls = SETS[sname]
            accs = [fit_eval(config_matrix(CF, [FDS, EDC, i, j] * 2), cal, test, cls) for i, j in pairs]
            r8 = fit_eval(config_matrix(CF, list(range(8))), cal, test, cls)
            best = int(np.argmax(accs))
            res['4ch_median'][sname].append(np.median(accs))
            res['4ch_best'][sname].append(accs[best])
            res['ring8'][sname].append(r8)
            p(f'{subj:7d}  {sname}  {np.median(accs):10.1f}   {accs[best]:8.1f} ({pairs[best][0] + 1},{pairs[best][1] + 1})   '
              f'{r8:6.1f}   {100 / len(cls):5.1f}   {counts if sname == "S9" else ""}')
    p('\nmean (SD) over subjects, balanced accuracy %')
    for sname in ORDER:
        p(f'{sname}: ' + '   '.join(f'{k} {np.mean(res[k][sname]):5.1f} ({np.std(res[k][sname]):4.1f})'
                                   for k in ('4ch_median', '4ch_best', 'ring8')))
    p(f'\nsubjects reaching 85 % (4ch median): ' + ', '.join(
        f"{s} {sum(v >= 85 for v in res['4ch_median'][s])}/{len(subs)}" for s in ORDER))
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, f'db2_wrist_sim_{args.split}.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
