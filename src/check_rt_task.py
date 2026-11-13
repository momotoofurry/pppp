"""Task labels in the real-time loop (RTL_TASK_LABEL in src/c/rt_lda.c) on the PC, against a float64 re-statement.
Exploratory (report 35.24).

Same drive as check_rt_lda.py (recorded int16 EMG of arm_position through rtl_rx, packet by packet): day 1
calibration, then per test block the first recording of every gesture as the cued start-up sequence (one cued
pass, 60 windows) and FIT; then every other recording of the block is streamed (STREAM_RESET + samples) and, right
after it, the robot side sends RTL_TASK_LABEL for the last command: expected = the recording's gesture with
probability 0.8, otherwise a random other gesture (Rest recordings: a random gesture); valid = expected + two
random other gestures. rtl_idle() then runs the soft update.
Reference (Python, float64, lda_anchor.OasLDA): the same features, z-score of the session, predictions; the same
rule for the windows of a command (run of agreeing windows, then further windows of the same class while the
class stays); decision.c as in check_rt_lda.ref_commands; prior and q as task_sim2 (eps 0.15, p0 0.05, beta 0.3),
forgetting 0.97, weighted sums, refit.
Compared per subject: predicted class of every window, commands, number of task updates, the argmax of q and
floor(999 q[argmax]) (reported by the MCU in RTL_EV_TASK), accuracy of both.
Writes results/rt_task_check.csv; with --arm, arm_rt_lda_task_size.csv (Cortex-M7 objects).
Usage (in the container): python src/check_rt_task.py [--arm] [--jobs 19]
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
TASK_LABEL, EV_TASK, EV_TASK_US = 12, 18, 19
EPS, P0, P_INVALID, BETA, DECAY, CMD_MAX = 0.15, 0.05, 0.01, 0.3, 0.97, 16
REST = 5


class Counters(ctypes.Structure):
    _fields_ = R.Counters._fields_ + [('task_labels', ctypes.c_uint32)]


def prior_of(e, mask):
    others = [c for c in range(5) if c != e and (mask >> c) & 1]
    pr = np.full(6, P_INVALID)
    pr[e] = 1 - EPS if others else 1 - P0
    for c in others:
        pr[c] = EPS / len(others)
    pr[REST] = P0
    return pr


def run(subject):
    lib = R.build()
    lib.rtl_counters.restype = ctypes.POINTER(Counters)
    L = FC.lib()
    dec = PR.Decoder()
    preds, cmds, status = [], [], []

    def tx(ptr, n):
        for t, _, p in dec.feed(ctypes.string_at(ptr, n)):
            if t == PR.PRED:
                w, _, cls, acc, m = struct.unpack('<IIBBH', p[:12])
                preds.append((w, cls))
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
        for rec, y in zip(q, lab):
            send(R.ctl(enc, PR.STREAM_RESET) + R.ctl(enc, R.LABEL_START, bytes([int(y)])) + R.sample_bytes(enc, rec)
                 + R.ctl(enc, R.LABEL_END))
        send(R.ctl(enc, R.FIT))
        lib.rtl_idle()
        assert lib.rtl_counters().contents.fit_result == 0

    send(R.ctl(enc, R.SET_REPORT, bytes([1])))
    rng = np.random.default_rng(subject)
    ref = LA.OasLDA()
    q, lab = R.recordings(subject, 'calibration')
    label(q, lab)
    ref.add(LA.zs(R.features(L, q).reshape(-1, 80)), np.repeat(lab, 10))
    st = dict(windows=0, agree=0, ok_c=0, ok_py=0, rec=0, cmd_same=0, upd_c=0, upd_py=0, upd_match=0, q_arg_same=0,
              q_milli_maxdiff=0, none_c=0)
    for b in range(P.N_BLOCKS):
        q, lab = R.recordings(subject, f'testing_block{b}')
        anc = np.sort(np.array([np.flatnonzero(lab == c)[0] for c in range(6)]))
        rest = np.setdiff1d(np.arange(len(lab)), anc)
        label(q[anc], lab[anc])
        Fa = R.features(L, q[anc]).reshape(-1, 80)
        mu, sd = Fa.mean(0), Fa.std(0)
        ref.add((Fa - mu) / sd, np.repeat(lab[anc], 10))
        ref.fit()
        for r in rest:
            p0, c0, s0 = len(preds), len(cmds), len(status)
            w0 = lib.rtl_counters().contents.windows
            send(R.ctl(enc, PR.STREAM_RESET) + R.sample_bytes(enc, q[r]))
            pc = np.array([g[1] for g in preds[p0:]])
            Z = (R.features(L, q[r:r + 1]).reshape(-1, 80) - mu) / sd
            pp = np.argmax(ref.scores(Z), axis=1)
            st['windows'] += len(pp)
            st['agree'] += int(np.sum(pc == pp))
            st['ok_c'] += int(np.sum(pc == lab[r]))
            st['ok_py'] += int(np.sum(pp == lab[r]))
            want = [(w0 + FC.W0 + 1 + i, c) for i, c in R.ref_commands(pp, np.ones(len(pp), bool))]
            st['rec'] += 1
            st['cmd_same'] += int(cmds[c0:] == want)
            # windows of the last command, as rt_lda.c
            run_rows, run_cls, pend, pend_cls, popen = [], -1, None, -1, False
            last, rn, latched = -1, 0, -1
            for i, p in enumerate(pp):
                if p != run_cls:
                    run_cls, run_rows = p, []
                if len(run_rows) < CMD_MAX:
                    run_rows.append(Z[i])
                if popen:
                    if p == pend_cls:
                        if len(pend) < CMD_MAX:
                            pend.append(Z[i])
                    else:
                        popen = False
                if p == last:
                    rn = min(rn + 1, R.K)
                else:
                    last, rn = p, 1
                if rn >= R.K and p != latched:
                    latched = p
                    if R.CMD[p]:
                        pend, pend_cls, popen = list(run_rows), p, True
            g = int(lab[r])
            e = g if (g < 5 and rng.random() < 0.8) else int(rng.choice([c for c in range(5) if c != g]))
            mask = (1 << e) | sum(1 << int(c) for c in rng.choice([c for c in range(5) if c != e], 2, replace=False))
            send(R.ctl(enc, TASK_LABEL, bytes([e, mask])))
            lib.rtl_idle()
            ev = [v for k, v in status[s0:] if k == EV_TASK]
            assert len(ev) == 1, status[s0:]
            vc = ev[0]
            if pend is not None:
                pr = prior_of(e, mask)
                Zp = np.stack(pend)
                s = ref.scores(Zp).mean(0)
                qq = pr * np.exp(BETA * (s - s.max()))
                qq /= qq.sum()
                ref.G *= DECAY
                ref.s *= DECAY
                ref.n *= DECAY
                Zq = LA.OasLDA.q(Zp)
                ref.G += Zq.T @ Zq
                ref.s += np.outer(qq, Zq.sum(0))
                ref.n += qq * len(Zq)
                ref.fit()
                st['upd_py'] += 1
                a = int(np.argmax(qq))
                if vc >= 0:
                    st['upd_match'] += 1
                    st['q_arg_same'] += int(vc // 1000 == a)
                    st['q_milli_maxdiff'] = max(st['q_milli_maxdiff'], abs(vc % 1000 - int(np.floor(qq[a] * 999))))
            if vc >= 0:
                st['upd_c'] += 1
            elif vc == -1:
                st['none_c'] += 1
    st['acc_c'] = st['ok_c'] / st['windows'] * 100
    st['acc_py'] = st['ok_py'] / st['windows'] * 100
    st['task_labels_counter'] = lib.rtl_counters().contents.task_labels
    return dict(subject=subject, **st)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--arm', action='store_true')
    args = ap.parse_args()
    import check_rt_task as M
    FC.lib()
    lib = R.build()
    print('rt_lda static bytes (PC build, without ldacal / features):', lib.rtl_static_bytes())
    df = pd.DataFrame(Parallel(n_jobs=args.jobs, verbose=0)(delayed(M.run)(s) for s in range(20)))
    df.to_csv(os.path.join(OUT, 'rt_task_check.csv'), index=False, float_format='%.6g')
    pd.set_option('display.width', 250)
    tot = df.drop(columns=['subject', 'acc_c', 'acc_py', 'q_milli_maxdiff']).sum()
    print(tot.to_string())
    print(f"agree {tot.agree / tot.windows * 100:.4f} %, commands as decision.c {tot.cmd_same}/{tot.rec}, "
          f"updates C {tot.upd_c} Python {tot.upd_py}, argmax same {tot.q_arg_same}/{tot.upd_match}, "
          f"max |floor(999q)| diff {df.q_milli_maxdiff.max()}, acc C {df.acc_c.mean():.2f} Python {df.acc_py.mean():.2f}")
    if args.arm:
        a = R.arm_size()
        a.to_csv(os.path.join(OUT, 'arm_rt_lda_task_size.csv'), index=False)
        print(a.to_string(index=False))


if __name__ == '__main__':
    main()
