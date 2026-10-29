"""Route B on the board: recorded raw EMG streamed to the NUCLEO-H753ZI over the ST-LINK virtual COM port in real
time, the board (src/c/app_rt.c = rt.c on board_hal.c) does one-shot calibration, classification, decision and
self-calibration and sends packets back; then the same stream through the PC build of rt.c for comparison.

  make    build/board_replay/stream.bin + schedule.csv (end byte offset and send time of every packet) and
          windows.csv (every test window: block, recording, label, index of the packet that completes it), from
          subject 0 as check_rt.py: SET_REPORT 1; per calibration recording STREAM_RESET, CAL_START(label), the
          4000 samples, CAL_END; CALIBRATE; a 3 s pause (one-shot calibration and the Flash write run on the board);
          then --blocks test blocks, per recording STREAM_RESET + samples. Samples are int16 at 0.25 uV (protocol.py),
          20 frames per packet, sent at 2 kHz.
  (send)  src/pc/serial_replay.ps1 on Windows (System.IO.Ports, nothing to install): sends the packets at their
          times and records the received bytes with time stamps (rx.bin, rx_log.csv, tx_log.csv).
  decode  parse rx.bin (protocol.py); per test window the board's prediction, the accuracy per block, the commands,
          the status events (one-shot result, self-calibration blocks, lost packets), and the latency
          = time the PRED packet arrived - time the packet completing the window was sent (PC clock, both ends).
          Then the same stream through the PC rt.c (firmware v2: SC_EMBED = 0, RT_ADAPT = 1; same seed, warmup 9;
          self-calibration started --delay windows after it is due, the board runs it in the background) and the
          per-window agreement. Writes results/board_replay_windows.csv and results/board_replay_summary.csv.
Usage (in the container): python src/board_replay.py make [--blocks 2]; ... decode
"""
import argparse
import ctypes
import os
import subprocess
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pc'))
import check_oneshot_c as C  # noqa: E402
import check_rt as R  # noqa: E402
import pipeline as P  # noqa: E402
import protocol as PR  # noqa: E402

D = os.path.join(P.ROOT, 'build', 'board_replay')
OUT = os.path.join(P.ROOT, 'results')
LIB = os.path.join(P.ROOT, 'build', 'c', 'librt_v2.so')
SRC = ['rt.c', 'protocol.c', 'features.c', 'decision.c', 'oneshot.c', 'selfcal.c', 'kmeans.c', 'rf_train.c', 'adapt.c']
SEED = 0x2545F491                                       # app_rt.c
WARMUP = 9
FS = 2000.0
SUBJECT = 0


def packets(blocks):
    """[(bytes, t_s)] and the test windows"""
    enc = PR.Encoder()
    out, wins, t = [], [], 0.0
    out.append((enc.control(PR.SET_REPORT, 1), t))
    recs, lab = R.recordings(SUBJECT, 'calibration')
    for frames, y in zip(recs, lab):
        out += [(enc.control(PR.STREAM_RESET), t), (enc.control(PR.CAL_START, int(y)), t)]
        for i in range(0, len(frames), PR.FRAMES_PER_PACKET):
            t += PR.FRAMES_PER_PACKET / FS
            out.append((enc.packet(PR.SAMPLES, frames[i:i + PR.FRAMES_PER_PACKET].tobytes()), t))
        out.append((enc.control(PR.CAL_END), t))
    out.append((enc.control(PR.CALIBRATE), t))
    t += 3.0
    for b in range(blocks):
        recs, lab = R.recordings(SUBJECT, f'testing_block{b}')
        for r, (frames, y) in enumerate(zip(recs, lab)):
            out.append((enc.control(PR.STREAM_RESET), t))
            first = len(out)
            for i in range(0, len(frames), PR.FRAMES_PER_PACKET):
                t += PR.FRAMES_PER_PACKET / FS
                out.append((enc.packet(PR.SAMPLES, frames[i:i + PR.FRAMES_PER_PACKET].tobytes()), t))
            n_win = (len(frames) - 400) // 200 + 1
            for j in range(WARMUP, n_win):                  # window j ends with sample 200 j + 399
                wins.append(dict(block=b, rec=r, win=j, label=int(y),
                                 packet=first + (200 * j + 399) // PR.FRAMES_PER_PACKET))
    return out, pd.DataFrame(wins)


def make(blocks):
    pk, wins = packets(blocks)
    os.makedirs(D, exist_ok=True)
    off = 0
    with open(os.path.join(D, 'stream.bin'), 'wb') as fh:
        rows = []
        for b, t in pk:
            fh.write(b)
            off += len(b)
            rows.append((off, t))
    pd.DataFrame(rows, columns=['end', 't_s']).to_csv(os.path.join(D, 'schedule.csv'), index=False, float_format='%.4f')
    wins.to_csv(os.path.join(D, 'windows.csv'), index=False)
    print(f'{len(pk)} packets, {off} bytes, {rows[-1][1]:.1f} s; {len(wins)} test windows; {D}')


def pc_reference(blocks, delay):
    return run_stream(packets(blocks)[0], delay)[0]


def run_stream(pk, delay, lib_path=LIB, defines=()):
    """pk ([(bytes, t)]) through the PC build of rt.c -> (PRED messages, STATUS messages) as DataFrame / list"""
    src = [os.path.join(R.CSRC, f) for f in SRC]
    os.makedirs(os.path.dirname(lib_path), exist_ok=True)
    subprocess.run(['gcc', '-O2', '-std=c99', '-Wall', '-fPIC', '-shared', '-DSC_EMBED=0', '-DRT_ADAPT=1', *defines,
                    '-o', lib_path] + src + ['-lm'], check=True)
    lib = ctypes.CDLL(lib_path)
    lib.rt_init.argtypes = [ctypes.POINTER(R.Config)]
    lib.rt_rx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    lib.rt_counters.restype = ctypes.POINTER(R.Counters)
    _, arrs = C.pre_trees()
    tab = C.table_struct(arrs)
    flash = np.full(C.CAP, 0xFF, dtype=np.uint8)

    def write(_ctx, off, src_, n):
        flash[off:off + n] = np.frombuffer(ctypes.string_at(src_, n), dtype=np.uint8)
        return 0
    wcb = C.WRITE_FN(write)
    w = C.Writer(wcb, None, C.CAP)
    dec, preds, status = PR.Decoder(), [], []

    def tx(ptr, n):
        for t, _, p in dec.feed(ctypes.string_at(ptr, n)):
            m = PR.parse_mcu(t, p)
            if m['kind'] == 'pred':
                preds.append(m)
            elif m['kind'] == 'status':
                status.append(m)
    txcb = R.TX(tx)
    cfg = R.Config(ctypes.addressof(tab), ctypes.addressof(w), flash.ctypes.data, R.ERASE(0), R.ERASE(0), txcb,
                   R.NOW(0), WARMUP, 600, 3, SEED)
    lib.rt_init(ctypes.byref(cfg))
    pending = None
    for b, _ in pk:
        lib.rt_rx(ctypes.c_char_p(b), len(b))
        c = lib.rt_counters().contents
        if b[2] == PR.CONTROL and b[7] == PR.CALIBRATE:
            lib.rt_idle()
        elif c.pushed and c.pushed // 300 > c.selfcal_blocks:   # a self-calibration is due
            if pending is None:
                pending = c.windows
            if c.windows - pending >= delay:
                lib.rt_idle()
                pending = None
    return pd.DataFrame(preds), status


def decode(blocks, delay):
    wins = pd.read_csv(os.path.join(D, 'windows.csv'))
    rx = open(os.path.join(D, 'rx.bin'), 'rb').read()
    log = pd.read_csv(os.path.join(D, 'rx_log.csv'))             # end (bytes received so far), ms
    txl = pd.read_csv(os.path.join(D, 'tx_log.csv'))             # packet, ms (actual send time)
    dec, msgs, pos = PR.Decoder(), [], 0
    for end, ms in zip(log['end'], log['ms']):
        for t, _, p in dec.feed(rx[pos:end]):
            m = PR.parse_mcu(t, p)
            m['rx_ms'] = ms
            msgs.append(m)
        pos = end
    preds = [m for m in msgs if m['kind'] == 'pred']
    status = [m for m in msgs if m['kind'] == 'status']
    cmds = [m for m in msgs if m['kind'] == 'command']
    print('status events:', [(m['event'], m['value']) for m in status])
    print(f'received {len(rx)} bytes, {dec.ok} packets, crc errors {dec.crc_errors}, skipped {dec.skipped}; '
          f'{len(preds)} PRED (expected {len(wins)}), {len(cmds)} COMMAND')
    assert len(preds) == len(wins), (len(preds), len(wins))
    sent = dict(zip(txl['packet'], txl['ms']))
    wins['board'] = [m['class_id'] for m in preds]
    wins['board_pushed'] = [m['pushed'] for m in preds]
    wins['board_window'] = [m['window'] for m in preds]
    wins['latency_ms'] = [m['rx_ms'] - sent[k] for m, k in zip(preds, wins['packet'])]
    ref = pc_reference(blocks, delay)
    assert len(ref) == len(wins), (len(ref), len(wins))
    wins['pc'] = ref['class_id'].values
    wins['pc_window'] = ref['window'].values
    assert (wins.board_window == wins.pc_window).all()
    wins.to_csv(os.path.join(OUT, 'board_replay_windows.csv'), index=False, float_format='%.2f')
    rows = []
    for b, g in wins.groupby('block'):
        rows.append(dict(block=b, windows=len(g), board_acc=(g.board == g.label).mean() * 100,
                         pc_acc=(g.pc == g.label).mean() * 100, agree=(g.board == g.pc).mean() * 100,
                         not_buffered=int((g.board_pushed == 0).sum()), latency_ms_mean=g.latency_ms.mean(),
                         latency_ms_p95=g.latency_ms.quantile(0.95), latency_ms_max=g.latency_ms.max()))
    s = pd.DataFrame(rows)
    ev = {m['event']: m['value'] for m in status}
    s['calibrated'] = ev.get(PR.EV_CALIBRATED)
    s['selfcal_blocks'] = max([m['value'] for m in status if m['event'] == PR.EV_SELFCAL], default=0)
    s['lost_packets'] = sum(m['value'] for m in status if m['event'] == PR.EV_LOST)
    s['crc_errors'] = dec.crc_errors
    s['commands'] = len(cmds)
    s['pc_delay_windows'] = delay
    s.to_csv(os.path.join(OUT, 'board_replay_summary.csv'), index=False, float_format='%.3f')
    pd.set_option('display.width', 220)
    print(s.round(3).to_string(index=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['make', 'decode'])
    ap.add_argument('--blocks', type=int, default=2)
    ap.add_argument('--delay', type=int, default=1, help='PC reference: windows between due and self-calibration')
    args = ap.parse_args()
    make(args.blocks) if args.mode == 'make' else decode(args.blocks, args.delay)


if __name__ == '__main__':
    main()
