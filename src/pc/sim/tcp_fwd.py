"""TCP forwarder for the test only: <listen host>:<port> -> 127.0.0.1:<target> (both directions). Lets the
container (Docker Desktop) reach ros_relay.py, which listens on the WSL loopback."""
import socket
import sys
import threading


def pipe(a, b):
    try:
        while True:
            d = a.recv(65536)
            if not d:
                break
            b.sendall(d)
    except OSError:
        pass
    for s in (a, b):
        try:
            s.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def main():
    host, port, target = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(4)
    print(f'forwarding {host}:{port} -> 127.0.0.1:{target}', flush=True)
    while True:
        c, _ = srv.accept()
        r = socket.create_connection(('127.0.0.1', target))
        threading.Thread(target=pipe, args=(c, r), daemon=True).start()
        threading.Thread(target=pipe, args=(r, c), daemon=True).start()


if __name__ == '__main__':
    main()
