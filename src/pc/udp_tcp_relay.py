"""Board commands from TrignoBridge (Windows) to src/pc/sim/assist_ros.py board (WSL), report 35.82.

TrignoBridge run --udp 50555,50556 sends every board COMMAND / STATUS as a UDP datagram "<unix_ms>,<mcu.csv line>" to
127.0.0.1. WSL 2 (NAT) forwards Windows-localhost TCP into WSL, not UDP, so this relay (Windows, stdlib only) listens on
UDP and passes each datagram as one text line over TCP to assist_ros.py board (listening in WSL on 127.0.0.1:50560 by
default), prefixed with the relay's own receive time: "<relay_unix_ms>,<datagram>". Reconnects every second when
assist_ros is not (yet) up; datagrams meanwhile are dropped and counted.
The way back (report 35.83): assist_ros answers every event with 'ack,<relay_unix_ms>' (the relay logs the round trip
on its own clock to --rtt) and sends hindsight labels 'range,<first>,<last>,<class>', which the relay passes as a UDP
datagram to TrignoBridge --task-udp (default 50559) -> RTL_LABEL_RANGE on the board.
usage (Windows): python src/pc/udp_tcp_relay.py [--udp 50556] [--to 127.0.0.1:50560] [--task 50559] [--rtt rtt.csv]
"""
import argparse
import socket
import threading
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--udp', type=int, default=50556)
    ap.add_argument('--to', default='127.0.0.1:50560')
    ap.add_argument('--task', type=int, default=50559)
    ap.add_argument('--rtt', default='relay_rtt.csv')
    a = ap.parse_args()
    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rtt = open(a.rtt, 'w', encoding='ascii')
    rtt.write('relay_unix_ms,rtt_ms\n')
    rtt.flush()
    back = {'labels': 0, 'acks': 0}

    def reader(conn):
        try:
            for line in conn.makefile('r', encoding='ascii', errors='replace'):
                f = line.strip().split(',')
                if f[0] == 'ack' and len(f) == 2:
                    now = time.time() * 1000
                    rtt.write(f'{f[1]},{now - float(f[1]):.2f}\n')        # f[1]: the relay time it sent
                    rtt.flush()
                    back['acks'] += 1
                elif f[0] == 'range' and len(f) == 4:
                    out.sendto(line.strip().encode('ascii'), ('127.0.0.1', a.task))
                    back['labels'] += 1
                    print('label -> bridge: ' + line.strip(), flush=True)
        except OSError as e:
            print(f'reader stopped: {e}', flush=True)
    host, port = a.to.rsplit(':', 1)
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    u.bind(('127.0.0.1', a.udp))
    u.settimeout(1.0)
    t, sent, dropped, last_try = None, 0, 0, 0.0
    print(f'UDP 127.0.0.1:{a.udp} -> TCP {a.to}', flush=True)
    try:
        while True:
            if t is None and time.time() - last_try > 1.0:
                last_try = time.time()
                try:
                    t = socket.create_connection((host, int(port)), timeout=1.0)
                    # 35.85: the 1 s connect timeout stayed on the socket, so the reader thread hit a timeout after
                    # 1 s without acks / labels and ended quietly: nothing came back any more
                    t.settimeout(None)
                    t.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    threading.Thread(target=reader, args=(t,), daemon=True).start()
                    print('connected to assist_ros', flush=True)
                except OSError:
                    t = None
            try:
                d, _ = u.recvfrom(2048)
            except socket.timeout:
                continue
            line = f'{time.time() * 1000:.1f},' + d.decode('ascii', 'replace').strip() + '\n'
            if t is None:
                dropped += 1
                continue
            try:
                t.sendall(line.encode('ascii'))
                sent += 1
            except OSError:
                print('assist_ros connection lost', flush=True)
                t = None
                dropped += 1
    except KeyboardInterrupt:
        pass
    print(f'relayed {sent}, dropped {dropped}; back: acks {back["acks"]}, labels {back["labels"]}', flush=True)


if __name__ == '__main__':
    main()
