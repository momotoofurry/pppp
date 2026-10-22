"""Log what the MCU sends (PK_COMMAND / PK_PRED / PK_STATUS) to a CSV, with the PC receive time.

Standard library only (+ pyserial when reading a serial port). Used by trigno_bridge.py, which owns the serial
port and logs the MCU's packets from its reader thread; standalone it reads a port nobody else has open, or
decodes a captured byte file.

  python mcu_logger.py --port COM5 --baud 921600 --out mcu.csv
  python mcu_logger.py --port file:capture.bin --out mcu.csv
"""
import argparse
import csv
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import protocol as PR  # noqa: E402

FIELDS = ['pc_time', 'kind', 'window', 't_us', 'command', 'command_code', 'gesture', 'class_id', 'accepted', 'ratio',
          'pushed', 'event', 'value', 'type', 'length']


class MCULogger:
    def __init__(self, path):
        self.f = open(path, 'w', newline='')
        self.w = csv.DictWriter(self.f, FIELDS, extrasaction='ignore')
        self.w.writeheader()
        self.dec = PR.Decoder()
        self.rows = 0

    def feed(self, data, pc_time=None):
        t = time.time() if pc_time is None else pc_time
        out = []
        for ptype, _seq, payload in self.dec.feed(data):
            m = PR.parse_mcu(ptype, payload)
            m['pc_time'] = f'{t:.6f}'
            self.w.writerow(m)
            self.rows += 1
            out.append(m)
        return out

    def close(self):
        self.f.close()


def open_port(port, baud):
    if port.startswith('file:'):
        return open(port[5:], 'rb')
    import serial                                   # pyserial: only needed for a real port
    return serial.Serial(port, baud, timeout=0.05)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', required=True, help='serial port (COM5, /dev/ttyACM0) or file:<captured bytes>')
    ap.add_argument('--baud', type=int, default=921600)
    ap.add_argument('--out', default='mcu.csv')
    args = ap.parse_args()
    log = MCULogger(args.out)
    src = open_port(args.port, args.baud)
    try:
        while True:
            data = src.read(4096)
            if not data:
                if args.port.startswith('file:'):
                    break
                continue
            for m in log.feed(data):
                if m['kind'] in ('command', 'status'):
                    print(m, flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        log.close()
        print(f'{log.rows} packets, {log.dec.crc_errors} CRC errors', file=sys.stderr)


if __name__ == '__main__':
    main()
