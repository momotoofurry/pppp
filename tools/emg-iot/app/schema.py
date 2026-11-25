"""Message contract shared by the edge publisher and the ingest service.

Topic   emg/<subject>/<session>/window   one 200 ms window every 100 ms, QoS 1
        emg/<subject>/<session>/status   retained "online" / "offline" (last will)
Payload JSON: {"seq": int, "t": unix ms (replay clock), "src_t": unix ms (recording clock), "phase": str,
               "label": int (-1 = none), "pred": int, "rms": [4 floats, uV], "hum": [4 floats, uV]}
"""
PHASES = {'cal', 'probe', 'task', 'idle'}
CLASSES = {0: 'Ext', 1: 'Flex', 2: 'Rad', 3: 'Uln', 6: 'Open', 7: 'Fist', 8: 'Rest'}
N_CH = 4
MAX_UV = 5000.0          # Trigno range is +-11 mV; an RMS above 5 mV is not EMG


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate(msg):
    """-> None if valid, else the reason. Strict: a bad record goes to emg_reject, never into the data."""
    if not isinstance(msg, dict):
        return 'not an object'
    if not isinstance(msg.get('seq'), int) or msg['seq'] < 0:
        return 'seq'
    if not _num(msg.get('t')):
        return 't'
    if msg.get('phase') not in PHASES:
        return 'phase'
    if msg.get('label') != -1 and msg.get('label') not in CLASSES:
        return 'label'
    if msg.get('pred') not in CLASSES:
        return 'pred'
    for k in ('rms', 'hum'):
        v = msg.get(k)
        if not isinstance(v, list) or len(v) != N_CH or not all(_num(x) and 0 <= x <= MAX_UV for x in v):
            return k
    return None
