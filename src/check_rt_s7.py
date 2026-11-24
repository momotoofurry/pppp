"""The S7 firmware rule (report 35.78: RTL_SET_CLASSES 0x1CF, RTL_SET_GATE 50 mode 2, k 5;
35.79: Rest established after k_rest 2, RTL_SET_REJECT 0 0 5 2) on the two self-test
donnings, through the real-time C loop (src/c/rt_lda.c, 9-class build as on the board: -DLD_CLASSES=9
-DDC_CLASSES=9 -DRTL_LABEL_MAX=810) on the PC, against a Python re-statement.

Drive per donning: the whole recording as the board receives it (int16, 0.25 uV, 20 frames per packet, one
STREAM_RESET at the start, warm-up 0); LABEL_START g / LABEL_END around exactly the cued windows selftest9_analysis
uses (the last 30 windows of every 4 s cue, all 9 gestures: the firmware drops Point / ThumbUp at the fit); FIT +
rtl_idle() after the last cued window; then run mode for the rest of the recording (probes, task, rests).
Reference (Python): features of the same int16 signal (features.c through check_features_c), selftest9_analysis.Model
over the S7 classes (z-score of the active cued windows, Q5.10, OAS LDA); activity = float32 sum of the 8 MAV
features; threshold = median activity of the active non-Rest cued windows; gated = activity < 0.5 x threshold;
decision.c (k 5 for a command, k_rest 2 for Rest, all-or-nothing votes, Rest latches without a command).
Compared: gate threshold (RTL_EV_GATE_THR, nV), per window the predicted class and the gate flag, the commands.
Then, on the MCU's own output (continuous stream, no reset between cues, as on the board):
  probe  every S7 non-Rest probe cue: the first command in [cue_on, cue_off + 0.5 s]: right / wrong / none, latency
  rest   commands while resting: task rest periods from rest_on + 0.5 s, the 1 s after every probe cue, Rest cues
Writes results/selftest_T00/rt_s7_check.txt and rt_s7_labels_<name>.npz (per-window labels, with and
without the gate, and the stretches, for src/assist/modes_sim_emg.py).
usage (container): python src/check_rt_s7.py --dir /sd/T00 [--days T00_d1_G T00_d2_G]
"""
import argparse
import ctypes
import os
import struct
import subprocess
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pc'))
import check_rt_lda as R  # noqa: E402
import pipeline as P  # noqa: E402
import protocol as PR  # noqa: E402
import selftest_analysis as SA  # noqa: E402
import selftest9_analysis as S9  # noqa: E402

LIB9 = os.path.join(P.ROOT, 'build', 'c', 'librtl9.so')
FLAGS9 = ['-DLD_CLASSES=9', '-DDC_CLASSES=9', '-DRTL_LABEL_MAX=810']
SET_GATE, SET_CLASSES, EV_GATE_THR, EV_FIT = 13, 14, 20, 1
CL = S9.SETS['S7']
MASK = sum(1 << c for c in CL)                    # 0x1CF
K, K_REST, GATE_K100, GATE_MODE = 5, 2, 50, 2
REST = S9.REST
LSB = np.float32(2.5e-7)
MAV0 = 4 * 8
OUT = os.path.join(P.ROOT, 'results', 'selftest_T00')


def build9():
    src = [os.path.join(R.CSRC, f) for f in R.SRC]
    deps = src + [s[:-1] + 'h' for s in src]
    if not os.path.exists(LIB9) or os.path.getmtime(LIB9) < max(os.path.getmtime(s) for s in deps):
        os.makedirs(os.path.dirname(LIB9), exist_ok=True)
        subprocess.run(['gcc', '-O2', '-std=c99', '-Wall', '-Wextra', '-fPIC', '-shared', '-o', LIB9] + FLAGS9 + src
                       + ['-lm'], check=True)
    lib = ctypes.CDLL(LIB9)
    lib.rtl_init.argtypes = [ctypes.POINTER(R.Config)]
    lib.rtl_rx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    lib.rtl_idle.restype = None
    lib.rtl_counters.restype = ctypes.POINTER(R.Counters)
    return lib


def spans(name, t0, nw):
    """probe cues (rows, class, t_on); rest stretches (rows) without their first 0.5 s (the false-command count)
    and the release after every S7 probe cue (cue_off to the next cue_on, with the cue's class; the simulation)"""
    task = pd.read_csv(os.path.join(S9.day_folder(A.dir, name), f'{name}_task.csv'), dtype=str, keep_default_na=False)
    task['t'] = task.unix_ms.astype(float)
    cues, rests, full, on, last_off, last_g = [], [], [], {}, None, None
    for r in task.itertuples():
        if r.segment == 'labelled' and r.event == 'cue_on':
            on[('c', r.step)] = r
            if last_off is not None:
                rests.append(SA.inside(t0, nw, last_off + 500, r.t))
                full.append((SA.inside(t0, nw, last_off, r.t), last_g))
                last_off = None
        elif r.segment == 'labelled' and r.event == 'cue_off' and ('c', r.step) in on:
            a = on.pop(('c', r.step))
            g = S9.G[r.target]
            if g == REST:
                rests.append(SA.inside(t0, nw, a.t + 500, r.t))
            elif g in CL:
                cues.append((SA.inside(t0, nw, a.t, r.t + 500), g, a.t))
                last_off, last_g = r.t, g
        elif r.event == 'seg_end':
            last_off = None
        elif r.segment == 'task' and r.event == 'rest_on':
            on[('r', r.step)] = r
        elif r.segment == 'task' and r.event == 'rest_off' and ('r', r.step) in on:
            a = on.pop(('r', r.step))
            rests.append(SA.inside(t0, nw, a.t + 500, r.t))
    return cues, [w for w in rests if len(w)], [(w, g) for w, g in full if len(w)]


def ref_decision(top):
    """decision.c with all-or-nothing votes (every window accepted): list of (window index, class) commands and the
    latched class after every window"""
    out, last, run, latched, lat = [], -1, 0, -1, np.empty(len(top), int)
    for i, p in enumerate(top):
        run = min(run + 1, max(K, K_REST)) if p == last else 1
        last = p
        if run >= (K_REST if p == REST else K) and p != latched:
            latched = p
            if p != REST:
                out.append((i, p))
        lat[i] = latched
    return out, lat


def run_day(name, lib):
    day = S9.load_day(A.dir, name, 4.0, frozenset(CL))   # cued rows / labels (the same windows as the analysis)
    X, t0, _ = SA.load_emg(os.path.join(S9.day_folder(A.dir, name), f'{name}_emg.csv'))
    q = np.clip(np.round(X.astype(np.float64) / 2.5e-7), -32768, 32767).astype(np.int16)
    Fq = SA.features(q.astype(np.float32) * LSB)
    nw = len(Fq)
    assert nw == len(day['F'])
    # Python reference
    mdl = S9.Model(Fq, day['cal_rows'], day['cal_lab'], CL)
    act = np.zeros(nw, np.float32)
    for ch in range(8):
        act = act + Fq[:, MAV0 + ch].astype(np.float32)
    gl = np.isin(day['cal_lab'], CL) & (day['cal_lab'] != REST)
    v = np.sort(act[day['cal_rows'][gl]])
    m = len(v)
    thr = v[m // 2] if m & 1 else np.float32(0.5) * (v[m // 2 - 1] + v[m // 2])
    gated_py = act < np.float32(GATE_K100 / 100.0) * thr
    top_py = mdl.predict(Fq)
    top_py[gated_py] = REST
    # C, as the board
    dec = PR.Decoder()
    preds, cmds, status = {}, [], []

    def tx(ptr, n):
        for t, _, p in dec.feed(ctypes.string_at(ptr, n)):
            if t == PR.PRED:
                w, _, cls, acc, mg, gt = struct.unpack('<IIBBHB', p[:13])
                preds[w - 1] = (cls, gt)
            elif t == PR.COMMAND:
                w, _, cmd, cls, _ = struct.unpack('<IIBBH', p[:12])
                cmds.append((w - 1, cls))
            else:
                status.append(struct.unpack('<B3xi', p[:8]))
    txcb = R.TX(tx)
    cfg = R.Config(txcb, R.NOW(0), 0, 0, 0, K)
    lib.rtl_init(ctypes.byref(cfg))
    enc = PR.Encoder()

    def send(b):
        lib.rtl_rx(ctypes.c_char_p(b), len(b))
    send(R.ctl(enc, SET_CLASSES, bytes([MASK & 0xFF, MASK >> 8])) + R.ctl(enc, SET_GATE, bytes([GATE_K100, 0, GATE_MODE]))
         + R.ctl(enc, R.SET_REJECT, bytes([0, 0, 0, 0, K, K_REST]))
         + R.ctl(enc, R.SET_REPORT, bytes([1])) + R.ctl(enc, PR.STREAM_RESET))
    # label runs: (first window, last window, class), contiguous cued windows of one cue
    rows, lab = day['cal_rows'], day['cal_lab']
    order = np.argsort(rows)
    rows, lab = rows[order], lab[order]
    runs, s = [], 0
    for i in range(1, len(rows) + 1):
        if i == len(rows) or rows[i] != rows[i - 1] + 1 or lab[i] != lab[i - 1]:
            runs.append((rows[s], rows[i - 1], lab[s]))
            s = i
    FPP = PR.FRAMES_PER_PACKET
    n_pk = len(q) // FPP
    # window w is complete after frame w*STEP + WIN - 1, i.e. after packet (w*STEP + WIN) / FPP - 1
    before = {(a * SA.STEP + SA.WIN) // FPP - 1: g for a, _, g in runs}
    after = {(b * SA.STEP + SA.WIN) // FPP - 1 for _, b, _ in runs}
    fit_after = max(after)
    for k in range(n_pk):
        b = b''
        if k in before:
            b += R.ctl(enc, R.LABEL_START, bytes([int(before[k])]))
        b += enc.packet(PR.SAMPLES, q[k * FPP:(k + 1) * FPP].tobytes())
        if k in after:
            b += R.ctl(enc, R.LABEL_END)
        if k == fit_after:
            b += R.ctl(enc, R.FIT)
        send(b)
        if k == fit_after:
            lib.rtl_idle()
    c = lib.rtl_counters().contents
    thr_c = [v for e, v in status if e == EV_GATE_THR]
    fit_c = [v for e, v in status if e == EV_FIT]
    run_w = np.array(sorted(preds))
    top_c = np.array([preds[w][0] for w in run_w])
    gt_c = np.array([preds[w][1] for w in run_w]).astype(bool)
    # decision.c on the MCU's own windows, and on Python's
    want, _ = ref_decision(top_c)
    want = [(int(run_w[i]), p) for i, p in want]
    ref_py, _ = ref_decision(top_py[run_w])
    lines = [f'== {name}: {nw} windows, cued runs {len(runs)}, label windows {c.label_windows}, fit {fit_c}, '
             f'lost {c.lost_packets}, skipped busy {c.skipped_busy}',
             f'gate threshold: C {thr_c} nV, Python {thr * 1e9:.1f} nV',
             f'run-mode windows {len(run_w)}: class agree {np.mean(top_c == top_py[run_w]) * 100:.3f} %, '
             f'gate flag agree {np.mean(gt_c == gated_py[run_w]) * 100:.3f} %, gated {gt_c.mean() * 100:.1f} %',
             f'commands: C {len(cmds)}, decision.c on the C windows {len(want)}, identical {cmds == want}; '
             f'on the Python windows {len(ref_py)}']
    # metrics on the MCU's commands
    cues, rests, full = spans(name, t0, nw)
    cw = np.array([w for w, _ in cmds])
    cc = np.array([g for _, g in cmds])
    ok = wr = no = 0
    lat = []
    for w, g, ton in cues:
        sel = (cw >= w[0]) & (cw <= w[-1]) if len(w) else np.zeros(len(cw), bool)
        if not sel.any():
            no += 1
            continue
        i = np.flatnonzero(sel)[0]
        ok += cc[i] == g
        wr += cc[i] != g
        lat.append(t0 + cw[i] * SA.STEP / SA.FS * 1000 + SA.WIN / SA.FS * 1000 - ton)
    rest_set = np.zeros(nw, bool)
    for w in rests:
        rest_set[w] = True
    fc = int(rest_set[cw].sum()) if len(cw) else 0
    mins = rest_set.sum() * SA.STEP / SA.FS / 60
    n = len(cues)
    lines.append(f'probe cues {n}: right {100 * ok / n:.1f} %, wrong {100 * wr / n:.1f} %, none {100 * no / n:.1f} %, '
                 f'latency median {np.median(lat):.0f} ms (quartiles {np.percentile(lat, 25):.0f}-'
                 f'{np.percentile(lat, 75):.0f}); rest {mins:.2f} min: {fc} commands = {fc / mins:.2f} / min')
    # per-window labels for the simulation (the MCU's own classes; -1 before run mode)
    labw = np.full(nw, -1, int)
    labw[run_w] = top_c
    raw = np.full(nw, -1, int)                    # the same LDA without the gate (Python; = C, agree 100 %)
    raw[run_w] = mdl.predict(Fq[run_w])
    np.savez(os.path.join(OUT, f'rt_s7_labels_{name}.npz'), lab=labw, lab_raw=raw, act_ratio=act / thr,
             rest_starts=np.array([w[0] for w in rests]), rest_lens=np.array([len(w) for w in rests]),
             rel_starts=np.array([w[0] for w, _ in full]), rel_lens=np.array([len(w) for w, _ in full]),
             rel_cls=np.array([g for _, g in full]),
             cue_starts=np.array([w[0] for w, _, _ in cues]), cue_lens=np.array([len(w) for w, _, _ in cues]),
             cue_cls=np.array([g for _, g, _ in cues]))
    return lines


def main():
    lib = build9()
    os.makedirs(OUT, exist_ok=True)
    lines = [f'S7 firmware rule through rt_lda.c (9-class build {" ".join(FLAGS9)}): classes 0x{MASK:03X}, '
             f'gate {GATE_K100 / 100} x median gesture activity (mode {GATE_MODE}), k {K}, k_rest {K_REST}']
    for name in A.days:
        day_lines = run_day(name, lib)
        lines += day_lines
        print('\n'.join(day_lines), flush=True)
    with open(os.path.join(OUT, 'rt_s7_check.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


ap = argparse.ArgumentParser()
ap.add_argument('--dir', required=True)
ap.add_argument('--days', nargs='+', default=['T00_d1_G', 'T00_d2_G'])
A = ap.parse_args()
main()
