"""Small, transactional pairing coordinator. Run behind TLS outside localhost."""
import argparse
import json
import secrets
import socket
import sqlite3
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .common import code_digest, now
from .transport import DATA, HELLO, MAX_DATAGRAM, parse_relay_packet, relay_packet, verify_relay_packet

MAX_BODY = 2048


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL,
            a_token TEXT NOT NULL, a_name TEXT NOT NULL, a_key TEXT NOT NULL,
            b_token TEXT, b_name TEXT, b_key TEXT,
            created REAL NOT NULL, expires REAL NOT NULL, reserve_until REAL,
            session_until REAL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0)""")

    def _refresh(self):
        t = now()
        self.db.execute("UPDATE sessions SET state='expired' WHERE state='pending' AND expires<=?", (t,))
        self.db.execute("UPDATE sessions SET state='unconfirmed' WHERE state='reserved' AND reserve_until<=?", (t,))
        self.db.execute("UPDATE sessions SET state='closed' WHERE state='paired' AND session_until<=?", (t,))

    def create(self, data):
        digest = data["digest"]
        key = data["public_key"]
        name = data["name"]
        ttl = int(data.get("ttl", 45))
        if not (len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)):
            raise ValueError("digest inválido")
        validate_key(key)
        validate_name(name)
        if not 30 <= ttl <= 90:
            raise ValueError("duración fuera de rango")
        sid, token = secrets.token_hex(16), secrets.token_hex(32)
        t = now()
        with self.lock:
            self._refresh()
            self.db.execute("INSERT INTO sessions (id,digest,a_token,a_name,a_key,created,expires,state) VALUES (?,?,?,?,?,?,?,'pending')",
                            (sid, digest, token, name, key, t, t + ttl))
        return {"session_id": sid, "token": token, "expires_at": t + ttl}

    def redeem(self, data):
        digest = code_digest(data["code"])
        key, name = data["public_key"], data["name"]
        validate_key(key)
        validate_name(name)
        with self.lock:
            self._refresh()
            row = self.db.execute("SELECT * FROM sessions WHERE digest=?", (digest,)).fetchone()
            if not row:
                return 404, {"error": "código inválido"}
            if row["state"] == "expired":
                return 410, {"error": "código vencido"}
            if row["state"] != "pending":
                return 409, {"error": "código usado o cancelado"}
            if row["attempts"] >= 5:
                return 429, {"error": "intentos agotados"}
            token = secrets.token_hex(32)
            # A successful redemption starts its own confirmation window.
            until = now() + 20
            self.db.execute("UPDATE sessions SET b_token=?,b_name=?,b_key=?,reserve_until=?,state='reserved',attempts=attempts+1 WHERE id=?",
                            (token, name, key, until, row["id"]))
            return 200, {"session_id": row["id"], "token": token, "reserve_until": until,
                         "peer_name": row["a_name"], "peer_public_key": row["a_key"]}

    def status(self, sid, token):
        with self.lock:
            self._refresh()
            row = self.db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
            if not row or token not in (row["a_token"], row["b_token"]):
                return 404, {"error": "sesión no encontrada"}
            is_a = token == row["a_token"]
            result = {"state": row["state"], "expires_at": row["expires"],
                      "session_until": row["session_until"]}
            if row["state"] in ("reserved", "paired"):
                result.update(peer_name=row["b_name"] if is_a else row["a_name"],
                              peer_public_key=row["b_key"] if is_a else row["a_key"])
            return 200, result

    def transition(self, sid, token, action):
        with self.lock:
            self._refresh()
            row = self.db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
            if not row or token not in (row["a_token"], row["b_token"]):
                return 404, {"error": "sesión no encontrada"}
            if action == "confirm":
                if token != row["a_token"] or row["state"] != "reserved":
                    return 409, {"error": "confirmación no autorizada"}
                until = now() + 3600
                self.db.execute("UPDATE sessions SET state='paired',session_until=? WHERE id=?", (until, sid))
                return 200, {"state": "paired", "session_until": until}
            if action == "close":
                self.db.execute("UPDATE sessions SET state='closed' WHERE id=?", (sid,))
                return 200, {"state": "closed"}
            return 404, {"error": "acción desconocida"}

    def relay_token(self, sid, role):
        with self.lock:
            self._refresh()
            row = self.db.execute("SELECT a_token,b_token,state FROM sessions WHERE id=?", (sid,)).fetchone()
            if not row or row["state"] != "paired":
                return None
            return row["a_token"] if role == "a" else row["b_token"]


class UDPRelay(threading.Thread):
    """Forwards ciphertext only. Endpoint registrations expire after 10 seconds."""

    def __init__(self, store, host, port):
        super().__init__(daemon=True)
        self.store = store
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((host, port))
        self.socket.settimeout(0.5)
        self.endpoints = {}
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            try:
                packet, address = self.socket.recvfrom(MAX_DATAGRAM + 1)
                sid, role, kind, payload = parse_relay_packet(packet)
                token = self.store.relay_token(sid, role)
                if token is None or not verify_relay_packet(packet, token) or kind not in (HELLO, DATA):
                    continue
                t = time.monotonic()
                pair = self.endpoints.setdefault(sid, {})
                pair[role] = (address, t)
                if kind == DATA and payload:
                    other = pair.get("b" if role == "a" else "a")
                    if other and t - other[1] < 10:
                        # Relay header is rebuilt with the recipient's token;
                        # it never touches or decrypts the encrypted payload.
                        with self.store.lock:
                            row = self.store.db.execute("SELECT a_token,b_token FROM sessions WHERE id=?", (sid,)).fetchone()
                        target_token = row["b_token"] if role == "a" else row["a_token"]
                        self.socket.sendto(relay_packet(sid, target_token,
                                                        "b" if role == "a" else "a", DATA, payload), other[0])
                if len(self.endpoints) > 1000:
                    self.endpoints = {key: value for key, value in self.endpoints.items()
                                      if any(t - entry[1] < 10 for entry in value.values())}
            except (socket.timeout, OSError, ValueError, TypeError):
                continue

    def close(self):
        self.stop.set()
        self.socket.close()


def validate_key(key):
    if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
        raise ValueError("clave pública inválida")


def validate_name(name):
    if not isinstance(name, str) or not 1 <= len(name) <= 32 or any(ord(c) < 32 for c in name):
        raise ValueError("nombre inválido")


def handler(store):
    attempts = {}
    attempts_lock = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= MAX_BODY:
                    return self.respond(413, {"error": "solicitud demasiado grande"})
                data = json.loads(self.rfile.read(size))
                path = urlparse(self.path).path.strip("/").split("/")
                if path == ["invites"]:
                    return self.respond(201, store.create(data))
                if path == ["invites", "redeem"]:
                    address = self.client_address[0]
                    with attempts_lock:
                        recent = [t for t in attempts.get(address, []) if time.monotonic() - t < 60]
                        if len(recent) >= 10:
                            attempts[address] = recent
                            return self.respond(429, {"error": "demasiados intentos; espera un minuto"})
                        recent.append(time.monotonic())
                        attempts[address] = recent
                    return self.respond(*store.redeem(data))
                if len(path) == 3 and path[0] == "sessions" and path[2] in ("confirm", "close"):
                    return self.respond(*store.transition(path[1], data["token"], path[2]))
                self.respond(404, {"error": "ruta desconocida"})
            except (ValueError, KeyError, TypeError, sqlite3.IntegrityError) as exc:
                self.respond(400, {"error": str(exc)})

        def do_GET(self):
            path = urlparse(self.path).path.strip("/").split("/")
            if len(path) == 3 and path[0] == "sessions" and path[2] == "status":
                # Credentials are in headers, never URLs or access logs.
                return self.respond(*store.status(path[1], self.headers.get("X-Session-Token", "")))
            self.respond(404, {"error": "ruta desconocida"})

        def log_message(self, fmt, *args):
            pass

    return Handler


def main():
    p = argparse.ArgumentParser(description="Coordinador experimental Switch 2")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--udp-port", type=int, default=8766)
    p.add_argument("--db", default="switch2_sessions.sqlite3")
    p.add_argument("--cert")
    p.add_argument("--key")
    args = p.parse_args()
    if args.host not in ("127.0.0.1", "localhost") and not (args.cert and args.key):
        p.error("se requiere TLS para escuchar fuera de localhost")
    store = Store(args.db)
    server = ThreadingHTTPServer((args.host, args.port), handler(store))
    if args.cert and args.key:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(args.cert, args.key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    relay = UDPRelay(store, args.host, args.udp_port)
    relay.start()
    print(f"Coordinador en {args.host}:{args.port}; relay UDP {args.udp_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
