"""Accuracy vs latency of the board's real-time decision (report 35.54, 2026-11-18).

Why: in the day-1 procedure test (6 gestures, 4 sensors) the median time from the cue to the board's command was
1.17 s. For arm control the latency has to come down. Two questions:

Part 1  --day1 <dir> <name>: where do the 1.17 s go? For every task trial (TaskScreen trial_on = cue shown,
        trial_end latency_ms = first command) the EMG onset is detected offline in the recording (onset() below):
        reaction = onset - cue (the user), system = command - onset (windowing + k agreement + transport + latch).

Part 2  --oz <dir>: offline sweep on Ozdemir 2022 (4 sensors on targeted muscles, 40 participants; the closest public
        match to the self-test placement; ozdemir_sim.py), sets S7 and S5. Per participant and setting:
          features   the board's features.c, compiled with window W and step S (FE_WIN / FE_STEP; the 4 channels fed
                     twice as 8, as the self-test's repeated slots)
          model      the board's model (selftest9_analysis.Model) on two cued passes = cycles 1-2, windows wholly in
                     1.0-4.2 s after the scheduled start (about one 4 s cue each, independent of S)
          stream     cycles 4-5 replayed as one continuous stream through the board's decision (decision.c: margin
                     threshold m on top - second LDA score, k agreeing accepted windows, latch; the same class fires
                     again only after another class, Rest included, was established). Optional fast start: a window
                     with margin >= hi establishes its class at once (k = 1), otherwise k.
          onset      per trial from the raw EMG (onset() below); trials without a clear onset are left out
        Metrics (median over participants of each participant's value):
          first_ok   % of in-set gesture trials whose first command (fired from onset - 0.2 s to offset + 1 s) is right
          miss       % of those trials with no command
          start_ms   onset -> first command, trials whose first command is right
          stop_ms    offset -> Rest established (= the arm would stop), trials with a command
          wrong_tr   wrong commands per trial (incl. ones at the return to rest)
          false_min  commands per minute during rest (Rest trials and gaps, away from any movement)
        A command is available at the end of its window; MCU processing (~2 ms) and transport are not included.

Part 3  --self <dir> <name>: the same sweep on one 9-gesture self-test recording (T00_d<day>_G), sets S9 / S7 / S5:
        model from that day's cued passes (windows wholly 1.0 s to cal_s after each `cal g`, as the board after its 9
        warm-up windows; both passes), stream = the task segments (each one continuous), trials = TaskScreen trial_on
        -> the target command's gesture, onset / offset from the recording. Same metrics, one participant.

Onset / offset (offline ground truth, not causal): 20 Hz high-pass, 50 ms moving RMS per channel; baseline B = median
in the second before the cue, peak P = 95th percentile 1-4 s after it; channel with the largest P / B; threshold
B + 0.2 (P - B); onset = first time from cue - 1 s on that stays above for 50 ms; offset = first time after cue + 4 s
that stays below for 100 ms. Trials with P / B < 2 have no clear onset.

usage: python src/latency_sweep.py --oz /oz [--subjects 1-40] [--out results/latency]
       python src/latency_sweep.py --self /d T00_d1_G [--cal-s 4] [--out results/latency]
       python src/latency_sweep.py --day1 /d T00_d1_A [--out results/latency]
"""
import argparse
import ctypes
import itertools
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import scipy.io as sio
from joblib import Parallel, delayed
from scipy.signal import butter, sosfiltfilt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as P  # noqa: E402
import selftest9_analysis as S9  # noqa: E402

FS = 2000
REST = S9.REST
OZ = {1: 0, 2: 1, 4: 2, 3: 3, 6: 6, 5: 7, 0: 8}          # Ozdemir gesture -> self-test class (ozdemir_sim.py)
CYCLE0 = [4, 138, 272, 406, 540]
SETS = {'S7': S9.SETS['S7'], 'S5': S9.SETS['S5']}
WINS = [200, 300, 400, 500]                              # samples: 100, 150, 200, 250 ms
STEPS = [100, 200]                                       # 50, 100 ms
KS = [1, 2, 3, 4, 5]
MS = [0.0, 0.5, 1.0, 2.0]
FAST = [(k, hi) for k in (2, 3) for hi in (2.0, 4.0, 6.0)]
BASE = (400, 200, 3, 0.0, None)                          # the board now: 200 ms / 100 ms, k 3, margin 0
BUILD = os.path.join(P.ROOT, 'build', 'latency')


# ---------------------------------------------------------------- features.c with another window / step
_libs = {}


def fe_build(win, step):
    d = os.path.join(BUILD, f'fe_{win}_{step}')
    so = os.path.join(d, 'libfe.so')
    if not os.path.exists(so):
        os.makedirs(d, exist_ok=True)
        src = os.path.join(P.ROOT, 'src', 'c')
        h = open(os.path.join(src, 'features.h'), encoding='utf-8').read()
        h = h.replace('#define FE_WIN 400', f'#define FE_WIN {win}').replace('#define FE_STEP 200', f'#define FE_STEP {step}')
        assert f'FE_WIN {win}' in h and f'FE_STEP {step}' in h and win <= 512
        open(os.path.join(d, 'features.h'), 'w', encoding='utf-8').write(h)
        open(os.path.join(d, 'features.c'), 'w', encoding='utf-8').write(
            open(os.path.join(src, 'features.c'), encoding='utf-8').read())
        subprocess.run(['gcc', '-O2', '-std=c99', '-fPIC', '-shared', '-o', so, os.path.join(d, 'features.c'), '-lm'],
                       check=True)
    return so


def fe_lib(win, step):
    key = (win, step)
    if key in _libs:
        return _libs[key]
    L = ctypes.CDLL(fe_build(win, step))
    L.fe_recording.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    L.fe_init()
    _libs[key] = L
    return L


def features(X8, win, step):
    """window i covers samples [i * step, i * step + win); returns (nw, 80)"""
    x = np.ascontiguousarray(X8.T.astype(np.float32))
    n = x.shape[1]
    nw = (n - win) // step + 1
    F = np.zeros((nw, 80), dtype=np.float32)
    assert fe_lib(win, step).fe_recording(x.ctypes.data, n, F.ctypes.data, nw) == nw
    return np.nan_to_num(F.astype(np.float64))


# ---------------------------------------------------------------- onset / offset
def envelope(X):
    sos = butter(4, 20, 'highpass', fs=FS, output='sos')
    y = sosfiltfilt(sos, X, axis=0)
    k = int(0.05 * FS)
    c = np.cumsum(np.vstack([np.zeros((1, y.shape[1])), y ** 2]), axis=0)
    ms = (c[k:] - c[:-k]) / k
    ms = np.vstack([np.repeat(ms[:1], k // 2, 0), ms, np.repeat(ms[-1:], k - k // 2, 0)])[:len(y)]
    return np.sqrt(ms)


def _first_run(mask, start, need):
    """first index >= start where mask stays true for need samples, or -1"""
    m = mask[start:].astype(np.int32)
    if len(m) < need:
        return -1
    c = np.convolve(m, np.ones(need, np.int32), 'valid')
    i = np.flatnonzero(c == need)
    return start + int(i[0]) if len(i) else -1


def onset(env, cue, t_end=None, peak=(1.0, 4.0)):
    """cue: sample index. Returns (onset, offset) sample indices or None"""
    n = len(env)
    b0, b1 = cue - FS, cue - int(0.05 * FS)
    p0, p1 = cue + int(peak[0] * FS), cue + int(peak[1] * FS)
    if b0 < 0 or p1 > n or p1 <= p0:
        return None
    B = np.median(env[b0:b1], axis=0)
    Pk = np.percentile(env[p0:p1], 95, axis=0)
    ratio = Pk / np.maximum(B, 1e-12)
    c = int(np.argmax(ratio))
    if ratio[c] < 2:
        return None
    thr = B[c] + 0.2 * (Pk[c] - B[c])
    on = _first_run(env[:, c] > thr, cue - FS, int(0.05 * FS))
    if on < 0 or on > cue + 3 * FS:
        return None
    off = _first_run(env[:, c] <= thr, max(on, cue + 4 * FS) if t_end is None else max(on, t_end), int(0.1 * FS))
    return on, (off if off >= 0 else None)


# ---------------------------------------------------------------- decision.c replay
def replay(pred, margin, k, m, hi):
    """established class per window (-1 none), as dc_step with all-or-nothing votes (+ optional fast start)"""
    n = len(pred)
    est = np.full(n, -1, np.int8)
    last, run, latched = -1, 0, -1
    for i in range(n):
        if margin[i] < m:
            last, run = -1, 0
            continue
        t = pred[i]
        if t == last:
            if run < k:
                run += 1
        else:
            last, run = t, 1
        need = 1 if (hi is not None and margin[i] >= hi) else k
        if run < need or t == latched:
            continue
        latched = t
        est[i] = t
    return est


def metrics(est, t_end, trials, rest_iv):
    """est: established class per window, t_end: window end (s). trials: (cls, on_s, off_s). rest_iv: [(a, b)] s"""
    fired = np.flatnonzero(est >= 0)
    ft, fc = t_end[fired], est[fired]
    first_ok = miss = 0
    start, stop, wrong = [], [], 0
    for cls, on, off in trials:
        sel = (ft >= on - 0.2) & (ft <= off + 1.0) & (fc != REST)
        cmds = fc[sel]
        wrong += int((cmds != cls).sum())
        if len(cmds) == 0:
            miss += 1
            continue
        if cmds[0] == cls:
            first_ok += 1
            start.append((ft[sel][0] - on) * 1000)
        r = (ft > off) & (fc == REST)
        if r.any():
            stop.append((ft[r][0] - off) * 1000)
    nt = len(trials)
    rest_s = sum(b - a for a, b in rest_iv)
    fals = sum(int(((ft >= a) & (ft < b) & (fc != REST)).sum()) for a, b in rest_iv)
    md = lambda v: float(np.median(v)) if len(v) else np.nan  # noqa: E731
    return dict(first_ok=100 * first_ok / nt, miss=100 * miss / nt, start_ms=md(start), stop_ms=md(stop),
                wrong_tr=wrong / nt, false_min=60 * fals / rest_s if rest_s else np.nan, n_trials=nt)


# ---------------------------------------------------------------- Part 2: Ozdemir
def settings():
    for win, step in itertools.product(WINS, STEPS):
        for k, m in itertools.product(KS, MS):
            yield win, step, k, m, None
        for k, hi in FAST:
            yield win, step, k, 0.0, hi


def oz_subject(path, subj):
    m = sio.loadmat(path)
    X = np.asarray(m['data'], dtype=np.float64)
    if X.shape[0] == 4:
        X = X.T
    env = envelope(X)
    X8 = (X[:, [0, 1, 2, 3, 0, 1, 2, 3]] * 1e-3)                  # mV -> V, as ozdemir_sim
    # trials of the test cycles 4-5 (all 10 Ozdemir gestures; the ones outside a set are masked out)
    tr = []
    for cyc in (3, 4):
        for og in range(10):
            t = CYCLE0[cyc] + 10 * og
            r = onset(env, int(t * FS)) if og != 0 else None
            tr.append((og, t, r))
    a_s, b_s = CYCLE0[3] - 2.0, CYCLE0[4] + 100.0
    rows = []
    stats = dict(no_onset=sum(1 for og, _, r in tr if og != 0 and r is None), react=[
        (r[0] / FS - t) * 1000 for og, t, r in tr if og != 0 and r is not None])
    for win, step in itertools.product(WINS, STEPS):
        F = features(X8, win, step)
        st = np.arange(len(F)) * step / FS
        te = st + win / FS
        cal_r, cal_l = [], []
        for og, c in OZ.items():
            for cyc in (0, 1):
                t = CYCLE0[cyc] + 10 * og
                w = np.flatnonzero((st >= t + 1.0) & (te <= t + 4.2))
                cal_r.append(w)
                cal_l.append(np.full(len(w), c))
        cal_r, cal_l = np.concatenate(cal_r), np.concatenate(cal_l)
        sw = np.flatnonzero((st >= a_s) & (te <= b_s))
        for sname, cls in SETS.items():
            mdl = S9.Model(F, cal_r, cal_l, cls)
            sc = mdl.scores(F[sw])
            o = np.sort(sc, 1)
            margin = o[:, -1] - o[:, -2]
            pred = np.array(cls)[np.argmax(sc, 1)]
            # in-set gesture trials with an onset; rest intervals = Rest trials + gaps, away from all movement
            trials, busy = [], []
            for og, t, r in tr:
                c = OZ.get(og)
                if og == 0:
                    continue
                if r is None:
                    busy.append((t - 1.0, t + 9.0))
                    continue
                on, off = r[0] / FS, (r[1] / FS if r[1] is not None else t + 6.5)
                busy.append((on - 0.5, off + 1.5))
                if c is not None and c in cls:
                    trials.append((c, on, off))
            rest_iv = []
            edges = sorted(busy)
            cur = a_s + 1.0
            for a, b in edges:
                if a > cur:
                    rest_iv.append((cur, a))
                cur = max(cur, b)
            if b_s - 0.5 > cur:
                rest_iv.append((cur, b_s - 0.5))
            for s in settings():
                if s[0] != win or s[1] != step:
                    continue
                est = replay(pred, margin, s[2], s[3], s[4])
                r = metrics(est, te[sw], trials, rest_iv)
                rows.append(dict(subject=subj, set=sname, win_ms=win / 2, step_ms=step / 2, k=s[2], m=s[3],
                                 hi=s[4] if s[4] is not None else np.nan, **r))
            if (win, step) == (400, 200):
                stats.setdefault('margin_q', {})[sname] = np.percentile(margin, [10, 25, 50, 75, 90]).round(2).tolist()
    return rows, stats


def summarize(df, p, sets=SETS):
    key = ['set', 'win_ms', 'step_ms', 'k', 'm', 'hi']
    g = df.fillna({'hi': -1}).groupby(key)
    s = g[['first_ok', 'miss', 'start_ms', 'stop_ms', 'wrong_tr', 'false_min']].median().reset_index()
    s['hi'] = s['hi'].replace(-1, np.nan)
    for sname in sets:
        d = s[s.set == sname].copy()
        b = d[(d.win_ms == 200) & (d.step_ms == 100) & (d.k == 3) & (d.m == 0) & d.hi.isna()].iloc[0]
        p(f'\n===== {sname}: median over participants')
        p(f'board now (200 ms / 100 ms, k 3, m 0): first_ok {b.first_ok:.1f} %, miss {b.miss:.1f} %, '
          f'start {b.start_ms:.0f} ms, stop {b.stop_ms:.0f} ms, wrong/trial {b.wrong_tr:.2f}, false/min {b.false_min:.2f}')
        # Pareto front on (start_ms low, first_ok high)
        d = d.sort_values(['start_ms', 'first_ok'], ascending=[True, False])
        front, best = [], -1
        for r in d.itertuples():
            if r.first_ok > best + 1e-9:
                front.append(r)
                best = r.first_ok
        p('Pareto front (faster start vs right first command):')
        p('  win  step  k    m   hi | first_ok  miss  start_ms  stop_ms  wrong/tr  false/min')
        for r in front:
            hi = '  -' if np.isnan(r.hi) else f'{r.hi:3.0f}'
            p(f'  {r.win_ms:3.0f}  {r.step_ms:4.0f}  {r.k}  {r.m:3.1f}  {hi} | {r.first_ok:8.1f} {r.miss:5.1f} '
              f'{r.start_ms:9.0f} {r.stop_ms:8.0f} {r.wrong_tr:9.2f} {r.false_min:10.2f}')
        ok = d[d.first_ok >= b.first_ok - 1.0].sort_values('start_ms').head(8)
        p(f'fastest settings within 1 point of the board now ({b.first_ok:.1f} %):')
        for r in ok.itertuples():
            hi = '  -' if np.isnan(r.hi) else f'{r.hi:3.0f}'
            p(f'  {r.win_ms:3.0f}  {r.step_ms:4.0f}  {r.k}  {r.m:3.1f}  {hi} | {r.first_ok:8.1f} {r.miss:5.1f} '
              f'{r.start_ms:9.0f} {r.stop_ms:8.0f} {r.wrong_tr:9.2f} {r.false_min:10.2f}')
        p('effect of k alone (200 ms / 100 ms, m 0):')
        for r in d[(d.win_ms == 200) & (d.step_ms == 100) & (d.m == 0) & d.hi.isna()].sort_values('k').itertuples():
            p(f'  k {r.k}: first_ok {r.first_ok:5.1f}  start {r.start_ms:5.0f} ms  stop {r.stop_ms:5.0f} ms  '
              f'wrong/tr {r.wrong_tr:4.2f}  false/min {r.false_min:5.2f}')
    return s


# ---------------------------------------------------------------- Part 1: day-1 decomposition
def day1(folder, name, p):
    emg = pd.read_csv(os.path.join(folder, f'{name}_emg.csv'))
    ms = emg.unix_ms.to_numpy(np.float64)
    fr = emg.frame.to_numpy(np.float64)
    slope, icpt = np.polyfit(fr, ms - ms[0], 1)
    t_of = lambda i: ms[0] + icpt + slope * i              # noqa: E731  unix ms of sample i
    X = emg[[f'ch{c}_V' for c in range(1, 5)]].to_numpy(np.float64)
    rate = 1000.0 / slope
    env = envelope(X) if abs(rate - FS) < 50 else None
    assert env is not None, f'sample rate {rate:.0f} Hz'
    task = pd.read_csv(os.path.join(folder, f'{name}_task.csv'), dtype=str, keep_default_na=False)
    task['t'] = task.unix_ms.astype(float)
    on_rows = task[(task.event == 'trial_on') & (task.segment == 'task')]
    end_rows = task[(task.event == 'trial_end') & (task.segment == 'task')]
    rows = []
    for r in on_rows.itertuples():
        e = end_rows[(end_rows.step == r.step) & (end_rows.t >= r.t)]
        if not len(e):
            continue
        e = e.iloc[0]
        lat = float(e.latency_ms) if e.latency_ms not in ('', 'nan') else np.nan
        cue = int(round((r.t - ms[0] - icpt) / slope))
        o = onset(env, cue, t_end=cue + int(0.5 * FS), peak=(0.2, 2.0)) if np.isfinite(lat) else None
        on_ms = (t_of(o[0]) - r.t) if o else np.nan
        rows.append(dict(step=r.step, target=r.target, result=e.result, latency=lat, react=on_ms,
                         system=lat - on_ms if o else np.nan))
    d = pd.DataFrame(rows)
    q = lambda v: f'median {np.nanmedian(v):5.0f} ms (quartiles {np.nanpercentile(v, 25):4.0f}-{np.nanpercentile(v, 75):4.0f}, n {np.isfinite(v).sum()})'  # noqa: E731,E501
    p(f'===== Part 1: {name}, {len(d)} task trials, sample rate {rate:.0f} Hz')
    p(f'cue -> command (TaskScreen):        {q(d.latency.to_numpy())}')
    p(f'cue -> EMG onset (reaction):        {q(d.react.to_numpy())}')
    p(f'EMG onset -> command (system):      {q(d.system.to_numpy())}')
    for res in ('right', 'wrong'):
        s = d[d.result == res]
        if len(s):
            p(f'  {res:5s} commands: reaction {q(s.react.to_numpy())}; system {q(s.system.to_numpy())}')
    p(f'trials without a clear onset: {int(d.react.isna().sum() - d.latency.isna().sum())}, timeouts: {int(d.latency.isna().sum())}')
    return d


# ---------------------------------------------------------------- Part 3: own 9-gesture recording
def self_day(folder, name, cal_s, p):
    import selftest_analysis as SA
    X, t0, rate = SA.load_emg(os.path.join(folder, f'{name}_emg.csv'))       # resampled to 2 kHz, t0 = unix ms
    env = envelope(X[:, :4].astype(np.float64))
    ops = pd.read_csv(os.path.join(folder, f'{name}_ops.csv'))
    task = pd.read_csv(os.path.join(folder, f'{name}_task.csv'), dtype=str, keep_default_na=False)
    task['t'] = task.unix_ms.astype(float)
    sec = lambda u: (u - t0) / 1000.0                                          # noqa: E731
    first_seg = task.loc[task.event == 'seg_start', 't'].min()
    cal = [(int(c.split()[1]), float(r.unix_ms)) for r in ops.itertuples() for c in [str(r.command)]
           if len(c.split()) == 2 and c.split()[0] == 'cal' and c.split()[1].isdigit() and r.unix_ms < first_seg
           and str(r.accepted) not in ('0', 'False')]
    assert {g for g, _ in cal} == set(range(9)), f'{name}: cued pass incomplete'
    spans, trials_all, cur = [], [], None
    for r in task.itertuples():
        if r.event == 'seg_start' and r.segment == 'task':
            cur = r.t
        elif r.event in ('seg_end', 'seg_abort') and cur is not None:
            spans.append((sec(cur), sec(r.t)))
            cur = None
    on_t = {}
    for r in task[task.segment == 'task'].itertuples():
        if r.event == 'trial_on':
            on_t[r.step] = r.t
        elif r.event == 'trial_off' and r.step in on_t and r.target in S9.COMMAND:
            cue = int(round(sec(on_t[r.step]) * FS))
            o = onset(env, cue, t_end=cue + int(0.5 * FS), peak=(0.2, 2.0))
            trials_all.append((S9.G[S9.COMMAND[r.target]], sec(on_t[r.step]), sec(r.t), o))
    p(f'===== Part 3: {name}, {len(trials_all)} task trials, {sum(o is None for *_, o in trials_all)} without a clear '
      f'onset, cued windows {cal_s:.0f} s per cue, sample rate {rate:.0f} Hz')
    rows = []
    for win, step in itertools.product(WINS, STEPS):
        F = features(X, win, step)
        st = np.arange(len(F)) * step / FS
        te = st + win / FS
        cr = [np.flatnonzero((st >= sec(t) + 1.0) & (te <= sec(t) + cal_s)) for _, t in cal]
        cal_r, cal_l = np.concatenate(cr), np.concatenate([np.full(len(w), g) for (g, _), w in zip(cal, cr)])
        for sname, cls in S9.SETS.items():
            mdl = S9.Model(F, cal_r, cal_l, cls)
            sw = np.flatnonzero(np.any([(st >= a) & (te <= b) for a, b in spans], axis=0))
            sc = mdl.scores(F[sw])
            o_ = np.sort(sc, 1)
            margin = o_[:, -1] - o_[:, -2]
            pred = np.array(cls)[np.argmax(sc, 1)]
            trials, busy = [], []
            for c, t_on, t_off, o in trials_all:
                if o is None:
                    busy.append((t_on - 1.0, t_off + 2.0))
                    continue
                on, off = o[0] / FS, (o[1] / FS if o[1] is not None else t_off)
                busy.append((on - 0.5, off + 1.5))
                if c in cls:
                    trials.append((c, on, off))
            rest_iv = []
            for a, b in spans:
                cur_ = a + 1.0
                for x, y in sorted(busy):
                    if y <= a or x >= b:
                        continue
                    if x > cur_:
                        rest_iv.append((cur_, x))
                    cur_ = max(cur_, y)
                if b - 0.5 > cur_:
                    rest_iv.append((cur_, b - 0.5))
            # one continuous stream per task segment: the decision state is reset at each segment start
            seg_id = np.zeros(len(sw), int)
            for j, (a, b) in enumerate(spans):
                seg_id[(st[sw] >= a) & (te[sw] <= b)] = j
            for s in settings():
                if s[0] != win or s[1] != step:
                    continue
                est = np.concatenate([replay(pred[seg_id == j], margin[seg_id == j], s[2], s[3], s[4])
                                      for j in range(len(spans))])
                if not trials:
                    continue
                r = metrics(est, te[sw], trials, rest_iv)
                rows.append(dict(subject=name, set=sname, win_ms=win / 2, step_ms=step / 2, k=s[2], m=s[3],
                                 hi=s[4] if s[4] is not None else np.nan, **r))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--oz')
    ap.add_argument('--subjects', default='1-40')
    ap.add_argument('--day1', nargs=2)
    ap.add_argument('--self', nargs=2)
    ap.add_argument('--cal-s', type=float, default=4.0)
    ap.add_argument('--out')
    ap.add_argument('--jobs', type=int, default=8)
    a = ap.parse_args()
    lines = []

    def p(s=''):
        print(s, flush=True)
        lines.append(s)

    if a.out:
        os.makedirs(a.out, exist_ok=True)
    if a.day1:
        d = day1(a.day1[0], a.day1[1], p)
        if a.out:
            d.to_csv(os.path.join(a.out, f'day1_{a.day1[1]}.csv'), index=False)
    if a.oz:
        for w, s in itertools.product(WINS, STEPS):
            fe_build(w, s)                                    # compile once before the workers start
        lo, hi = (a.subjects.split('-') + [None])[:2]
        subs = list(range(int(lo), int(hi or lo) + 1))
        res = Parallel(n_jobs=a.jobs)(delayed(oz_subject)(os.path.join(a.oz, f'{s}_raw.mat'), s) for s in subs)
        df = pd.DataFrame([r for rows, _ in res for r in rows])
        p(f'===== Part 2: Ozdemir 2022, {len(subs)} participants, {df.groupby(["win_ms", "step_ms", "k", "m", "hi"], dropna=False).ngroups} settings per set')
        react = np.concatenate([st['react'] for _, st in res])
        p(f'gesture trials without a clear onset: {sum(st["no_onset"] for _, st in res)} of {len(subs) * 18}; '
          f'reaction (cue -> onset) median {np.median(react):.0f} ms')
        for sname in SETS:
            qs = np.median([st['margin_q'][sname] for _, st in res], axis=0)
            p(f'{sname} margin (top - second LDA score) percentiles 10/25/50/75/90, 200/100 ms: {np.round(qs, 2).tolist()}')
        summarize(df, p)
        if a.out:
            df.to_csv(os.path.join(a.out, 'ozdemir_latency_sweep.csv'), index=False)
    if a.self:
        df = self_day(a.self[0], a.self[1], a.cal_s, p)
        summarize(df, p, sets=S9.SETS)
        if a.out:
            df.to_csv(os.path.join(a.out, f'self_{a.self[1]}_latency_sweep.csv'), index=False)
    if a.out:
        name = 'latency_sweep.txt' if not a.self else f'self_{a.self[1]}_latency_sweep.txt'
        with open(os.path.join(a.out, name), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
