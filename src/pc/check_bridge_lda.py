"""Check what TrignoBridge.exe --firmware lda sent (run --port file:<bytes>, against fake_tcu.py; report 35.29): parse
every packet, list the LDA control packets (SET_GATE, TASK_LABEL, FORGET) with their payloads, then feed all packets
in order to the PC build of rt_lda.c (rtl_idle after every control packet, as the board's main loop) and score the
PRED of every test recording against its label (segments.csv).
Usage (in the container): python src/pc/check_bridge_lda.py <dir with bridge_out.bin and segments.csv>
"""
import ctypes
import os
import struct
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import check_rt_lda as R  # noqa: E402
import protocol as PR  # noqa: E402

NAMES = {11: 'FORGET', 12: 'TASK_LABEL', 13: 'SET_GATE'}
EV = {1: 'fit', 4: 'label_full', 16: 'forgot', 17: 'fit_us', 18: 'task', 19: 'task_us', 20: 'gate_thr_nV'}


def main():
    d = sys.argv[1]
    raw = open(os.path.join(d, 'bridge_out.bin'), 'rb').read()
    seg = pd.read_csv(os.path.join(d, 'segments.csv'))
    dec = PR.Decoder()
    pk = dec.feed(raw)
    print(f'{len(raw)} bytes, {len(pk)} packets, crc errors {dec.crc_errors}, skipped {dec.skipped}')
    ctl = [p for t, _, p in pk if t == PR.CONTROL]
    print('control sub-commands:', pd.Series([p[0] for p in ctl]).value_counts().sort_index().to_dict())
    for p in ctl:
        if p[0] in NAMES:
            extra = f', window {struct.unpack("<I", p[3:7])[0]}' if p[0] == 12 and len(p) >= 7 else ''
            print(f'  {NAMES[p[0]]}: payload {list(p)}{extra}')
    lib = R.build()
    out = PR.Decoder()
    preds, status, cmds = [], [], []

    def tx(ptr, n):
        for t, _, p in out.feed(ctypes.string_at(ptr, n)):
            if t == PR.PRED:
                preds.append(struct.unpack('<IIBBHB', p[:13]))
            elif t == PR.STATUS:
                status.append(struct.unpack('<B3xi', p[:8]))
            elif t == PR.COMMAND:
                cmds.append(p)
    txcb = R.TX(tx)
    cfg = R.Config(txcb, R.NOW(0), 9, 0, 0, 3)
    lib.rtl_init(ctypes.byref(cfg))
    enc = PR.Encoder()
    for t, _, p in pk:
        b = enc.packet(t, p)
        lib.rtl_rx(ctypes.c_char_p(b), len(b))
        if t == PR.CONTROL:
            lib.rtl_idle()
    print('status events:', [(EV.get(e, e), v) for e, v in status if e != 3])
    test = seg[seg.kind != 'calibration'].reset_index(drop=True)
    n_rec = len(preds) // 10
    lab = [int(test.label[i // 10]) for i in range(n_rec * 10)]
    ok = sum(int(p[2] == y) for p, y in zip(preds, lab))
    gated = sum(p[5] for p in preds)
    print(f'PRED {len(preds)} ({n_rec} test recordings x 10), accuracy {ok / max(1, len(lab)) * 100:.2f} %, '
          f'gated windows {gated}, commands {len(cmds)}')


if __name__ == '__main__':
    main()
