"""Real-time loop of the LDA main line (src/c/rt_lda.c) on the PC, driven with recorded raw EMG through the serial
protocol, against a float64 reference built from the same samples. Exploratory (report 35.13); rt.c is untouched.

Per subject of arm_position (20): the raw recordings (int16 at 0.25 uV, as the PC forwarder sends them) go through
rtl_rx() packet by packet, exactly as over the serial link:
  day 1   the 6 calibration recordings, each STREAM_RESET + LABEL_START(gesture) + samples + LABEL_END; then FIT
  blocks  for each of the 11 test blocks: the first two recordings of every gesture as the cued start-up sequence
          (labelled, 120 windows), FIT, then the other recordings of the block are classified (PK_PRED per window)
warmup = 9 windows after every reset, so windows 9..18 of each 2 s recording are used, as upstream.
Reference: features of the same int16 samples (features.c through check_features_c), then lda_anchor.OasLDA
(float64) with the session statistics of each start-up sequence = cum_T2 of lda_main.py. Compared per window:
predicted class, margin (the MCU sends floor(margin x 100)), and the commands (k = 3, no rejection) against a
Python re-statement of decision.c. A second pass with a margin threshold and a distance threshold checks the
'accepted' flag against the reference.
Also: -DRTL_LABEL_MAX variants are not built; --arm compiles the firmware modules for Cortex-M7 and reports the
static RAM of each object (arm-none-eabi-size).
Writes results/rt_lda_check.csv, rt_lda_summary.csv; with --arm arm_rt_lda_size.csv.
Usage (in the container): python src/check_rt_lda.py [--arm] [--jobs 19]
"""
import argparse
import ctypes
import os
import struct
import subprocess
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pc'))
import check_features_c as FC  # noqa: E402
import lda_anchor as LA  # noqa: E402
import pipeline as P  # noqa: E402
import protocol as PR  # noqa: E402

CSRC = os.path.join(P.ROOT, 'src', 'c')
LIB = os.path.join(P.ROOT, 'build', 'c', 'librtl.so')
OUT = os.path.join(P.ROOT, 'results')
SRC = ['rt_lda.c', 'ldacal.c', 'protocol.c', 'features.c', 'decision.c']
TX = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint32)
NOW = ctypes.CFUNCTYPE(ctypes.c_uint32)
LABEL_START, LABEL_END, FIT, SET_REJECT, SET_REPORT, FORGET = 2, 3, 4, 5, 6, 11
CMD = [1, 5, 2, 3, 4, 0]                         # decision.c dc_class_command
K = 3
ARM_FLAGS = ['-mcpu=cortex-m7', '-mthumb', '-mfpu=fpv5-d16', '-mfloat-abi=hard', '-Os', '-ffunction-sections',
             '-fdata-sections', '-std=c99', '-Wall', '-fstack-usage']


class Config(ctypes.Structure):
    _fields_ = [('tx', TX), ('now_us', NOW), ('warmup', ctypes.c_uint16), ('margin_x100', ctypes.c_uint16),
                ('dist2', ctypes.c_uint16), ('k', ctypes.c_uint8)]


class Counters(ctypes.Structure):
    _fields_ = [(k, ctypes.c_uint32) for k in ['windows', 'windows_used', 'classified', 'skipped_busy', 'commands',
                                               'lost_packets', 'seq_gaps', 'label_windows', 'fits']] + \
               [('fit_result', ctypes.c_int32)]


def build():
    src = [os.path.join(CSRC, f) for f in SRC]
    deps = src + [s[:-1] + 'h' for s in src]
    if not os.path.exists(LIB) or os.path.getmtime(LIB) < max(os.path.getmtime(s) for s in deps):
        os.makedirs(os.path.dirname(LIB), exist_ok=True)
        subprocess.run(['gcc', '-O2', '-std=c99', '-Wall', '-Wextra', '-fPIC', '-shared', '-o', LIB] + src + ['-lm'],
                       check=True)
    lib = ctypes.CDLL(LIB)
    lib.rtl_init.argtypes = [ctypes.POINTER(Config)]
    lib.rtl_rx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    lib.rtl_counters.restype = ctypes.POINTER(Counters)
    lib.rtl_static_bytes.restype = ctypes.c_uint
    return lib


def recordings(subject, folder):
    raw = np.load(os.path.join(P.REPO, 'dataset_arm_position', str(subject), folder, 'data.npy'))
    lab = np.load(os.path.join(P.REPO, 'dataset_arm_position', str(subject), folder, 'label.npy')).astype(int)
    q = np.clip(np.round(raw / PR.LSB_VOLT), -32768, 32767).astype('<i2')       # trials x 8 x 4000
    return q, lab


def features(L, q):
    """reference features of int16 recordings (trials x 8 x n): windows 9..18 -> (trials, 10, 80) float64"""
    out = np.zeros((len(q), FC.NWIN, 80), dtype=np.float32)
    for t, rec in enumerate(q):
        x = np.ascontiguousarray(rec.astype(np.float32) * np.float32(PR.LSB_VOLT))
        assert L.fe_recording(x.ctypes.data, x.shape[1], out[t].ctypes.data, FC.NWIN) == FC.NWIN
    return out[:, FC.W0:, :].astype(np.float64)


def sample_bytes(enc, rec):
    frames = np.ascontiguousarray(rec.T)
    out = bytearray()
    for i in range(0, len(frames), PR.FRAMES_PER_PACKET):
        out += enc.packet(PR.SAMPLES, frames[i:i + PR.FRAMES_PER_PACKET].tobytes())
    return bytes(out)


def ctl(enc, sub, payload=b''):
    return enc.packet(PR.CONTROL, bytes([sub]) + payload)


def ref_commands(pred, acc):
    """decision.c for one recording (dc_reset before it): list of (index, command)"""
    out, last, run, latched = [], -1, 0, -1
    for i, (p, a) in enumerate(zip(pred, acc)):
        if not a:
            last, run = -1, 0
            continue
        if p == last:
            run = min(run + 1, K)
        else:
            last, run = p, 1
        if run < K or p == latched:
            continue
        latched = p
        if CMD[p]:
            out.append((i, CMD[p]))
    return out


def run(subject, margin_x100=0, dist2=0):
    lib = build()
    L = FC.lib()
    dec = PR.Decoder()
    preds, cmds, status = [], [], []

    def tx(ptr, n):
        for t, _, p in dec.feed(ctypes.string_at(ptr, n)):
            if t == PR.PRED:
                w, _, cls, acc, m = struct.unpack('<IIBBH', p[:12])
                preds.append((w, cls, acc, m))
            elif t == PR.COMMAND:
                w, _, cmd, cls, m = struct.unpack('<IIBBH', p[:12])
                cmds.append((w, cmd))
            else:
                status.append(struct.unpack('<B3xi', p[:8]))
    txcb = TX(tx)
    cfg = Config(txcb, NOW(0), FC.W0, margin_x100, dist2, K)
    lib.rtl_init(ctypes.byref(cfg))
    enc = PR.Encoder()

    def send(b):
        lib.rtl_rx(ctypes.c_char_p(b), len(b))

    def label(q, lab):
        for rec, y in zip(q, lab):
            send(ctl(enc, PR.STREAM_RESET) + ctl(enc, LABEL_START, bytes([int(y)])) + sample_bytes(enc, rec)
                 + ctl(enc, LABEL_END))
        send(ctl(enc, FIT))
        lib.rtl_idle()
        assert lib.rtl_counters().contents.fit_result == 0, lib.rtl_counters().contents.fit_result

    send(ctl(enc, SET_REPORT, bytes([1])))
    ref = LA.OasLDA()
    q, lab = recordings(subject, 'calibration')
    label(q, lab)
    F = features(L, q).reshape(-1, 80)
    ref.add(LA.zs(F), np.repeat(lab, 10))
    rows = []
    for b in range(P.N_BLOCKS):
        q, lab = recordings(subject, f'testing_block{b}')
        anc = np.sort(np.concatenate([np.flatnonzero(lab == c)[:2] for c in range(6)]))
        rest = np.setdiff1d(np.arange(len(lab)), anc)
        label(q[anc], lab[anc])
        Fa = features(L, q[anc]).reshape(-1, 80)
        mu, sd = Fa.mean(0), Fa.std(0)
        ref.add((Fa - mu) / sd, np.repeat(lab[anc], 10))
        ref.fit()
        Ci = np.linalg.inv((1 - ref.rho) * ref.S + ref.rho * np.trace(ref.S) / 80 * np.eye(80))
        n = agree = ok_c = ok_py = acc_agree = cmd_same = cmd_n = near = 0
        dm = 0.0
        for r in rest:
            p0, c0 = len(preds), len(cmds)
            w0 = lib.rtl_counters().contents.windows
            send(ctl(enc, PR.STREAM_RESET) + sample_bytes(enc, q[r]))
            got = preds[p0:]
            assert len(got) == 10, len(got)
            Z = (features(L, q[r:r + 1]).reshape(-1, 80) - mu) / sd
            s = ref.scores(Z)
            pp = np.argmax(s, axis=1)
            o = np.sort(s, axis=1)
            mar = o[:, -1] - o[:, -2]
            Zq = LA.OasLDA.q(Z)
            d2 = np.einsum('nd,de,ne->n', Zq, Ci, Zq) - 2 * o[:, -1]
            acc = (np.floor(mar * 100) >= margin_x100) & ((d2 <= dist2) if dist2 else True)
            pc = np.array([g[1] for g in got])
            ac = np.array([g[2] for g in got]).astype(bool)
            mc = np.array([g[3] for g in got])
            n += 10
            agree += int(np.sum(pc == pp))
            ok_c += int(np.sum(pc == lab[r]))
            ok_py += int(np.sum(pp == lab[r]))
            acc_agree += int(np.sum(ac == acc))
            near += int(np.sum(np.abs(mc - np.minimum(np.floor(mar * 100), 65535)) <= 1))
            dm = max(dm, float(np.max(np.abs(mc - np.minimum(mar * 100, 65535)))))
            want = [(w0 + FC.W0 + 1 + i, c) for i, c in ref_commands(pc, ac)]     # decision logic on the MCU's own windows
            cmd_n += 1
            cmd_same += int(cmds[c0:] == want)
        rows.append(dict(subject=subject, margin_x100=margin_x100, dist2=dist2, block=b, windows=n, agree=agree,
                         acc_c=ok_c / n * 100, acc_py=ok_py / n * 100, accepted_agree=acc_agree, margin_within_1=near,
                         margin_max_diff=dm, recordings=cmd_n, commands_as_decision_c=cmd_same))
    c = lib.rtl_counters().contents
    for r in rows:
        r.update(fits=c.fits, lost=c.lost_packets, commands=c.commands, skipped_busy=c.skipped_busy)
    return rows


def arm_size():
    d = os.path.join(P.ROOT, 'build', 'arm_rt_lda')
    os.makedirs(d, exist_ok=True)
    rows = []
    for f in SRC:
        obj = os.path.join(d, f[:-1] + 'o')
        subprocess.run(['arm-none-eabi-gcc'] + ARM_FLAGS + ['-I', CSRC, '-c', os.path.join(CSRC, f), '-o', obj], check=True)
        o = subprocess.run(['arm-none-eabi-size', obj], check=True, capture_output=True, text=True).stdout.split('\n')[1].split()
        rows.append(dict(module=f, text=int(o[0]), data=int(o[1]), bss=int(o[2])))
    df = pd.DataFrame(rows)
    df.loc[len(df)] = dict(module='total', text=df.text.sum(), data=df.data.sum(), bss=df.bss.sum())
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--arm', action='store_true')
    args = ap.parse_args()
    import check_rt_lda as M
    FC.lib()
    lib = build()
    print('rt_lda static bytes (PC build, without ldacal / features):', lib.rtl_static_bytes())
    tasks = [delayed(M.run)(s) for s in range(20)] + [delayed(M.run)(s, 340, 150) for s in range(20)]
    res = Parallel(n_jobs=args.jobs, verbose=5)(tasks)
    df = pd.DataFrame([r for rows in res for r in rows])
    df.to_csv(os.path.join(OUT, 'rt_lda_check.csv'), index=False, float_format='%.6g')
    d = df[df.block >= 1]
    sm = d.groupby(['margin_x100', 'dist2']).agg(
        windows=('windows', 'sum'), agree=('agree', 'sum'), acc_c=('acc_c', 'mean'), acc_py=('acc_py', 'mean'),
        accepted_agree=('accepted_agree', 'sum'), margin_within_1=('margin_within_1', 'sum'),
        margin_max_diff=('margin_max_diff', 'max'), recordings=('recordings', 'sum'),
        commands_as_decision_c=('commands_as_decision_c', 'sum'), lost=('lost', 'max'),
        skipped_busy=('skipped_busy', 'max')).reset_index()
    sm['agree_pct'] = sm.agree / sm.windows * 100
    sm['accepted_agree_pct'] = sm.accepted_agree / sm.windows * 100
    sm.to_csv(os.path.join(OUT, 'rt_lda_summary.csv'), index=False, float_format='%.6g')
    pd.set_option('display.width', 250)
    print(sm.T.to_string())
    if args.arm:
        a = arm_size()
        a.to_csv(os.path.join(OUT, 'arm_rt_lda_size.csv'), index=False)
        print(a.to_string(index=False))


if __name__ == '__main__':
    main()
