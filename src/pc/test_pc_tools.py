"""Integration test of the PC tools without hardware (in the container):

fake TCU (TCP 50040 / 50041 on localhost: banner, "OK" to START / STOP, 16-channel float32 frames of subject 0's
six calibration recordings, sensors 9-16 zero) -> trigno_bridge.py -> TCP instead of the serial port -> the C
real-time loop (src/c/rt.c via ctypes, the "MCU") -> its packets back over the same socket -> mcu_logger CSV.
The "MCU" is put into calibration mode (label 0) before the stream starts and asked to calibrate at the end, so
it sends status packets (calibration windows full, calibration result) back through the bridge.
Checks: every forwarded sample equals the float32 TCU value quantised to int16 at 0.25 uV; the EMG CSV holds every
frame; the bridge logged the MCU's status packets. The TCU protocol itself (banner, commands, frame layout) is
the pytrigno one and still has to be checked against the real TCU on the lab PC.
Writes results/pc_tools_test.csv. Usage (in the container): PYTHONPATH=src python src/pc/test_pc_tools.py
"""
import csv
import ctypes
import os
import socket
import struct
import sys
import tempfile
import threading

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import check_oneshot_c as C  # noqa: E402
import check_rt as RT  # noqa: E402
import pipeline as P  # noqa: E402
import protocol as PR  # noqa: E402
import trigno_bridge  # noqa: E402


def fake_tcu(frames16, ports, ready):
    cmd_srv = socket.create_server(('127.0.0.1', ports[0]))
    emg_srv = socket.create_server(('127.0.0.1', ports[1]))
    ready.set()
    c, _ = cmd_srv.accept()
    e, _ = emg_srv.accept()
    c.sendall(b'Delsys Trigno System Digital Protocol Version 3.6.0 (fake)\r\n\r\n')
    started = threading.Event()

    def commands():
        buf = b''
        while True:
            d = c.recv(1024)
            if not d:
                return
            buf += d
            while b'\r\n\r\n' in buf:
                cmd, buf = buf.split(b'\r\n\r\n', 1)
                c.sendall(b'OK\r\n\r\n')
                if cmd.strip() == b'START':
                    started.set()
    threading.Thread(target=commands, daemon=True).start()
    started.wait(10)
    data = frames16.astype('<f4').tobytes()
    for i in range(0, len(data), 64 * 200):                     # 200 frames per send
        e.sendall(data[i:i + 64 * 200])
    e.close()


def fake_mcu(port, ready, result):
    lib = RT.build()
    _, arrs = C.pre_trees()
    tab = C.table_struct(arrs)
    flash = np.full(C.CAP, 0xFF, dtype=np.uint8)

    def write(_ctx, off, src, n):
        flash[off:off + n] = np.frombuffer(ctypes.string_at(src, n), dtype=np.uint8)
        return 0
    w = C.Writer(C.WRITE_FN(write), None, C.CAP)
    srv = socket.create_server(('127.0.0.1', port))
    ready.set()
    conn, _ = srv.accept()
    def tx(ptr, n):
        try:
            conn.sendall(ctypes.string_at(ptr, n))
        except OSError:
            pass
    txcb = RT.TX(tx)
    cfg = RT.Config(ctypes.addressof(tab), ctypes.addressof(w), flash.ctypes.data, RT.ERASE(0), RT.ERASE(0), txcb,
                    RT.NOW(0), 9, 0, 1, 1)
    lib.rt_init(ctypes.byref(cfg))
    enc = PR.Encoder()
    ctl = enc.control(PR.CAL_START, 0)                          # straight into the "MCU", not via the bridge
    lib.rt_rx(ctypes.c_char_p(ctl), len(ctl))
    dec = PR.Decoder()
    got = []
    while True:
        try:
            d = conn.recv(65536)
        except ConnectionResetError:                # the bridge closed with our packets unread: end of stream
            d = b''
        if not d:
            break
        lib.rt_rx(ctypes.c_char_p(d), len(d))
        for t, s, p in dec.feed(d):
            if t == PR.SAMPLES:
                got.append(np.frombuffer(p, dtype='<i2').reshape(-1, 8))
        if lib.rt_counters().contents.cal_windows >= 60 and 'calibrated' not in result:
            ctl = enc.control(PR.CALIBRATE)
            lib.rt_rx(ctypes.c_char_p(ctl), len(ctl))
            lib.rt_idle()                                       # sends the EV_CALIBRATED status
            result['calibrated'] = lib.rt_counters().contents.calibrate_result
    result['samples'] = np.concatenate(got) if got else np.zeros((0, 8), dtype=np.int16)
    result['counters'] = {k: getattr(lib.rt_counters().contents, k) for k, _ in RT.Counters._fields_}
    conn.close()


def main():
    raw = np.load(os.path.join(P.REPO, 'dataset_arm_position', '0', 'calibration', 'data.npy'))   # 6 x 8 x 4000
    emg8 = np.concatenate([t.T for t in raw]).astype(np.float32)                                  # frames x 8
    frames16 = np.concatenate([emg8, np.zeros_like(emg8)], axis=1)
    ports = (50040, 50041)
    r1, r2, result = threading.Event(), threading.Event(), {}
    threading.Thread(target=fake_tcu, args=(frames16, ports, r1), daemon=True).start()
    mcu = threading.Thread(target=fake_mcu, args=(7000, r2, result), daemon=True)
    mcu.start()
    r1.wait(10)
    r2.wait(60)
    tmp = tempfile.mkdtemp()
    emg_csv, mcu_csv = os.path.join(tmp, 'emg.csv'), os.path.join(tmp, 'mcu.csv')
    n, clipped = trigno_bridge.main(['--tcu', '127.0.0.1', '--port', 'tcp:127.0.0.1:7000', '--emg-csv', emg_csv,
                                     '--mcu-csv', mcu_csv])
    mcu.join(30)
    sent = result['samples']
    expect = np.array(PR.volts_to_int16(emg8[:len(sent)].tolist())[0], dtype=np.int16)
    with open(emg_csv) as f:
        emg_rows = sum(1 for _ in f) - 1
    with open(mcu_csv) as f:
        mcu_rows = list(csv.DictReader(f))
    status = [r for r in mcu_rows if r['kind'] == 'status']
    row = dict(frames_from_tcu=len(emg8), frames_forwarded=n, frames_received_by_mcu=len(sent),
               samples_equal=bool(np.array_equal(sent, expect)), clipped=clipped, emg_csv_rows=emg_rows,
               mcu_packets_logged=len(mcu_rows), status_events=';'.join(f"{r['event']}={r['value']}" for r in status),
               calibrate_result=result.get('calibrated'), mcu_windows=result['counters']['windows'],
               mcu_cal_windows=result['counters']['cal_windows'], mcu_lost_packets=result['counters']['lost_packets'])
    for k, v in row.items():
        print(f'{k}: {v}')
    out = os.path.join(P.ROOT, 'results', 'pc_tools_test.csv')
    with open(out, 'w', newline='') as f:
        w = csv.DictWriter(f, list(row))
        w.writeheader()
        w.writerow(row)


if __name__ == '__main__':
    main()
