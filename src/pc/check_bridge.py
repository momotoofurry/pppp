"""Check what TrignoBridge.exe sent (run --port file:<bytes>, against fake_tcu.py): parse every packet, feed them in
order to the PC build of rt.c (firmware v2, as src/board_replay.py: same seed, warmup 9, self-calibration when due)
and score the PRED of every test recording against its label (segments.csv). Also checks the sample count
per recording (2000 Hz after the bridge) and the packet integrity.
Usage (in the container): python src/pc/check_bridge.py <dir with bridge_out.bin and segments.csv>
"""
import ctypes
import os
import subprocess
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import board_replay as B  # noqa: E402
import check_oneshot_c as C  # noqa: E402
import check_rt as R  # noqa: E402
import protocol as PR  # noqa: E402


def main():
    d = sys.argv[1]
    raw = open(os.path.join(d, 'bridge_out.bin'), 'rb').read()
    seg = pd.read_csv(os.path.join(d, 'segments.csv'))
    dec = PR.Decoder()
    pk = dec.feed(raw)
    print(f'{len(raw)} bytes, {len(pk)} packets, crc errors {dec.crc_errors}, skipped {dec.skipped}')
    src = [os.path.join(R.CSRC, f) for f in B.SRC]             # firmware v2, as board_replay.pc_reference
    subprocess.run(['gcc', '-O2', '-std=c99', '-Wall', '-fPIC', '-shared', '-DSC_EMBED=0', '-DRT_ADAPT=1', '-o', B.LIB]
                   + src + ['-lm'], check=True)
    lib = ctypes.CDLL(B.LIB)
    lib.rt_init.argtypes = [ctypes.POINTER(R.Config)]
    lib.rt_rx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    lib.rt_counters.restype = ctypes.POINTER(R.Counters)
    _, arrs = C.pre_trees()
    tab = C.table_struct(arrs)
    flash = np.full(C.CAP, 0xFF, dtype=np.uint8)

    def write(_ctx, off, src, n):
        flash[off:off + n] = np.frombuffer(ctypes.string_at(src, n), dtype=np.uint8)
        return 0
    wcb = C.WRITE_FN(write)
    w = C.Writer(wcb, None, C.CAP)
    out_dec, msgs = PR.Decoder(), []
    cur = [-1]

    def tx(ptr, n):
        for t, _, p in out_dec.feed(ctypes.string_at(ptr, n)):
            m = PR.parse_mcu(t, p)
            m['segment'] = cur[0]
            msgs.append(m)
    txcb = R.TX(tx)
    cfg = R.Config(ctypes.addressof(tab), ctypes.addressof(w), flash.ctypes.data, R.ERASE(0), R.ERASE(0), txcb,
                   R.NOW(0), B.WARMUP, 600, 3, B.SEED)
    lib.rt_init(ctypes.byref(cfg))
    frames_per_seg = {}
    for t, s, p in pk:
        if t == PR.CONTROL and p[0] == PR.STREAM_RESET:
            cur[0] += 1
        if t == PR.SAMPLES:
            frames_per_seg[cur[0]] = frames_per_seg.get(cur[0], 0) + len(p) // 16
        b = PR.build(t, s, p)
        lib.rt_rx(ctypes.c_char_p(b), len(b))
        c = lib.rt_counters().contents
        if t == PR.CONTROL and p[0] == PR.CALIBRATE:
            lib.rt_idle()
        elif c.pushed and c.pushed // 300 > c.selfcal_blocks:
            lib.rt_idle()
    st = [m for m in msgs if m['kind'] == 'status']
    print('status events:', [(m['event'], m['value']) for m in st])
    preds = pd.DataFrame([m for m in msgs if m['kind'] == 'pred'])
    test = seg[seg.kind == 'testing_block0']
    lab = dict(zip(test.segment, test.label))
    p = preds[preds.segment.isin(lab)]
    acc = (p.class_id == p.segment.map(lab)).mean() * 100
    fps = pd.Series(frames_per_seg)
    print(f'test windows {len(p)} (expected {10 * len(test)}), accuracy {acc:.2f}%')
    print(f'frames per recording after the bridge: min {fps.min()}, max {fps.max()} (4000 = 2 s at 2000 Hz)')


if __name__ == '__main__':
    main()
