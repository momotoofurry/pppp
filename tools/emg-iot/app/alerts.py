"""Alert log: receives Grafana's webhook notifications, stores every alert in alert_log and republishes it on MQTT
(emg/alerts, QoS 1), so an edge device or another service can react (e.g. ask the user to re-do the Rest cue)."""
import json, os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import paho.mqtt.client as mqtt
import psycopg

DSN = os.environ['DB_DSN']
MQ = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='alert-log')
MQ.connect(os.environ.get('MQTT_HOST', 'localhost'), 1883, keepalive=30)
MQ.loop_start()


def parse_time(s):
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except (AttributeError, ValueError):
        return None


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        try:
            msg = json.loads(body)
            rows = []
            for a in msg.get('alerts', []):
                lab, ann = a.get('labels', {}), a.get('annotations', {})
                rows.append((datetime.now(timezone.utc), a.get('status'), lab.get('alertname'), lab.get('severity'),
                             ann.get('summary'), parse_time(a.get('startsAt')), a.get('fingerprint')))
            with psycopg.connect(DSN) as db:
                db.cursor().executemany('INSERT INTO alert_log (time, status, alertname, severity, summary, starts_at, '
                                        'fingerprint) VALUES (%s,%s,%s,%s,%s,%s,%s)', rows)
            for r in rows:
                MQ.publish('emg/alerts', json.dumps(dict(status=r[1], alert=r[2], severity=r[3], summary=r[4])), qos=1)
            print(f'alert-log: {len(rows)} alert(s): ' + ', '.join(f'{r[2]} {r[1]}' for r in rows), flush=True)
            self.send_response(200)
        except Exception as e:  # noqa: BLE001
            print('alert-log: bad notification:', e, flush=True)
            self.send_response(400)
        self.end_headers()

    def log_message(self, *_):
        pass


if __name__ == '__main__':
    print('alert-log: listening on :8080', flush=True)
    HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
