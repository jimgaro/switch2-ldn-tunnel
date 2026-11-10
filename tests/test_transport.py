import socket
import tempfile
import time
import unittest

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from switch2_tunnel.common import code_digest, make_code
from switch2_tunnel.coordinator import Store, UDPRelay
from switch2_tunnel.transport import Cipher, DATA, HELLO, Link, parse_relay_packet, relay_packet, verify_relay_packet


def public_hex(private):
    return private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.a_private = X25519PrivateKey.generate()
        self.b_private = X25519PrivateKey.generate()
        self.sid = "01" * 16
        self.a_cipher = Cipher(self.a_private, public_hex(self.b_private), self.sid, "a")
        self.b_cipher = Cipher(self.b_private, public_hex(self.a_private), self.sid, "b")

    def test_cipher_roundtrip_replay_and_tamper(self):
        encrypted = self.a_cipher.encrypt(b"opaque frame")
        self.assertNotIn(b"opaque frame", encrypted)
        self.assertEqual(self.b_cipher.decrypt(encrypted), b"opaque frame")
        with self.assertRaises(ValueError):
            self.b_cipher.decrypt(encrypted)
        corrupted = bytearray(self.a_cipher.encrypt(b"second"))
        corrupted[-1] ^= 1
        with self.assertRaises(Exception):
            self.b_cipher.decrypt(bytes(corrupted))
        self.assertEqual(self.a_cipher.decrypt(self.b_cipher.encrypt(b"reply")), b"reply")

    def test_relay_only_for_paired_tokens(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder + "/sessions.db")
            code = make_code()
            a = store.create({"digest": code_digest(code), "public_key": public_hex(self.a_private), "name": "A"})
            _, b = store.redeem({"code": code, "public_key": public_hex(self.b_private), "name": "B"})
            relay = UDPRelay(store, "127.0.0.1", 0)
            relay.start()
            address = relay.socket.getsockname()
            left = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            right = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            right.settimeout(0.3)
            try:
                left.sendto(relay_packet(a["session_id"], a["token"], "a", HELLO), address)
                right.sendto(relay_packet(a["session_id"], b["token"], "b", HELLO), address)
                left.sendto(relay_packet(a["session_id"], a["token"], "a", DATA, b"ciphertext"), address)
                with self.assertRaises(socket.timeout):
                    right.recvfrom(2300)  # not paired yet
                store.transition(a["session_id"], a["token"], "confirm")
                left.sendto(relay_packet(a["session_id"], a["token"], "a", HELLO), address)
                right.sendto(relay_packet(a["session_id"], b["token"], "b", HELLO), address)
                time.sleep(0.05)
                left.sendto(relay_packet(a["session_id"], a["token"], "a", DATA, b"ciphertext"), address)
                packet, _ = right.recvfrom(2300)
                sid, role, kind, payload = parse_relay_packet(packet)
                self.assertTrue(verify_relay_packet(packet, b["token"]))
                self.assertNotIn(bytes.fromhex(b["token"]), packet)
                self.assertEqual((sid, role, kind, payload),
                                 (a["session_id"], "b", DATA, b"ciphertext"))
            finally:
                left.close()
                right.close()
                relay.close()
                relay.join(timeout=1)
                store.db.close()

    def test_two_links_exchange_encrypted_datagram(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder + "/sessions.db")
            code = make_code()
            a = store.create({"digest": code_digest(code), "public_key": public_hex(self.a_private), "name": "A"})
            _, b = store.redeem({"code": code, "public_key": public_hex(self.b_private), "name": "B"})
            store.transition(a["session_id"], a["token"], "confirm")
            relay = UDPRelay(store, "127.0.0.1", 0)
            relay.start()
            port = relay.socket.getsockname()[1]
            left = Link("http://127.0.0.1:8765", port, a["session_id"], a["token"], "a",
                        Cipher(self.a_private, public_hex(self.b_private), a["session_id"], "a"))
            right = Link("http://127.0.0.1:8765", port, a["session_id"], b["token"], "b",
                         Cipher(self.b_private, public_hex(self.a_private), a["session_id"], "b"))
            try:
                left.hello()
                right.hello()
                time.sleep(0.05)
                left.send(b"opaque frame")
                self.assertEqual(right.receive(), b"opaque frame")
                self.assertIsNone(right.receive())
            finally:
                left.close()
                right.close()
                relay.close()
                relay.join(timeout=1)
                store.db.close()


if __name__ == "__main__":
    unittest.main()
