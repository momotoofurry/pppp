"""Route B, lab PC: read EMG from the Trigno Control Utility (TCU) over TCP, log it to CSV and forward it to the
MCU over the serial link (src/c/protocol.h); log what the MCU sends back. Standard library + pyserial only
(pyserial is needed only for a real serial port; install it offline from its wheel).

TCU (Delsys Trigno SDK server), as used by pytrigno -- *to be verified on the lab PC*:
  command port 50040: ASCII commands terminated by "\\r\\n\\r\\n" ("START", "STOP"); the server sends a version
  banner on connect and answers each command (e.g. "OK\\r\\n\\r\\n").
  EMG data port 50041: little-endian float32, 16 channels per frame (sensor 1..16), volts, 2000 Hz by default.
The first --channels sensors are forwarded (8 by default) as int16 at 0.25 uV per LSB (+-8.19 mV, clipped
samples are counted), 20 frames per packet.

Control lines typed on stdin while streaming (sent to the MCU as PK_CONTROL):
  reset | cal <0-5> | calend | calibrate | decision <tau_permille> <k> | report <0|1> | quit
Gestures: 0 Power, 1 Lateral, 2 Tripod, 3 Pointer, 4 Open, 5 Rest.

  python trigno_bridge.py --tcu 127.0.0.1 --port COM5 --emg-csv emg.csv --mcu-csv mcu.csv
  python trigno_bridge.py --tcu 127.0.0.1 --port file:out.bin      (no MCU: write the serial bytes to a file)
  python trigno_bridge.py --tcu 127.0.0.1 --port tcp:127.0.0.1:7000  (a TCP socket instead of the serial port)
"""
import argparse
import csv
import os
import socket
import struct
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcu_logger  # noqa: E402
import protocol as PR  # noqa: E402

TCU_CHANNELS = 16
FRAME_BYTES = TCU_CHANNELS * 4


class TCU:
    def __init__(self, host, cmd_port=50040, emg_port=50041, timeout=10.0):
        self.cmd = socket.create_connection((host, cmd_port), timeout=timeout)
        self.emg = socket.create_connection((host, emg_port), timeout=timeout)
        self.banner = self._reply()

    def _reply(self):
        buf = b''
        while not buf.endswith(b'\r\n\r\n'):
            chunk = self.cmd.recv(1024)
            if not chunk:
                break
            buf += chunk
        return buf.decode('ascii', 'replace').strip()

    def command(self, text):
        self.cmd.sendall(text.encode('ascii') + b'\r\n\r\n')
        return self._reply()

    def frames(self):
        """yields lists of frames (each TCU_CHANNELS floats, volts)"""
        buf = b''
        while True:
            chunk = self.emg.recv(65536)
            if not chunk:
                return
            buf += chunk
            n = len(buf) // FRAME_BYTES
            if n:
                vals = struct.unpack('<%df' % (n * TCU_CHANNELS), buf[:n * FRAME_BYTES])
                buf = buf[n * FRAME_BYTES:]
                yield [vals[i * TCU_CHANNELS:(i + 1) * TCU_CHANNELS] for i in range(n)]

    def close(self):
        try:
            self.command('STOP')
        except OSError:
            pass
        self.cmd.close()
        self.emg.close()


class Link:
    """the MCU side: serial port, a file (bytes are only written) or a TCP socket"""

    def __init__(self, spec, baud):
        self.kind = spec.split(':')[0] if spec.startswith(('file:', 'tcp:')) else 'serial'
        if self.kind == 'file':
            self.f = open(spec[5:], 'wb')
        elif self.kind == 'tcp':
            host, port = spec[4:].rsplit(':', 1)
            self.s = socket.create_connection((host, int(port)))
            self.s.settimeout(0.05)
        else:
            import serial                           # pyserial
            self.ser = serial.Serial(spec, baud, timeout=0.05)

    def write(self, b):
        if self.kind == 'file':
            self.f.write(b)
        elif self.kind == 'tcp':
            self.s.sendall(b)
        else:
            self.ser.write(b)

    def read(self):
        if self.kind == 'file':
            time.sleep(0.05)
            return b''
        if self.kind == 'tcp':
            try:
                return self.s.recv(4096)
            except socket.timeout:
                return b''
        return self.ser.read(4096)

    def close(self):
        for a in ('f', 's', 'ser'):
            if hasattr(self, a):
                getattr(self, a).close()


def parse_control(line):
    p = line.split()
    if not p:
        return None
    c = p[0].lower()
    if c == 'reset':
        return (PR.STREAM_RESET,)
    if c == 'cal' and len(p) == 2:
        return (PR.CAL_START, int(p[1]))
    if c == 'calend':
        return (PR.CAL_END,)
    if c == 'calibrate':
        return (PR.CALIBRATE,)
    if c == 'decision' and len(p) == 3:
        return (PR.SET_DECISION, int(p[1]), int(p[2]))
    if c == 'report' and len(p) == 2:
        return (PR.SET_REPORT, int(p[1]))
    if c == 'quit':
        return 'quit'
    raise ValueError(line)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--tcu', default='127.0.0.1', help='host running the Trigno Control Utility')
    ap.add_argument('--cmd-port', type=int, default=50040)
    ap.add_argument('--emg-port', type=int, default=50041)
    ap.add_argument('--port', required=True, help='serial port, file:<path> or tcp:<host>:<port>')
    ap.add_argument('--baud', type=int, default=921600)
    ap.add_argument('--channels', type=int, default=PR.CH)
    ap.add_argument('--emg-csv', default='emg.csv')
    ap.add_argument('--mcu-csv', default='mcu.csv')
    ap.add_argument('--max-frames', type=int, default=0, help='stop after this many frames (0: until quit / end)')
    ap.add_argument('--no-start', action='store_true', help='do not send START (TCU already streaming)')
    args = ap.parse_args(argv)
    if args.channels != PR.CH:
        sys.exit('the MCU expects 8 channels')
    tcu = TCU(args.tcu, args.cmd_port, args.emg_port)
    print('TCU:', tcu.banner, file=sys.stderr)
    link = Link(args.port, args.baud)
    log = mcu_logger.MCULogger(args.mcu_csv)
    enc = PR.Encoder()
    stop = threading.Event()
    lock = threading.Lock()

    def reader():
        while not stop.is_set():
            data = link.read()
            if data:
                for m in log.feed(data):
                    if m['kind'] in ('command', 'status'):
                        print(m, file=sys.stderr, flush=True)

    def controls():
        for line in sys.stdin:
            try:
                c = parse_control(line)
            except ValueError:
                print('? reset | cal <0-5> | calend | calibrate | decision <tau_permille> <k> | report <0|1> | quit',
                      file=sys.stderr)
                continue
            if c == 'quit':
                stop.set()
                return
            if c:
                with lock:
                    link.write(enc.control(*c))

    threading.Thread(target=reader, daemon=True).start()
    if sys.stdin.isatty():
        threading.Thread(target=controls, daemon=True).start()
    if not args.no_start:
        print('START ->', tcu.command('START'), file=sys.stderr)
    n_frames, clipped, pending = 0, 0, []
    with open(args.emg_csv, 'w', newline='') as fe:
        w = csv.writer(fe)
        w.writerow(['pc_time', 'frame'] + [f'ch{i + 1}_V' for i in range(args.channels)])
        try:
            for frames in tcu.frames():
                t = time.time()
                for fr in frames:
                    v = fr[:args.channels]
                    w.writerow([f'{t:.6f}', n_frames] + [f'{x:.9g}' for x in v])
                    pending.append(v)
                    n_frames += 1
                while len(pending) >= PR.FRAMES_PER_PACKET:
                    q, c = PR.volts_to_int16(pending[:PR.FRAMES_PER_PACKET])
                    clipped += c
                    del pending[:PR.FRAMES_PER_PACKET]
                    with lock:
                        link.write(enc.samples(q))
                if stop.is_set() or (args.max_frames and n_frames >= args.max_frames):
                    break
        except KeyboardInterrupt:
            pass
    stop.set()
    tcu.close()
    time.sleep(0.1)
    link.close()
    log.close()
    print(f'{n_frames} frames forwarded, {clipped} samples clipped, {log.rows} MCU packets logged', file=sys.stderr)
    return n_frames, clipped


if __name__ == '__main__':
    main()
