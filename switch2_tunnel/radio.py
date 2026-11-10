"""Experimental Linux monitor-mode adapter; it cannot provide firmware ACKs."""
import hashlib
import socket
import struct
import time

from ldn_receive_probe import frame_class, is_ldn_advertisement, radiotap_metadata

MAX_FRAME = 1800
RADIO_PREFIX = b"F"


def frame_bssid(frame):
    if len(frame) < 24:
        return None
    control = int.from_bytes(frame[:2], "little")
    kind = (control >> 2) & 3
    if kind == 0:
        return frame[16:22]
    if kind == 2:
        to_ds = bool(control & 0x0100)
        from_ds = bool(control & 0x0200)
        if to_ds and not from_ds:
            return frame[4:10]
        if from_ds and not to_ds:
            return frame[10:16]
        if not to_ds and not from_ds:
            return frame[16:22]
    return None


class Radio:
    def __init__(self, interface, frequency):
        self.interface = interface
        self.frequency = frequency
        self.socket = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
        self.socket.bind((interface, 0))
        self.socket.settimeout(0.1)
        self.bssids = set()
        self.injected = {}
        self.captured = self.transmitted = self.discarded = 0

    def _candidate(self, frame):
        kind = frame_class(frame)
        if kind not in ("action", "beacon", "probe_response", "probe_request",
                        "authentication", "association_request", "association_response", "data"):
            return False
        if len(frame) < 24:
            return False
        if is_ldn_advertisement(frame):
            self.bssids.add(frame_bssid(frame))
            return True
        # Restrict forwarding to the LDN BSSID learned from an advertisement.
        return frame_bssid(frame) in self.bssids

    def receive(self):
        try:
            packet = self.socket.recv(4096)
            offset, frequency, flags = radiotap_metadata(packet)
            frame = packet[offset:]
            if flags is not None and flags & 0x10:
                frame = frame[:-4] if len(frame) >= 4 else b""
            if frequency != self.frequency or not 24 <= len(frame) <= MAX_FRAME:
                self.discarded += 1
                return None
            digest = hashlib.blake2s(frame, digest_size=8).digest()
            t = time.monotonic()
            if self.injected.get(digest, 0) > t:
                return None
            if not self._candidate(frame):
                return None
            self.captured += 1
            return RADIO_PREFIX + struct.pack("!HH", frequency, len(frame)) + frame
        except socket.timeout:
            return None
        except (ValueError, OSError):
            self.discarded += 1
            return None

    def send(self, payload):
        if len(payload) < 5 or payload[:1] != RADIO_PREFIX:
            return False
        frequency, length = struct.unpack_from("!HH", payload, 1)
        frame = payload[5:]
        if frequency != self.frequency or length != len(frame) or not 24 <= length <= MAX_FRAME:
            self.discarded += 1
            return False
        if not self._candidate(frame):
            return False
        digest = hashlib.blake2s(frame, digest_size=8).digest()
        self.injected[digest] = time.monotonic() + 2
        if len(self.injected) > 2048:
            t = time.monotonic()
            self.injected = {key: until for key, until in self.injected.items() if until > t}
        # Minimal radiotap header; driver/firmware still decide ACK and PHY.
        self.socket.send(b"\x00\x00\x08\x00\x00\x00\x00\x00" + frame)
        self.transmitted += 1
        return True

    def close(self):
        self.socket.close()
