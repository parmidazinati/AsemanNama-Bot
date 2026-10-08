#!/usr/bin/env python3
"""فورواردر پروکسی محلی برای کرومیوم.

کرومیوم نمی‌تواند احراز هویت پروکسی (username/password) را خودش انجام دهد؛
این فورواردر روی 127.0.0.1 بدون auth گوش می‌دهد و خودش با upstream احراز هویت می‌کند.
"""
import base64
import logging
import os
import socket
import socketserver
import threading
import urllib.parse as _up

log = logging.getLogger("weather")

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 18888

_server = None
_lock = threading.Lock()


def _upstream():
    raw = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") or ""
    u = _up.urlparse(raw)
    user = _up.unquote(u.username or "")
    pwd = _up.unquote(u.password or "")
    auth = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    return u.hostname, u.port or 3128, auth


def _read_head(sock) -> bytes:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
        if len(data) > 65536:
            break
    return data


def _relay(a: socket.socket, b: socket.socket, timeout: int = 90):
    a.settimeout(timeout)
    b.settimeout(timeout)
    try:
        while True:
            try:
                d = a.recv(65536)
            except (socket.timeout, OSError):
                break
            if not d:
                break
            try:
                b.sendall(d)
            except (socket.timeout, OSError):
                break
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            self._handle()
        except Exception as e:  # noqa: BLE001
            log.warning("proxyfwd error: %s", e)

    def _handle(self):
        req_line = self.rfile.readline().decode("latin1")
        if not req_line:
            return
        parts = req_line.split()
        if len(parts) < 2:
            return
        method, target = parts[0].upper(), parts[1]
        headers = []
        while True:
            h = self.rfile.readline().decode("latin1")
            if h in ("\r\n", "\n", ""):
                break
            if not h.lower().startswith("proxy-"):
                headers.append(h)

        host, port, auth = _upstream()
        if not host:
            self.wfile.write(b"HTTP/1.1 500 No Upstream\r\n\r\n")
            return
        up = socket.create_connection((host, port), timeout=25)
        try:
            if method == "CONNECT":
                up.sendall(
                    f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n"
                    f"Proxy-Authorization: Basic {auth}\r\n\r\n".encode("latin1")
                )
                resp = _read_head(up)
                code = resp.split(b" ")[1] if b" " in resp else b""
                if code != b"200":
                    self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                    return
                self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                t = threading.Thread(target=_relay, args=(up, self.connection), daemon=True)
                t.start()
                _relay(self.connection, up)
                t.join(timeout=5)
            else:
                up.sendall(req_line.encode("latin1"))
                for h in headers:
                    up.sendall(h.encode("latin1"))
                up.sendall(f"Proxy-Authorization: Basic {auth}\r\n\r\n".encode("latin1"))
                _relay(up, self.connection)
        finally:
            up.close()


class _Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def ensure() -> str:
    """فورواردر را (یک بار) بالا می‌آورد و آدرس پروکسی محلی را برمی‌گرداند."""
    global _server
    with _lock:
        if _server is None:
            try:
                _server = _Server((LISTEN_HOST, LISTEN_PORT), _Handler)
            except OSError as e:
                if getattr(e, "errno", None) == 98:
                    # پروسه دیگری (مثلاً خود ربات) قبلاً بالاست
                    log.info("proxyfwd already running in another process")
                    return f"http://{LISTEN_HOST}:{LISTEN_PORT}"
                raise
            threading.Thread(target=_server.serve_forever, daemon=True).start()
            log.info("proxyfwd listening on %s:%d", LISTEN_HOST, LISTEN_PORT)
    return f"http://{LISTEN_HOST}:{LISTEN_PORT}"
