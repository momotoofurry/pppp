"""LDA main line on the board (report 35.14): recorded raw EMG streamed to the NUCLEO-H753ZI over the ST-LINK
virtual COM port in real time; the board (src/c/app_rt_lda.c = rt_lda.c on board_hal.c) buffers the cued start-up
windows, fits the LDA, classifies and sends packets back. Then the same byte stream through the PC build of
rt_lda.c for comparison. Exploratory; the frozen firmware is restored afterwards.

  make    build/board_replay_lda/stream.bin + schedule.csv (end byte offset and send time of every packet) and
          windows.csv (every scored window: block, recording, label, MCU window counter, index of the packet that
          completes it). Subject 0, as check_rt_lda.py: SET_REPORT 1; the 6 calibration recordings, each
          STREAM_RESET + LABEL_START(gesture) + 4000 samples + LABEL_END; FIT; a pause; then per test block the
          first two recordings of every gesture labelled the same way (120 windows), FIT, a pause, and the other
          recordings of the block (STREAM_RESET + samples). int16 at 0.25 uV, 20 frames per packet, sent at 2 kHz.
  (send)  src/pc/serial_replay.ps1 on Windows.
  decode  parse rx.bin; per scored window the board's class / accepted / margin; the same stream through the PC
          rt_lda.c (rtl_idle after every packet); agreement, accuracy, commands, status events (fit result and
          duration, lost packets, diagnostics), and the latency = time the PRED packet arrived - time the packet
          completing the window was sent (PC clock, both ends).
          Writes results/board_replay_lda_windows.csv and board_replay_lda_summary.csv.
  --task  (report 35.25) task labels: per block only the FIRST recording of every gesture is the cued start-up
          sequence (one pass, 60 windows); after every other recording the robot side's RTL_TASK_LABEL (expected =
          the recording's gesture with probability 0.8, else a random other one; valid = expected + two random
          others; as check_rt_task.py) and a pause of TASK_PAUSE s. decode then also compares the RTL_EV_TASK
          values (argmax of the soft label and floor(999 q)) of board and PC and reports the update times.
Usage (in the container): python src/board_replay_lda.py make [--blocks 3] [--task --tag _task]; ... decode
"""
import argparse
import ctypes
import os
import struct
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pc'))
import check_rt_lda as CR  # noqa: E402
import pipeline as P  # noqa: E402
import protocol as PR  # noqa: E402

D = os.path.join(P.ROOT, 'build', 'board_replay_lda')
OUT = os.path.join(P.ROOT, 'results')
TAG = ''
SUBJECT = 0
FS = 2000.0
WIN_PER_REC = 19
PAUSE = 0.5                                              # after FIT: the fit runs in the main loop
EV = {1: 'fit', 3: 'lost', 4: 'label_full', 9: 'diag_rx_hw', 10: 'diag_stack', 11: 'diag_rx_ovf', 12: 'diag_rx_err',
      16: 'forgot', 17: 'fit_us', 18: 'task', 19: 'task_us'}
TASK = False
TASK_PAUSE = 0.05


def make(blocks):
    enc = PR.Encoder()
    out, wins, t, rec_no = [], [], 0.0, 0

    def recording(rec, label=None, meta=None):
        nonlocal t, rec_no
        out.append((CR.ctl(enc, PR.STREAM_RESET), t))
        if label is not None:
            out.append((CR.ctl(enc, CR.LABEL_START, bytes([int(label)])), t))
        frames = np.ascontiguousarray(rec.T)
        first = len(out)
        for i in range(0, len(frames), PR.FRAMES_PER_PACKET):
            t += PR.FRAMES_PER_PACKET / FS
            out.append((enc.packet(PR.SAMPLES, frames[i:i + PR.FRAMES_PER_PACKET].tobytes()), t))
        if label is not None:
            out.append((CR.ctl(enc, CR.LABEL_END), t))
        elif meta is not None:
            for k in range(9, WIN_PER_REC):              # window k is complete after 400 + 200 k samples
                pkt = first + (400 + 200 * k) // PR.FRAMES_PER_PACKET - 1
                wins.append(dict(**meta, win=k, window=rec_no * WIN_PER_REC + k + 1, packet=pkt))
        rec_no += 1

    def fit():
        nonlocal t
        out.append((CR.ctl(enc, CR.FIT), t))
        t += PAUSE

    out.append((CR.ctl(enc, CR.SET_REPORT, bytes([1])), t))
    rng = np.random.default_rng(SUBJECT)
    q, lab = CR.recordings(SUBJECT, 'calibration')
    for rec, y in zip(q, lab):
        recording(rec, y)
    fit()
    for b in range(blocks):
        q, lab = CR.recordings(SUBJECT, f'testing_block{b}')
        anc = np.sort(np.concatenate([np.flatnonzero(lab == c)[:1 if TASK else 2] for c in range(6)]))
        for r in anc:
            recording(q[r], lab[r])
        fit()
        for r in np.setdiff1d(np.arange(len(lab)), anc):
            recording(q[r], None, dict(block=b, rec=int(r), label=int(lab[r])))
            if TASK:
                g = int(lab[r])
                e = g if (g < 5 and rng.random() < 0.8) else int(rng.choice([c for c in range(5) if c != g]))
                mask = (1 << e) | sum(1 << int(c) for c in rng.choice([c for c in range(5) if c != e], 2, replace=False))
                out.append((CR.ctl(enc, 12, bytes([e, mask])), t))
                t += TASK_PAUSE
    os.makedirs(D, exist_ok=True)
    with open(os.path.join(D, 'stream.bin'), 'wb') as fh:
        fh.write(b''.join(p for p, _ in out))
    ends = np.cumsum([len(p) for p, _ in out])
    pd.DataFrame(dict(end=ends, t=[x for _, x in out])).to_csv(os.path.join(D, 'schedule.csv'), index=False,
                                                                float_format='%.4f')
    pd.DataFrame(wins).to_csv(os.path.join(D, 'windows.csv'), index=False)
    print(f'{len(out)} packets, {ends[-1]} bytes, {out[-1][1]:.1f} s, {len(wins)} scored windows -> {D}')


def parse(data):
    dec = PR.Decoder()
    preds, cmds, status, ends = {}, [], [], []
    pos = 0
    for i in range(0, len(data), 64):                    # small chunks: the byte offset of every packet end
        for t, _, p in dec.feed(data[i:i + 64]):
            pos += PR.OVERHEAD + len(p)
            if t == PR.PRED:
                w, tus, cls, acc, m = struct.unpack('<IIBBH', p[:12])
                preds[w] = dict(cls=cls, accepted=acc, margin=m, t_us=tus, end=pos + dec.skipped)
            elif t == PR.COMMAND:
                w, tus, cmd, cls, m = struct.unpack('<IIBBH', p[:12])
                cmds.append((w, cmd))
            elif t == PR.STATUS:
                ev, v = struct.unpack('<B3xi', p[:8])
                status.append((EV.get(ev, ev), v))
    return preds, cmds, status, dec


def pc_run():
    lib = CR.build()
    got = bytearray()
    txcb = CR.TX(lambda ptr, n: got.extend(ctypes.string_at(ptr, n)))
    cfg = CR.Config(txcb, CR.NOW(0), 9, 0, 0, 3)
    lib.rtl_init(ctypes.byref(cfg))
    stream = open(os.path.join(D, 'stream.bin'), 'rb').read()
    sched = pd.read_csv(os.path.join(D, 'schedule.csv'))
    start = 0
    for end in sched.end:
        b = stream[start:end]
        lib.rtl_rx(ctypes.c_char_p(b), len(b))
        lib.rtl_idle()
        start = end
    return bytes(got)


def decode():
    wins = pd.read_csv(os.path.join(D, 'windows.csv'))
    rx = open(os.path.join(D, 'rx.bin'), 'rb').read()
    bp, bc, bs, bdec = parse(rx)
    pp, pc, ps, _ = parse(pc_run())
    rxl = pd.read_csv(os.path.join(D, 'rx_log.csv'))
    txl = pd.read_csv(os.path.join(D, 'tx_log.csv')).set_index('packet').ms
    rows = []
    for w in wins.itertuples():
        b, p = bp.get(w.window), pp.get(w.window)
        row = dict(block=w.block, rec=w.rec, label=w.label, win=w.win, window=w.window,
                   board=b['cls'] if b else -1, pc=p['cls'] if p else -1,
                   board_accepted=b['accepted'] if b else -1, board_margin=b['margin'] if b else -1,
                   pc_margin=p['margin'] if p else -1)
        if b:
            arrive = rxl.ms[np.searchsorted(rxl.end.values, b['end'])]
            row['latency_ms'] = arrive - txl[w.packet]
        rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, f'board_replay_lda{TAG}_windows.csv'), index=False, float_format='%.3f')
    ok = df[df.board >= 0]
    sm = dict(scored_windows=len(df), received=len(ok), same_class_as_pc=int((ok.board == ok.pc).sum()),
              same_margin_as_pc=int((ok.board_margin == ok.pc_margin).sum()),
              margin_max_diff=int((ok.board_margin - ok.pc_margin).abs().max()),
              acc_board=(ok.board == ok.label).mean() * 100, acc_pc=(df.pc == df.label).mean() * 100,
              commands_board=len(bc), commands_pc=len(pc), commands_equal=bc == pc,
              latency_p50=ok.latency_ms.median(), latency_p95=ok.latency_ms.quantile(0.95),
              latency_max=ok.latency_ms.max(), rx_crc_errors=bdec.crc_errors, rx_skipped=bdec.skipped)
    fits = [v for e, v in bs if e == 'fit']
    fus = [v for e, v in bs if e == 'fit_us']
    sm.update(fits=len(fits), fits_ok=int(sum(v == 0 for v in fits)), fit_us_min=min(fus), fit_us_max=max(fus),
              lost_packets=int(sum(v for e, v in bs if e == 'lost')),
              pc_fits_ok=int(sum(v == 0 for e, v in ps if e == 'fit')))
    if TASK:
        bt, pt = [v for e, v in bs if e == 'task'], [v for e, v in ps if e == 'task']
        tus = [v for e, v in bs if e == 'task_us']
        sm.update(task_events_board=len(bt), task_events_pc=len(pt), task_values_equal=bt == pt,
                  task_updates_board=int(sum(v >= 0 for v in bt)), task_none_board=int(sum(v == -1 for v in bt)),
                  task_us_min=min(tus) if tus else -1, task_us_median=float(np.median(tus)) if tus else -1,
                  task_us_max=max(tus) if tus else -1)
    for e in ('diag_rx_hw', 'diag_stack', 'diag_rx_ovf', 'diag_rx_err'):
        v = [x for k, x in bs if k == e]
        sm[e + '_max'] = max(v) if v else -1
    pd.DataFrame([sm]).T.to_csv(os.path.join(OUT, f'board_replay_lda{TAG}_summary.csv'), header=['value'])
    for k, v in sm.items():
        print(f'{k:22s} {v}')
    print(df.groupby('block').apply(lambda g: pd.Series(dict(n=len(g), acc_board=(g.board == g.label).mean() * 100,
                                                             acc_pc=(g.pc == g.label).mean() * 100))).round(2).to_string())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['make', 'decode'])
    ap.add_argument('--blocks', type=int, default=3)
    ap.add_argument('--tag', default='', help='e.g. _all: build/board_replay_lda_all, results/board_replay_lda_all_*')
    ap.add_argument('--task', action='store_true')
    args = ap.parse_args()
    global D, TAG, TASK
    D, TAG, TASK = D + args.tag, args.tag, args.task
    make(args.blocks) if args.mode == 'make' else decode()


if __name__ == '__main__':
    main()
