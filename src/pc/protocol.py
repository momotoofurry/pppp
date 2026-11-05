"""PC side of the serial protocol of src/c/protocol.h and src/c/rt.h (standard library only).

Packet: 0xA5 0x5A | type u8 | seq u16 | len u16 | payload | crc u16, little-endian,
crc = CRC-16/CCITT-FALSE over type .. payload (binascii.crc_hqx(data, 0xFFFF)).
Samples: frames of 8 int16, 1 LSB = 0.25 uV (LSB_VOLT); 20 frames per packet by default.
"""
import binascii
import struct

SYNC = b'\xa5\x5a'
OVERHEAD = 9
MAX_PAYLOAD = 512
CH = 8
LSB_VOLT = 2.5e-7
FRAMES_PER_PACKET = 20
SAMPLES, CONTROL, COMMAND, STATUS, PRED = 0x01, 0x02, 0x81, 0x82, 0x83
# control sub-commands (rt.h)
STREAM_RESET, CAL_START, CAL_END, CALIBRATE, SET_DECISION, SET_REPORT = 1, 2, 3, 4, 5, 6
ALIGN_START, ALIGN_END, LOAD, SET_ADAPT = 7, 8, 9, 10
# status events
EV_CALIBRATED, EV_SELFCAL, EV_LOST, EV_CAL_FULL, EV_ALIGNED, EV_ALIGN_SHORT, EV_SC_BEGIN, EV_SC_END = 1, 2, 3, 4, 5, 6, 7, 8
EV_DIAG_RX_HW, EV_DIAG_STACK, EV_DIAG_RX_OVF, EV_DIAG_RX_ERR = 9, 10, 11, 12   # board main loop (app_rt.c)
EV_SC_SKIP, EV_LOADED = 13, 14                          # update skipped (RT_MIN_CLASSES); day-1 model restored (RT_LOAD)
EV_ALIGN_UNSURE = 15                                    # start-up rotation estimate rejected (kept 0)
COMMANDS = {0: 'none', 1: 'pose_A', 2: 'grip', 3: 'pose_B', 4: 'release', 5: 'home'}   # 5: Lateral, pilot-freeze-5
GESTURES = ['Power', 'Lateral', 'Tripod', 'Pointer', 'Open', 'Rest']


def crc16(data):
    return binascii.crc_hqx(bytes(data), 0xFFFF)


def build(ptype, seq, payload=b''):
    if len(payload) > MAX_PAYLOAD:
        raise ValueError('payload too long')
    body = struct.pack('<BHH', ptype, seq & 0xFFFF, len(payload)) + bytes(payload)
    return SYNC + body + struct.pack('<H', crc16(body))


def volts_to_int16(frames):
    """frames: sequence of CH-sample rows in volts -> list of int16 rows (saturating), number clipped."""
    out, clipped = [], 0
    for row in frames:
        q = []
        for v in row:
            x = int(round(v / LSB_VOLT))
            if x > 32767 or x < -32768:
                clipped += 1
                x = max(-32768, min(32767, x))
            q.append(x)
        out.append(q)
    return out, clipped


def samples_payload(int16_frames):
    return b''.join(struct.pack('<%dh' % CH, *row) for row in int16_frames)


def control_payload(sub, *args):
    if sub == CAL_START:
        return struct.pack('<BB', sub, args[0])
    if sub == SET_DECISION:
        return struct.pack('<BHB', sub, args[0], args[1])
    if sub in (SET_REPORT, SET_ADAPT):
        return struct.pack('<BB', sub, args[0])
    return struct.pack('<B', sub)


class Encoder:
    """Packets with their own sequence numbers per type."""

    def __init__(self):
        self.seq = {SAMPLES: 0, CONTROL: 0}

    def packet(self, ptype, payload):
        s = self.seq[ptype]
        self.seq[ptype] = (s + 1) & 0xFFFF
        return build(ptype, s, payload)

    def samples(self, int16_frames):
        return self.packet(SAMPLES, samples_payload(int16_frames))

    def control(self, sub, *args):
        return self.packet(CONTROL, control_payload(sub, *args))


class Decoder:
    """Incremental parser with the same resync rule as protocol.c: after a bad packet, rescan from the byte
    after its sync word. feed() returns the good packets as (type, seq, payload)."""

    def __init__(self):
        self.buf = bytearray()
        self.ok = self.crc_errors = self.len_errors = self.skipped = 0

    def _resync(self):
        k = self.buf.find(b'\xa5', 1)
        k = len(self.buf) if k < 0 else k
        self.skipped += k
        del self.buf[:k]

    def feed(self, data):
        self.buf += data
        out = []
        while self.buf:
            if self.buf[0] != 0xA5 or (len(self.buf) >= 2 and self.buf[1] != 0x5A):
                self._resync()
                continue
            if len(self.buf) < 7:
                break
            ptype, seq, n = struct.unpack_from('<BHH', self.buf, 2)
            if n > MAX_PAYLOAD:
                self.len_errors += 1
                self._resync()
                continue
            if len(self.buf) < OVERHEAD + n:
                break
            if crc16(self.buf[2:7 + n]) != struct.unpack_from('<H', self.buf, 7 + n)[0]:
                self.crc_errors += 1
                self._resync()
                continue
            self.ok += 1
            out.append((ptype, seq, bytes(self.buf[7:7 + n])))
            del self.buf[:OVERHEAD + n]
        return out


def parse_mcu(ptype, payload):
    """MCU -> PC payloads as dicts."""
    if ptype == COMMAND:
        w, t, cmd, cls, ratio = struct.unpack('<IIBBH', payload[:12])
        return dict(kind='command', window=w, t_us=t, command=COMMANDS.get(cmd, cmd), command_code=cmd,
                    gesture=GESTURES[cls] if cls < 6 else cls, ratio=ratio / 1000)
    if ptype == PRED:
        w, t, cls, acc, ratio, pushed = struct.unpack('<IIBBHB', payload[:13])
        return dict(kind='pred', window=w, t_us=t, gesture=GESTURES[cls] if cls < 6 else cls, class_id=cls,
                    accepted=acc, ratio=ratio / 1000, pushed=pushed)
    if ptype == STATUS:
        ev, value = struct.unpack('<B3xi', payload[:8])
        return dict(kind='status', event=ev, value=value)
    return dict(kind='unknown', type=ptype, length=len(payload))
