"""End-to-end encrypted UDP datagrams carried by an untrusted relay."""
import hashlib
import hmac
import socket
import struct
import threading
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"S2T1"
HELLO = 0
DATA = 1
MAX_DATAGRAM = 2300
MAX_PLAINTEXT = 1900


def relay_packet(session_id, token, role, kind, payload=b""):
    if role not in ("a", "b") or len(payload) > MAX_DATAGRAM - 38:
        raise ValueError("datagram too large")
    body = MAGIC + bytes.fromhex(session_id) + role.encode("ascii") + bytes([kind]) + payload
    tag = hmac.new(bytes.fromhex(token), body, hashlib.sha256).digest()[:16]
    return body + tag


def parse_relay_packet(packet):
    if len(packet) < 38 or len(packet) > MAX_DATAGRAM or packet[:4] != MAGIC:
        raise ValueError("invalid relay packet")
    role = packet[20:21].decode("ascii")
    if role not in ("a", "b"):
        raise ValueError("invalid role")
    return packet[4:20].hex(), role, packet[21], packet[22:-16]


def verify_relay_packet(packet, token):
    expected = hmac.new(bytes.fromhex(token), packet[:-16], hashlib.sha256).digest()[:16]
    return hmac.compare_digest(expected, packet[-16:])


class Cipher:
    def __init__(self, private_key, peer_public_hex, session_id, role):
        if role not in ("a", "b"):
            raise ValueError("invalid role")
        sid = bytes.fromhex(session_id)
        if len(sid) != 16:
            raise ValueError("invalid session id")
        peer = X25519PublicKey.from_public_bytes(bytes.fromhex(peer_public_hex))
        shared = private_key.exchange(peer)
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=sid,
                   info=b"switch2-experimental-datagrams-v1").derive(shared)
        self.aead = AESGCM(key)
        self.sid = sid
        self.send_prefix = b"S2A0" if role == "a" else b"S2B0"
        self.recv_prefix = b"S2B0" if role == "a" else b"S2A0"
        self.sequence = 0
        self.highest = -1
        self.seen = set()

    def encrypt(self, payload):
        if len(payload) > MAX_PLAINTEXT:
            raise ValueError("payload too large")
        sequence = self.sequence
        self.sequence += 1
        nonce = self.send_prefix + sequence.to_bytes(8, "big")
        return sequence.to_bytes(8, "big") + self.aead.encrypt(nonce, payload, self.sid)

    def decrypt(self, packet):
        if len(packet) < 24:
            raise ValueError("ciphertext too short")
        sequence = int.from_bytes(packet[:8], "big")
        if sequence in self.seen or sequence + 256 <= self.highest:
            raise ValueError("duplicate or stale datagram")
        nonce = self.recv_prefix + packet[:8]
        payload = self.aead.decrypt(nonce, packet[8:], self.sid)
        self.highest = max(self.highest, sequence)
        self.seen.add(sequence)
        self.seen = {n for n in self.seen if n + 256 > self.highest}
        return payload


def resolve_relay(url, port):
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return parsed.hostname, port


class Link:
    def __init__(self, server_url, port, sid, token, role, cipher):
        self.sid, self.token, self.role, self.cipher = sid, token, role, cipher
        host, port = resolve_relay(server_url, port)
        self.address = (socket.gethostbyname(host), port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(0.2)
        self.send_lock = threading.Lock()
        self.sent = self.received = self.lost = 0
        self.last_hello = 0

    def hello(self):
        if time.monotonic() - self.last_hello >= 2:
            self.socket.sendto(relay_packet(self.sid, self.token, self.role, HELLO), self.address)
            self.last_hello = time.monotonic()

    def send(self, payload):
        with self.send_lock:
            self.hello()
            self.socket.sendto(relay_packet(self.sid, self.token, self.role, DATA,
                                            self.cipher.encrypt(payload)), self.address)
            self.sent += 1

    def receive(self):
        try:
            packet, address = self.socket.recvfrom(MAX_DATAGRAM)
        except socket.timeout:
            return None
        if address != self.address:
            return None
        try:
            sid, role, kind, payload = parse_relay_packet(packet)
            if (sid != self.sid or role != self.role or kind != DATA
                    or not verify_relay_packet(packet, self.token)):
                return None
            plaintext = self.cipher.decrypt(payload)
            self.received += 1
            return plaintext
        except Exception:
            self.lost += 1
            return None

    def close(self):
        self.socket.close()


def probe_payload(sequence):
    return b"P" + struct.pack("!IQ", sequence, time.monotonic_ns())


def probe_reply(payload):
    return b"R" + payload[1:]
