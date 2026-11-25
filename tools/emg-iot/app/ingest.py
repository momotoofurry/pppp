"""Ingest service: MQTT -> validation -> TimescaleDB (batched COPY every 0.5 s).
Bad records go to emg_reject with the reason; per-session sequence gaps (lost / reordered windows) to ingest_gap."""
import json, os, queue, threading, time
from datetime import datetime, timezone
import paho.mqtt.client as mqtt
import psycopg
from schema import validate

Q = queue.Queue(maxsize=200000)
COLS = ('time', 'subject', 'session', 'seq', 'phase', 'label', 'pred', 'rms1', 'rms2', 'rms3', 'rms4',
        'hum1', 'hum2', 'hum3', 'hum4', 'src_ms')


def on_message(_c, _u, m):
    Q.put((m.topic, m.payload))


def collect(last_seq):
    batch, rej, gaps = [], [], []
    t_end = time.time() + 0.5
    while time.time() < t_end and len(batch) < 5000:
        try:
            topic, payload = Q.get(timeout=0.1)
        except queue.Empty:
            continue
        now = datetime.now(timezone.utc)
        text = payload.decode(errors='replace')[:500]
        try:
            msg = json.loads(payload)
            _, subject, session, _ = topic.split('/')
        except Exception as e:  # noqa: BLE001
            rej.append((now, topic, text, f'parse: {type(e).__name__}'))
            continue
        why = validate(msg)
        if why:
            rej.append((now, topic, text, why))
            continue
        prev = last_seq.get(session)
        if prev is not None and msg['seq'] != prev + 1:
            gaps.append((now, session, prev, msg['seq']))
        last_seq[session] = msg['seq']
        batch.append((datetime.fromtimestamp(msg['t'] / 1000, timezone.utc), subject, session, msg['seq'], msg['phase'],
                      msg['label'], msg['pred'], *msg['rms'], *msg['hum'], msg.get('src_t')))
    return batch, rej, gaps


def writer(dsn):
    last_seq = {}
    while True:
        try:
            with psycopg.connect(dsn) as db:
                print('ingest: database connected', flush=True)
                while True:
                    batch, rej, gaps = collect(last_seq)
                    if not (batch or rej or gaps):
                        continue
                    with db.cursor() as cur:
                        if batch:
                            with cur.copy(f'COPY emg_window ({",".join(COLS)}) FROM STDIN') as cp:
                                for r in batch:
                                    cp.write_row(r)
                        if rej:
                            cur.executemany('INSERT INTO emg_reject (time, topic, payload, reason) VALUES (%s,%s,%s,%s)', rej)
                        if gaps:
                            cur.executemany('INSERT INTO ingest_gap (time, session, prev_seq, seq) VALUES (%s,%s,%s,%s)', gaps)
                    db.commit()
        except psycopg.OperationalError as e:
            print('ingest: database unavailable, retrying:', e, flush=True)
            time.sleep(2)


def main():
    threading.Thread(target=writer, args=(os.environ['DB_DSN'],), daemon=True).start()
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='ingest', clean_session=False)
    c.on_message = on_message
    c.on_connect = lambda cl, *_: cl.subscribe('emg/+/+/window', qos=1)
    c.connect(os.environ.get('MQTT_HOST', 'localhost'), 1883, keepalive=30)
    print('ingest: subscribed to emg/+/+/window', flush=True)
    c.loop_forever(retry_first_connection=True)


if __name__ == '__main__':
    main()
