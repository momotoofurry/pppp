"""Edge node replay: publish a recorded session's windows over MQTT at the recording's own pace (or faster).
Window times are shifted so the first window is 'now'; src_t keeps the recording clock.
usage: python publish.py --session T00_d1_G [--subject T00] [--speed 20] [--limit N] [--bad N]
  --bad N   also send N malformed messages (to check that ingest rejects them)"""
import argparse, csv, json, os, time
import paho.mqtt.client as mqtt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--session', required=True)
    ap.add_argument('--subject', default='T00')
    ap.add_argument('--speed', type=float, default=1.0)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--bad', type=int, default=0)
    a = ap.parse_args()
    base = f'emg/{a.subject}/{a.session}'
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f'edge-{a.session}')
    c.will_set(f'{base}/status', 'offline', qos=1, retain=True)
    c.connect(os.environ.get('MQTT_HOST', 'localhost'), 1883, keepalive=30)
    c.loop_start()
    c.publish(f'{base}/status', 'online', qos=1, retain=True)
    with open(f'/data/{a.session}_edge.csv') as f:
        rows = list(csv.DictReader(f))
    if a.limit:
        rows = rows[:a.limit]
    src0 = float(rows[0]['t_ms'])
    wall0 = time.time() * 1000
    info = None
    for seq, r in enumerate(rows):
        src = float(r['t_ms'])
        delay = (wall0 + (src - src0) / a.speed) / 1000 - time.time()
        if delay > 0:
            time.sleep(delay)
        msg = dict(seq=seq, t=wall0 + (src - src0) / a.speed, src_t=src, phase=r['phase'], label=int(r['label']),
                   pred=int(r['pred']), rms=[float(r[f'rms{k}']) for k in range(1, 5)],
                   hum=[float(r[f'hum{k}']) for k in range(1, 5)])
        info = c.publish(f'{base}/window', json.dumps(msg), qos=1)
        if seq % 2000 == 0:
            print(f'{a.session}: {seq}/{len(rows)}', flush=True)
    for k in range(a.bad):
        bad = [b'not json', json.dumps(dict(seq=-1)).encode(), json.dumps(dict(seq=1, t=0, phase='cal', label=0, pred=0,
                                                                              rms=[1, 2, 3], hum=[0, 0, 0, 0])).encode()]
        c.publish(f'{base}/window', bad[k % 3], qos=1)
    if info:
        info.wait_for_publish()
    c.publish(f'{base}/status', 'offline', qos=1, retain=True).wait_for_publish()
    c.loop_stop()
    c.disconnect()
    print(f'{a.session}: published {len(rows)} windows (+{a.bad} malformed)', flush=True)


if __name__ == '__main__':
    main()
