"""Route B on the PC: serial protocol (protocol.c) and real-time loop (rt.c) driven with recorded raw EMG.

The firmware (rt.c, protocol.c, features.c, decision.c, oneshot.c, selfcal.c, tsne.c, kmeans.c, rf_train.c) is built
with the MCU sizes into build/c/librt.so; the PC side is src/pc/protocol.py, so both ends are checked together.

Part 1, parser (results/rt_parser_check.csv): a stream of sample / control packets built by protocol.py from
subject 0's raw EMG is damaged on purpose: 2% of the packets get one byte flipped (header, payload or CRC), 1% are
dropped, 2% are followed by 1-20 random garbage bytes, and the stream is cut into random chunks of 1-300 bytes.
Every intact packet must be delivered (in order, with its sequence number) and no damaged packet may get through,
for the C parser (pk_feed) and for the Python decoder.

Part 2, end to end (results/rt_replay.csv, rt_summary.csv): per subject x seed the raw recordings (int16 at
0.25 uV, as the PC forwarder sends them) go through rt_rx() exactly as over the serial link: per recording
STREAM_RESET then the samples; calibration: CAL_START(label) for each of the 6 calibration recordings, then
CALIBRATE and rt_idle() (one-shot model built on the "MCU"); test: the 11 blocks. warmup = 9 windows after
every reset, so windows 9..18 of each 2 s recording are used, as upstream. Self-calibration runs in rt_idle()
after every 300 pushed windows; to model it running in the background, rt_idle() is called only after D more
windows have arrived (D = 0, 20, 50: windows classified meanwhile are not buffered). Accuracy per block is
taken from the PK_PRED packets the MCU sends for every window, decoded by protocol.py, and compared (paired,
Wilcoxon over 20 subjects) with check_oneshot_c.py (same firmware fed with the upstream float features).
Usage (in the container): PYTHONPATH=src python src/check_rt.py
"""
import ctypes
import os
import random
import subprocess
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.stats import wilcoxon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pc'))
import check_oneshot_c as C  # noqa: E402
import pipeline as P  # noqa: E402
import protocol as PR  # noqa: E402

CSRC = os.path.join(P.ROOT, 'src', 'c')
LIB = os.path.join(P.ROOT, 'build', 'c', 'librt.so')
OUT = os.path.join(P.ROOT, 'results')
SRC = ['rt.c', 'protocol.c', 'features.c', 'decision.c', 'oneshot.c', 'selfcal.c', 'tsne.c', 'kmeans.c', 'rf_train.c']
HANDLER = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint8, ctypes.c_uint16, ctypes.c_void_p, ctypes.c_uint16)
TX = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint32)
ERASE = ctypes.CFUNCTYPE(ctypes.c_int)
NOW = ctypes.CFUNCTYPE(ctypes.c_uint32)
DELAYS = [0, 20, 50]


class Parser(ctypes.Structure):
    _fields_ = [('raw', ctypes.c_uint8 * (9 + 512)), ('n', ctypes.c_uint16), ('need', ctypes.c_uint16),
                ('ok', ctypes.c_uint32), ('crc_errors', ctypes.c_uint32), ('len_errors', ctypes.c_uint32),
                ('skipped_bytes', ctypes.c_uint32)]


class Config(ctypes.Structure):
    _fields_ = [('pre', ctypes.c_void_p), ('writer', ctypes.c_void_p), ('image', ctypes.c_void_p),
                ('flash_erase', ERASE), ('flash_flush', ERASE), ('tx', TX), ('now_us', NOW),
                ('warmup', ctypes.c_uint16), ('tau_permille', ctypes.c_uint16), ('k', ctypes.c_uint8),
                ('seed', ctypes.c_uint32)]


class Counters(ctypes.Structure):
    _fields_ = [(k, ctypes.c_uint32) for k in ['windows', 'windows_used', 'pushed', 'classified_only', 'commands',
                                               'lost_packets', 'seq_gaps', 'cal_windows', 'selfcal_blocks']] + \
               [('calibrate_result', ctypes.c_int32)]


def build(cc='gcc'):
    src = [os.path.join(CSRC, f) for f in SRC]
    deps = src + [s[:-1] + 'h' for s in src]
    if not os.path.exists(LIB) or os.path.getmtime(LIB) < max(os.path.getmtime(s) for s in deps):
        os.makedirs(os.path.dirname(LIB), exist_ok=True)
        subprocess.run([cc, '-O2', '-std=c99', '-Wall', '-fPIC', '-shared', '-o', LIB] + src + ['-lm'], check=True)
    lib = ctypes.CDLL(LIB)
    lib.pk_feed.argtypes = [ctypes.POINTER(Parser), ctypes.c_void_p, ctypes.c_uint32, HANDLER, ctypes.c_void_p]
    lib.rt_init.argtypes = [ctypes.POINTER(Config)]
    lib.rt_rx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    lib.rt_counters.restype = ctypes.POINTER(Counters)
    return lib


# ---------------------------------------------------------------- part 1: parser
def damaged_stream(seed=0, n_packets=3000):
    rng = random.Random(seed)
    raw = np.load(os.path.join(P.REPO, 'dataset_arm_position', '0', 'calibration', 'data.npy'))
    frames = np.clip(np.round(np.concatenate([t.T for t in raw]) / PR.LSB_VOLT), -32768, 32767).astype(np.int16)
    enc = PR.Encoder()
    out, intact = bytearray(), []
    for i in range(n_packets):
        if i % 50 == 0:
            pkt = enc.control(PR.STREAM_RESET)
        else:
            f = frames[(i * 20) % (len(frames) - 20):][:20]
            pkt = enc.samples(f.tolist())
        ptype, seq = pkt[2], pkt[3] | (pkt[4] << 8)
        u = rng.random()
        if u < 0.01:
            continue                                            # dropped
        if u < 0.03:
            b = bytearray(pkt)
            k = rng.randrange(len(b))
            b[k] ^= 1 << rng.randrange(8)                       # one bit flipped: header, payload or CRC
            out += b
        else:
            out += pkt
            intact.append((ptype, seq))
        if rng.random() < 0.02:
            out += bytes(rng.randrange(256) for _ in range(rng.randint(1, 20)))
    return bytes(out), intact, rng


def check_parser(lib):
    rows = []
    for seed in range(5):
        stream, intact, rng = damaged_stream(seed)
        got = []
        cb = HANDLER(lambda ctx, t, s, p, n: got.append((t, s)))
        ps = Parser()
        pos = 0
        while pos < len(stream):
            k = rng.randint(1, 300)
            chunk = stream[pos:pos + k]
            lib.pk_feed(ctypes.byref(ps), ctypes.c_char_p(chunk), len(chunk), cb, None)
            pos += k
        dec = PR.Decoder()
        py = []
        for i in range(0, len(stream), 97):
            py += [(t, s) for t, s, _ in dec.feed(stream[i:i + 97])]
        rows.append(dict(seed=seed, bytes=len(stream), intact=len(intact), c_delivered=len(got),
                         c_equal_intact=(got == intact), c_crc_errors=ps.crc_errors, c_len_errors=ps.len_errors,
                         c_skipped_bytes=ps.skipped_bytes, py_delivered=len(py), py_equal_intact=(py == intact),
                         py_crc_errors=dec.crc_errors))
        print(rows[-1], flush=True)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- part 2: end to end
def recordings(subject, folder):
    raw = np.load(os.path.join(P.REPO, 'dataset_arm_position', str(subject), folder, 'data.npy'))
    lab = np.load(os.path.join(P.REPO, 'dataset_arm_position', str(subject), folder, 'label.npy')).astype(int)
    q = np.clip(np.round(raw / PR.LSB_VOLT), -32768, 32767).astype('<i2')       # trials x 8 x 4000
    return [np.ascontiguousarray(t.T) for t in q], lab


def sample_bytes(enc, frames):
    out = bytearray()
    for i in range(0, len(frames), PR.FRAMES_PER_PACKET):
        out += enc.packet(PR.SAMPLES, frames[i:i + PR.FRAMES_PER_PACKET].tobytes())
    return bytes(out)


def run(subject, seed, delay):
    lib = build()
    _, arrs = C.pre_trees()
    tab = C.table_struct(arrs)
    flash = np.full(C.CAP, 0xFF, dtype=np.uint8)
    written = np.zeros(C.CAP, dtype=bool)

    def write(_ctx, off, src, n):
        if off + n > C.CAP or written[off:off + n].any():
            return -1
        flash[off:off + n] = np.frombuffer(ctypes.string_at(src, n), dtype=np.uint8)
        written[off:off + n] = True
        return 0
    wcb = C.WRITE_FN(write)
    w = C.Writer(wcb, None, C.CAP)
    dec = PR.Decoder()
    preds, status = [], []

    def tx(ptr, n):
        for t, _, p in dec.feed(ctypes.string_at(ptr, n)):
            m = PR.parse_mcu(t, p)
            (preds if m['kind'] == 'pred' else status).append(m)
    txcb = TX(tx)
    cfg = Config(ctypes.addressof(tab), ctypes.addressof(w), flash.ctypes.data, ERASE(0), ERASE(0), txcb, NOW(0),
                 9, 0, 1, seed * 1000 + subject + 7)
    lib.rt_init(ctypes.byref(cfg))
    enc = PR.Encoder()

    def send(b):
        lib.rt_rx(ctypes.c_char_p(b), len(b))
    send(enc.control(PR.SET_REPORT, 1))
    recs, lab = recordings(subject, 'calibration')
    for frames, y in zip(recs, lab):
        send(enc.control(PR.STREAM_RESET) + enc.control(PR.CAL_START, int(y)) + sample_bytes(enc, frames)
             + enc.control(PR.CAL_END))
    send(enc.control(PR.CALIBRATE))
    lib.rt_idle()
    cnt = lib.rt_counters().contents
    assert cnt.calibrate_result == 0 and cnt.cal_windows == 60, (cnt.calibrate_result, cnt.cal_windows)
    rows, pending_since = [], None
    for b in range(P.N_BLOCKS):
        recs, lab = recordings(subject, f'testing_block{b}')
        start = len(preds)
        for frames, y in zip(recs, lab):
            send(enc.control(PR.STREAM_RESET) + sample_bytes(enc, frames))
            c = lib.rt_counters().contents
            if c.pushed and c.pushed // 300 > c.selfcal_blocks:        # a self-calibration is due
                if pending_since is None:
                    pending_since = c.classified_only
                if c.classified_only - pending_since >= delay:
                    lib.rt_idle()
                    pending_since = None
        p = preds[start:]
        y = np.repeat(lab, 10)
        assert len(p) == len(y), (len(p), len(y))
        cls = np.array([q['class_id'] for q in p])
        rows.append(dict(subject=subject, seed=seed, delay=delay, block=b, acc=np.mean(cls == y),
                         not_buffered=int(sum(1 - q['pushed'] for q in p))))
    c = lib.rt_counters().contents
    for r in rows:
        r.update(lost_packets=c.lost_packets, selfcal_blocks=c.selfcal_blocks)
    return rows


def main():
    lib = build()
    pr = check_parser(lib)
    pr.to_csv(os.path.join(OUT, 'rt_parser_check.csv'), index=False)
    import check_rt as M
    res = Parallel(n_jobs=20, verbose=5)(delayed(M.run)(s, sd, d) for d in DELAYS for sd in [0, 1, 2]
                                         for s in range(20))
    df = pd.DataFrame([r for rr in res for r in rr])
    df.to_csv(os.path.join(OUT, 'rt_replay.csv'), index=False, float_format='%.4f')
    ref = pd.read_csv(os.path.join(OUT, 'oneshot_c_check.csv')).groupby('subject').acc_selfcal.mean() * 100
    rows = []
    for d in DELAYS:
        g = df[df.delay == d]
        a = g.groupby('subject').acc.mean() * 100
        x = a - ref
        per_seed = g.groupby('seed').acc.mean() * 100
        rows.append(dict(delay_windows=d, acc=a.mean(), seed_min=per_seed.min(), seed_max=per_seed.max(),
                         ref_float_features=ref.mean(), diff=x.mean(), better=int((x > 0).sum()),
                         worse=int((x < 0).sum()), p=wilcoxon(a, ref).pvalue,
                         not_buffered_per_block=g.not_buffered.mean()))
    s = pd.DataFrame(rows)
    s.to_csv(os.path.join(OUT, 'rt_summary.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 200)
    print(pr.to_string(index=False))
    print(s.round(3).to_string(index=False))


if __name__ == '__main__':
    main()
