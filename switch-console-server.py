#!/usr/bin/env python3
"""Local companion for Switch Console GUI.

Serves the HTML page and bridges SSH / Telnet to the browser.
Serial still uses the browser Web Serial API and does not need this
bridge, but you can serve the page from here either way.

  pip install paramiko
  python switch-console-server.py

Then open http://127.0.0.1:8080/switch-console-gui.html
"""
from __future__ import annotations

import json
import os
import queue
import socket
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

try:
    import paramiko
except ImportError:
    paramiko = None

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("SCG_PORT", "8080"))
out_q: "queue.Queue[str | None]" = queue.Queue()
lock = threading.Lock()
session = {"kind": None, "sock": None, "chan": None, "alive": False}


def push(text: str) -> None:
    out_q.put(text)


def close_session() -> None:
    with lock:
        session["alive"] = False
        sock = session.get("sock")
        chan = session.get("chan")
        session["sock"] = None
        session["chan"] = None
        session["kind"] = None
    try:
        if chan:
            chan.close()
    except Exception:
        pass
    try:
        if sock:
            sock.close()
    except Exception:
        pass


def reader_loop(recv) -> None:
    try:
        while session.get("alive"):
            data = recv()
            if not data:
                break
            if isinstance(data, bytes):
                text = data.decode("utf-8", "replace")
            else:
                text = data
            push(text)
    except Exception as exc:
        push(f"\n[session closed] {exc}\n")
    finally:
        session["alive"] = False
        push(None)


def start_telnet(host: str, port: int, user: str, password: str) -> None:
    sock = socket.create_connection((host, port), timeout=8)
    sock.settimeout(0.4)
    session["kind"] = "telnet"
    session["sock"] = sock
    session["alive"] = True

    def recv():
        try:
            return sock.recv(4096)
        except socket.timeout:
            return b""

    threading.Thread(target=reader_loop, args=(recv,), daemon=True).start()
    time.sleep(0.3)
    if user:
        sock.sendall((user + "\r").encode())
        time.sleep(0.4)
    if password:
        sock.sendall((password + "\r").encode())


def start_ssh(host: str, port: int, user: str, password: str) -> None:
    if paramiko is None:
        raise RuntimeError("Install paramiko: pip install paramiko")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=port,
        username=user or "admin",
        password=password or "",
        look_for_keys=False,
        allow_agent=False,
        timeout=12,
    )
    chan = client.invoke_shell(term="vt100", width=120, height=40)
    chan.settimeout(0.4)
    session["kind"] = "ssh"
    session["sock"] = client
    session["chan"] = chan
    session["alive"] = True

    def recv():
        try:
            if chan.recv_ready():
                return chan.recv(4096)
            time.sleep(0.05)
            return b""
        except Exception:
            return b""

    threading.Thread(target=reader_loop, args=(recv,), daemon=True).start()


def send_bytes(data: str) -> None:
    raw = data.encode("utf-8", "replace")
    with lock:
        kind = session.get("kind")
        sock = session.get("sock")
        chan = session.get("chan")
        alive = session.get("alive")
    if not alive:
        raise RuntimeError("not connected")
    if kind == "telnet" and sock:
        sock.sendall(raw)
    elif kind == "ssh" and chan:
        chan.send(raw)
    else:
        raise RuntimeError("no session")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=HERE, **kwargs)

    def log_message(self, fmt, *args):
        print("[http]", fmt % args)

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            payload = {}
        try:
            if self.path == "/api/connect":
                close_session()
                proto = (payload.get("proto") or "ssh").lower()
                host = payload.get("host") or ""
                port = int(payload.get("port") or (22 if proto == "ssh" else 23))
                user = payload.get("user") or ""
                password = payload.get("password") or ""
                if not host:
                    raise RuntimeError("host is required")
                if proto == "ssh":
                    start_ssh(host, port, user, password)
                elif proto == "telnet":
                    start_telnet(host, port, user, password)
                else:
                    raise RuntimeError("proto must be ssh or telnet")
                self._json(200, {"ok": True, "proto": proto})
                return
            if self.path == "/api/send":
                send_bytes(payload.get("data") or "")
                self._json(200, {"ok": True})
                return
            if self.path == "/api/disconnect":
                close_session()
                self._json(200, {"ok": True})
                return
            self._json(404, {"error": "unknown endpoint"})
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def do_GET(self):
        if self.path.startswith("/api/events"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                while True:
                    try:
                        item = out_q.get(timeout=15)
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        continue
                    if item is None:
                        self.wfile.write(b"event: close\ndata: end\n\n")
                        self.wfile.flush()
                        break
                    data = json.dumps(item)
                    self.wfile.write(f"data: {data}\n\n".encode())
                    self.wfile.flush()
            except BrokenPipeError:
                return
            return
        if self.path in ("/", "/index.html"):
            self.path = "/switch-console-gui.html"
        return super().do_GET()


def main() -> None:
    os.chdir(HERE)
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Open http://127.0.0.1:{PORT}/switch-console-gui.html")
    if paramiko is None:
        print("SSH requires: pip install paramiko   (Telnet works without it)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        close_session()


if __name__ == "__main__":
    main()
