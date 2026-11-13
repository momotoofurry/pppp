"""Activity gate in the real-time loop (RTL_SET_GATE in src/c/rt_lda.c) against a float64 re-statement.
Exploratory (report 35.28).

Same drive as check_rt_lda.py (20 subjects of arm_position, recorded int16 EMG through rtl_rx packet by packet;
day 1 calibration, then per test block the first two recordings of every gesture as the cued start-up sequence
and FIT, the other recordings classified), with RTL_SET_GATE sent before day 1. Settings: (k 1.00, mode 0 = the
threshold of day 1, as task_sim2.py), (k 0.50, mode 0), (k 1.00, mode 1 = a new threshold at every fit).
Reference: activity = sum of the 8 raw MAV features of the same C features (features.c), threshold =
sqrt(median Rest x smallest gesture median) over the cued windows of the fit (numpy.median, float64); a window
below k x threshold is Rest; otherwise argmax of lda_anchor.OasLDA as check_rt_lda.py; commands by decision.c.
Compared: the threshold the MCU reports (RTL_EV_GATE_THR, nV), per window the class and the gated flag, the
commands; windows whose activity lies within 1e-6 (relative) of the threshold are counted (float32 vs float64).
Writes results/rt_gate_check.csv.
Usage (in the container): python src/check_rt_gate.py [--jobs 19]
"""
import argparse
import ctypes
import os
import struct
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pc'))
import check_features_c as FC  # noqa: E402
import check_rt_lda as R  # noqa: E402
import lda_anchor as LA  # noqa: E402
import pipeline as P  # noqa: E402
import protocol as PR  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
SET_GATE, EV_GATE_THR, REST = 13, 20, 5
MAV = slice(32, 40)
SETTINGS = [(100, 0), (50, 0), (100, 1)]


def thr_of(F, y):
    a = F[:, MAV].sum(1)
    med = [np.median(a[y == c]) for c in range(6)]
    return float(np.sqrt(med[REST] * min(med[:5])))


def run(subject, k_x100, mode):
    lib = R.build()
    L = FC.lib()
    dec = PR.Decoder()
    preds, cmds, status = [], [], []

    def tx(ptr, n):
        for t, _, p in dec.feed(ctypes.string_at(ptr, n)):
            if t == PR.PRED:
                w, _, cls, acc, m, gated = struct.unpack('<IIBBHB', p[:13])
                preds.append((w, cls, gated))
            elif t == PR.COMMAND:
                w, _, cmd, cls, m = struct.unpack('<IIBBH', p[:12])
                cmds.append((w, cmd))
            else:
                status.append(struct.unpack('<B3xi', p[:8]))
    txcb = R.TX(tx)
    cfg = R.Config(txcb, R.NOW(0), FC.W0, 0, 0, R.K)
    lib.rtl_init(ctypes.byref(cfg))
    enc = PR.Encoder()

    def send(b):
        lib.rtl_rx(ctypes.c_char_p(b), len(b))

    def label(q, lab):
        s0 = len(status)
        for rec, y in zip(q, lab):
            send(R.ctl(enc, PR.STREAM_RESET) + R.ctl(enc, R.LABEL_START, bytes([int(y)])) + R.sample_bytes(enc, rec)
                 + R.ctl(enc, R.LABEL_END))
        send(R.ctl(enc, R.FIT))
        lib.rtl_idle()
        assert lib.rtl_counters().contents.fit_result == 0
        return [v for e, v in status[s0:] if e == EV_GATE_THR]

    send(R.ctl(enc, R.SET_REPORT, bytes([1])) + R.ctl(enc, SET_GATE, bytes([k_x100 & 0xFF, k_x100 >> 8, mode])))
    k = k_x100 / 100
    ref = LA.OasLDA()
    q, lab = R.recordings(subject, 'calibration')
    ev = label(q, lab)
    F = R.features(L, q).reshape(-1, 80)
    yF = np.repeat(lab, 10)
    thr = thr_of(F, yF)
    st = dict(thr_reports=1, thr_max_rel_diff=abs(ev[0] - thr * 1e9) / (thr * 1e9) if ev else 1.0, windows=0, agree=0,
              gated_c=0, gated_py=0, gated_agree=0, near=0, ok_c=0, ok_py=0, recordings=0, cmd_same=0)
    assert len(ev) == 1
    ref.add(LA.zs(F), yF)
    for b in range(P.N_BLOCKS):
        q, lab = R.recordings(subject, f'testing_block{b}')
        anc = np.sort(np.concatenate([np.flatnonzero(lab == c)[:2] for c in range(6)]))
        rest = np.setdiff1d(np.arange(len(lab)), anc)
        ev = label(q[anc], lab[anc])
        Fa = R.features(L, q[anc]).reshape(-1, 80)
        mu, sd = Fa.mean(0), Fa.std(0)
        ref.add((Fa - mu) / sd, np.repeat(lab[anc], 10))
        ref.fit()
        if mode == 1:
            thr = thr_of(Fa, np.repeat(lab[anc], 10))
            assert len(ev) == 1
            st['thr_reports'] += 1
            st['thr_max_rel_diff'] = max(st['thr_max_rel_diff'], abs(ev[0] - thr * 1e9) / (thr * 1e9))
        else:
            assert not ev
        for r in rest:
            p0, c0 = len(preds), len(cmds)
            w0 = lib.rtl_counters().contents.windows
            send(R.ctl(enc, PR.STREAM_RESET) + R.sample_bytes(enc, q[r]))
            got = preds[p0:]
            Fr = R.features(L, q[r:r + 1]).reshape(-1, 80)
            act = Fr[:, MAV].sum(1)
            gp = act < k * thr
            pp = np.argmax(ref.scores((Fr - mu) / sd), axis=1)
            pp[gp] = REST
            pc = np.array([g[1] for g in got])
            gc = np.array([g[2] for g in got]).astype(bool)
            st['windows'] += len(pp)
            st['agree'] += int(np.sum(pc == pp))
            st['gated_c'] += int(gc.sum())
            st['gated_py'] += int(gp.sum())
            st['gated_agree'] += int(np.sum(gc == gp))
            st['near'] += int(np.sum(np.abs(act - k * thr) <= 1e-6 * k * thr))
            st['ok_c'] += int(np.sum(pc == lab[r]))
            st['ok_py'] += int(np.sum(pp == lab[r]))
            want = [(w0 + FC.W0 + 1 + i, c) for i, c in R.ref_commands(pp, np.ones(len(pp), bool))]
            st['recordings'] += 1
            st['cmd_same'] += int(cmds[c0:] == want)
    return dict(subject=subject, k=k, mode=mode, **st)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    args = ap.parse_args()
    import check_rt_gate as M
    FC.lib()
    R.build()
    df = pd.DataFrame(Parallel(n_jobs=args.jobs)(delayed(M.run)(s, kx, md) for kx, md in SETTINGS for s in range(20)))
    df.to_csv(os.path.join(OUT, 'rt_gate_check.csv'), index=False, float_format='%.6g')
    pd.set_option('display.width', 250)
    g = df.groupby(['k', 'mode'])
    sm = g[['windows', 'agree', 'gated_c', 'gated_py', 'gated_agree', 'near', 'recordings', 'cmd_same', 'thr_reports']].sum()
    sm['thr_max_rel_diff'] = g.thr_max_rel_diff.max()
    sm['acc_c'] = g.ok_c.sum() / sm.windows * 100
    sm['acc_py'] = g.ok_py.sum() / sm.windows * 100
    sm['gated_pct'] = sm.gated_c / sm.windows * 100
    print(sm.to_string())


if __name__ == '__main__':
    main()
