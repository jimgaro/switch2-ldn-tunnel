import hashlib
import re
import secrets
import time

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def make_code():
    digest = hashlib.sha256(b"switch2-pair-v1" + secrets.token_bytes(16)).digest()
    value = int.from_bytes(digest[:10], "big")
    chars = "".join(ALPHABET[(value >> (5 * (15 - i))) & 31] for i in range(16))
    return "-".join(chars[i:i + 4] for i in range(0, 16, 4))


def normalize_code(code):
    value = re.sub(r"[-\s]", "", code.upper())
    if len(value) != 16 or any(c not in ALPHABET for c in value):
        raise ValueError("código inválido")
    return value


def code_digest(code):
    return hashlib.sha256(normalize_code(code).encode("ascii")).hexdigest()


def fingerprint(public_key):
    return hashlib.sha256(bytes.fromhex(public_key)).hexdigest()[:16]


def now():
    return time.time()
