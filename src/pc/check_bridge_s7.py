"""Check what TrignoBridge.exe --firmware lda --classes 9 --preset s7 sent (report 35.80): parse every packet, list the
LDA settings, feed all packets in order to the PC build of the 9-class rt_lda.c (rtl_idle after every control packet,
as the board's main loop) and score the commands of the probe cues (cues.csv of fake_tcu_s7.py).
usage (container): python src/pc/check_bridge_s7.py <run dir>   (report 35.80)"""
import ctypes
import os
import struct
import sys
from collections import Counter

import numpy as np
import pandas as pd

sys.path.insert(0, '/work/src')
sys.path.insert(0, '/work/src/pc')
import check_rt_lda as R  # noqa: E402
import protocol as PR  # noqa: E402

import subprocess  # noqa: E402

LIB9 = '/work/build/c/librtl9.so'


def build9():
    """the 9-class host build of check_rt_s7.py (same flags)"""
    src = [os.path.join(R.CSRC, f) for f in R.SRC]
    deps = src + [s[:-1] + 'h' for s in src]
    if not os.path.exists(LIB9) or os.path.getmtime(LIB9) < max(os.path.getmtime(s) for s in deps):
        subprocess.run(['gcc', '-O2', '-std=c99', '-Wall', '-Wextra', '-fPIC', '-shared', '-o', LIB9,
                        '-DLD_CLASSES=9', '-DDC_CLASSES=9', '-DRTL_LABEL_MAX=810'] + src + ['-lm'], check=True)
    lib = ctypes.CDLL(LIB9)
    lib.rtl_init.argtypes = [ctypes.POINTER(R.Config)]
    lib.rtl_rx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    lib.rtl_idle.restype = None
    lib.rtl_counters.restype = ctypes.POINTER(R.Counters)
    return lib

NAMES = {1: 'STREAM_RESET', 2: 'LABEL_START', 3: 'LABEL_END', 4: 'FIT', 5: 'SET_REJECT', 6: 'SET_REPORT',
         13: 'SET_GATE', 14: 'SET_CLASSES'}
G9 = ['WristExt', 'WristFlex', 'RadialDev', 'UlnarDev', 'Point', 'ThumbUp', 'HandOpen', 'Fist', 'Rest']


def main():
    d = sys.argv[1]
    raw = open(os.path.join(d, 'bridge_out.bin'), 'rb').read()
    cues = pd.read_csv(os.path.join(d, 'cues.csv'))
    dec = PR.Decoder()
    pk = dec.feed(raw)
    print(f'{len(raw)} bytes, {len(pk)} packets, crc errors {dec.crc_errors}, skipped {dec.skipped}')
    ctl = [p for t, _, p in pk if t == PR.CONTROL]
    print('control sub-commands:', {NAMES.get(k, k): v for k, v in sorted(Counter(p[0] for p in ctl).items())})
    for p in ctl:
        if p[0] in (5, 13, 14):
            print(f'  {NAMES[p[0]]}: payload {list(p)}')
    lib = build9()
    out = PR.Decoder()
    frames = [0]
    preds, cmds, status = [], [], []

    def tx(ptr, n):
        for t, _, p in out.feed(ctypes.string_at(ptr, n)):
            if t == PR.PRED:
                w, _, cls, acc, mg, gt = struct.unpack('<IIBBHB', p[:13])
                preds.append((frames[0], cls, gt))
            elif t == PR.COMMAND:
                w, _, cmd, cls, _ = struct.unpack('<IIBBH', p[:12])
                cmds.append((frames[0], cls))
            else:
                status.append(struct.unpack('<B3xi', p[:8]))
    txcb = R.TX(tx)
    cfg = R.Config(txcb, R.NOW(0), 9, 0, 0, 3)          # app_rt_lda.c defaults: warm-up 9 windows, k 3 (until SET_REJECT)
    lib.rtl_init(ctypes.byref(cfg))
    for t, seq, p in pk:
        b = PR.build(t, seq, p)
        if t == PR.SAMPLES:
            frames[0] += len(p) // 16
        lib.rtl_rx(ctypes.c_char_p(b), len(b))
        if t == PR.CONTROL:
            lib.rtl_idle()
    c = lib.rtl_counters().contents
    ev = Counter(e for e, _ in status)
    fit = [v for e, v in status if e == 1]
    thr = [v for e, v in status if e == 20]
    print(f'frames {frames[0]} ({frames[0] / 2000:.1f} s), windows {c.windows}, label windows {c.label_windows}, '
          f'fits {c.fits} result {fit}, gate threshold {thr} nV, lost {c.lost_packets}')
    pc = Counter(cls for _, cls, _ in preds)
    print('predicted classes after the fit:', {G9[k]: v for k, v in sorted(pc.items())},
          f'gated {100 * np.mean([g for _, _, g in preds]):.1f} %')
    assert pc[4] == 0 and pc[5] == 0, 'Point / ThumbUp predicted: the class mask did not act'
    cc = Counter(cls for _, cls in cmds)
    print('commands:', {G9[k]: v for k, v in sorted(cc.items())})
    ok = wr = no = 0
    lat = []
    for r in cues.itertuples():
        g = G9.index(r.gesture)
        if g in (4, 5, 8):                         # Rest, and Point / ThumbUp (cued in a 9-gesture recording, not S7)
            continue
        sel = [(f, cls) for f, cls in cmds if r.start_s <= f / 2000 <= r.end_s + 0.5]
        if not sel:
            no += 1
            continue
        ok += sel[0][1] == g
        wr += sel[0][1] != g
        lat.append(1000 * (sel[0][0] / 2000 - r.start_s))
    n = ok + wr + no
    rest = [(f, cls) for f, cls in cmds if any(r.start_s - 1.0 + 0.5 <= f / 2000 <= r.start_s for r in cues.itertuples())]
    if os.environ.get('DETAIL'):
        for r in cues.itertuples():
            near = [(round(f / 2000 - r.start_s, 2), G9[cls]) for f, cls in cmds if -1.0 <= f / 2000 - r.start_s <= 4.0]
            gts = [round(f / 2000 - r.start_s, 1) for f, cls, gt in preds if 0 <= f / 2000 - r.start_s <= 2.5 and not gt]
            print(f'  {r.gesture:10s} {r.start_s:7.2f}-{r.end_s:7.2f}  cmds {near}  first ungated {gts[:1]}')
    print(f'probe 1 S7 cues {n}: right {ok}, wrong {wr}, none {no}; latency median {np.median(lat):.0f} ms; '
          f'commands in the 0.5 s before a cue (rest): {len(rest)}')


main()
