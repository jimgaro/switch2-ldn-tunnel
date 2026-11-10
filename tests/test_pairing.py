import tempfile
import unittest

from switch2_tunnel.common import code_digest, make_code, normalize_code
from switch2_tunnel.coordinator import Store


KEY_A = "a" * 64
KEY_B = "b" * 64


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name + "/sessions.db")
        self.code = make_code()
        self.a = self.store.create({"digest": code_digest(self.code), "public_key": KEY_A, "name": "A"})

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_code_format_and_single_use(self):
        self.assertEqual(len(normalize_code(self.code)), 16)
        status, b = self.store.redeem({"code": self.code.lower(), "public_key": KEY_B, "name": "B"})
        self.assertEqual(status, 200)
        status, _ = self.store.redeem({"code": self.code, "public_key": KEY_B, "name": "C"})
        self.assertEqual(status, 409)
        self.assertEqual(self.store.transition(self.a["session_id"], b["token"], "confirm")[0], 409)
        self.assertEqual(self.store.transition(self.a["session_id"], self.a["token"], "confirm")[0], 200)
        self.assertEqual(self.store.status(self.a["session_id"], b["token"])[1]["state"], "paired")
        self.assertEqual(self.store.redeem({"code": self.code, "public_key": KEY_B, "name": "C"})[0], 409)

    def test_expiry_and_authorization(self):
        self.store.db.execute("UPDATE sessions SET expires=0 WHERE id=?", (self.a["session_id"],))
        self.assertEqual(self.store.redeem({"code": self.code, "public_key": KEY_B, "name": "B"})[0], 410)
        self.assertEqual(self.store.status(self.a["session_id"], "invalid")[0], 404)

    def test_close_is_final(self):
        self.assertEqual(self.store.transition(self.a["session_id"], self.a["token"], "close")[0], 200)
        self.assertEqual(self.store.redeem({"code": self.code, "public_key": KEY_B, "name": "B"})[0], 409)


if __name__ == "__main__":
    unittest.main()
