"""Board (rtl_task_s7b on the NUCLEO-H753ZI) vs the PC build of the same firmware, on the same bytes (bridge_out.bin of
the S7 end-to-end run): every PRED (window, class, gated), every COMMAND, the status events (fit, gate threshold).
usage (container): python src/pc/board_cmp_s7.py <run dir>   (report 35.80; board_rx.bin from board_send_s7.ps1)"""
import ctypes
import os
import struct
import subprocess
import sys

sys.path.insert(0, '/work/src')
sys.path.insert(0, '/work/src/pc')
import check_rt_lda as R  # noqa: E402
import protocol as PR  # noqa: E402

LIB9 = '/work/build/c/librtl9.so'
EV = {1: 'fit', 3: 'lost', 4: 'label_full', 17: 'fit_us', 20: 'gate_thr_nV', 9: 'rx_hw', 10: 'stack', 11: 'rx_ovf',
      12: 'rx_err'}


def build9():
    src = [os.path.join(R.CSRC, f) for f in R.SRC]
    deps = src + [s[:-1] + 'h' for s in src]
    if not os.path.exists(LIB9) or os.path.getmtime(LIB9) < max(os.path.getmtime(s) for s in deps):
        subprocess.run(['gcc', '-O2', '-std=c99', '-Wall', '-Wextra', '-fPIC', '-shared', '-o', LIB9,
                        '-DLD_CLASSES=9', '-DDC_CLASSES=9', '-DRTL_LABEL_MAX=810'] + src + ['-lm'], check=True)
    lib = ctypes.CDLL(LIB9)
    lib.rtl_init.argtypes = [ctypes.POINTER(R.Config)]
    lib.rtl_rx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    lib.rtl_idle.restype = None
    return lib


def parse(raw):
    preds, cmds, st = [], [], []
    for t, _, p in PR.Decoder().feed(raw):
        if t == PR.PRED:
            w, _, cls, acc, mg, gt = struct.unpack('<IIBBHB', p[:13])
            preds.append((w, cls, gt, mg))
        elif t == PR.COMMAND:
            w, _, cmd, cls, mg = struct.unpack('<IIBBH', p[:12])
            cmds.append((w, cmd, cls))
        elif t == PR.STATUS:
            st.append(struct.unpack('<B3xi', p[:8]))
    return preds, cmds, st


def main():
    d = sys.argv[1]
    raw = open(os.path.join(d, 'bridge_out.bin'), 'rb').read()
    lib = build9()
    out = bytearray()

    def tx(ptr, n):
        out.extend(ctypes.string_at(ptr, n))
    txcb = R.TX(tx)
    cfg = R.Config(txcb, R.NOW(0), 9, 0, 0, 3)          # app_rt_lda.c: warm-up 9, k 3 until SET_REJECT
    lib.rtl_init(ctypes.byref(cfg))
    for t, seq, p in PR.Decoder().feed(raw):
        b = PR.build(t, seq, p)
        lib.rtl_rx(ctypes.c_char_p(b), len(b))
        if t == PR.CONTROL:
            lib.rtl_idle()
    pc_p, pc_c, pc_s = parse(bytes(out))
    bd_raw = open(os.path.join(d, 'board_rx.bin'), 'rb').read()
    dec = PR.Decoder()
    dec.feed(bd_raw)
    bd_p, bd_c, bd_s = parse(bd_raw)
    print(f'board bytes {len(bd_raw)}, packets ok {dec.ok}, crc errors {dec.crc_errors}')
    print('board status:', [(EV.get(e, e), v) for e, v in bd_s])
    print('PC status   :', [(EV.get(e, e), v) for e, v in pc_s])
    print(f'PRED: board {len(bd_p)}, PC {len(pc_p)}')
    print(f'  identical (window, class, gated, margin): {bd_p == pc_p}')
    if bd_p != pc_p:
        n = min(len(bd_p), len(pc_p))
        diff = [i for i in range(n) if bd_p[i][:3] != pc_p[i][:3]]
        print(f'  class/gate differences {len(diff)} of {n}; margin within 1: '
              f'{sum(abs(a[3] - b[3]) <= 1 for a, b in zip(bd_p, pc_p))}/{n}; first {diff[:5]}')
        for i in diff[:5]:
            print('   board', bd_p[i], 'pc', pc_p[i])
    print(f'COMMAND: board {len(bd_c)}, PC {len(pc_c)}, identical {bd_c == pc_c}')


main()
