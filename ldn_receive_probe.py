"""Passive 802.11/LDN survey for the Linux monitor-mode test radio.

Run as root. The probe changes listening channel but never transmits frames or
stores payloads. Frequency comes from each frame's radiotap header when present.
"""

import argparse
import collections
import hashlib
import socket
import struct
import subprocess
import time


def radiotap_metadata(packet):
    """Return (header length, MHz or None, flags or None)."""
    if len(packet) < 8 or packet[0] != 0:
        raise ValueError("invalid radiotap header")
    length = struct.unpack_from("<H", packet, 2)[0]
    if length < 8 or length > len(packet):
        raise ValueError("invalid radiotap length")
    offset = 4
    words = []
    while True:
        if offset + 4 > length or len(words) >= 8:
            raise ValueError("invalid radiotap bitmap")
        word = struct.unpack_from("<I", packet, offset)[0]
        words.append(word)
        offset += 4
        if not word & (1 << 31):
            break
    first = words[0]
    flags = None
    frequency = None
    for bit, alignment, size in ((0, 8, 8), (1, 1, 1), (2, 1, 1), (3, 2, 4)):
        if first & (1 << bit):
            offset += (-offset) % alignment
            if offset + size > length:
                raise ValueError("truncated radiotap field")
            if bit == 1:
                flags = packet[offset]
            if bit == 3:
                frequency = struct.unpack_from("<H", packet, offset)[0]
            offset += size
    return length, frequency, flags


def radiotap_frequency(packet):
    length, frequency, _ = radiotap_metadata(packet)
    return length, frequency


def frame_class(frame):
    if len(frame) < 2:
        return "short"
    control = int.from_bytes(frame[:2], "little")
    kind = (control >> 2) & 3
    subtype = (control >> 4) & 15
    if kind == 0:
        return {4: "probe_request", 5: "probe_response", 8: "beacon",
                11: "authentication", 0: "association_request",
                1: "association_response", 13: "action"}.get(subtype, "management_other")
    if kind == 1:
        return {13: "ack", 11: "rts", 12: "cts"}.get(subtype, "control_other")
    if kind == 2:
        return "data"
    return "other"


def is_ldn_advertisement(frame):
    return (len(frame) >= 32 and frame_class(frame) == "action"
            and frame[24] == 127 and frame[25:28] == b"\x00\x22\xaa"
            and frame[28] == 4 and int.from_bytes(frame[30:32], "big") == 257)


def set_channel(interface, channel):
    result = subprocess.run(["iw", "dev", interface, "set", "channel", str(channel)],
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("interface")
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--channel", type=int, help="fix one channel instead of hopping 1/6/11")
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    channels = (args.channel,) if args.channel else (1, 6, 11)
    counts = collections.Counter()
    frequencies = collections.Counter()
    transmitters = collections.Counter()
    radio = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
    radio.bind((args.interface, 0))
    radio.settimeout(0.2)
    started = time.monotonic()
    next_hop = started
    channel_index = -1
    print(f"Passive survey for {args.seconds}s on channel(s) {channels}", flush=True)
    try:
        while time.monotonic() - started < args.seconds:
            now = time.monotonic()
            if now >= next_hop:
                channel_index = (channel_index + 1) % len(channels)
                set_channel(args.interface, channels[channel_index])
                next_hop = now + 0.8 if len(channels) > 1 else float("inf")
            try:
                packet = radio.recv(4096)
            except socket.timeout:
                continue
            try:
                header_length, frequency = radiotap_frequency(packet)
            except ValueError:
                counts["malformed_radiotap"] += 1
                continue
            frame = packet[header_length:]
            kind = frame_class(frame)
            counts[kind] += 1
            if frequency is not None:
                frequencies[frequency] += 1
            if is_ldn_advertisement(frame):
                counts["ldn_advertisement"] += 1
                transmitter = hashlib.blake2s(frame[10:16], digest_size=4).hexdigest()
                transmitters[transmitter] += 1
                print(f"LDN advertisement: frequency={frequency or 'unknown'} MHz "
                      f"transmitter_id={transmitter}", flush=True)
    finally:
        radio.close()
    print(f"Frame classes: {dict(counts)}", flush=True)
    print(f"Radiotap frequencies (MHz): {dict(frequencies)}", flush=True)
    print(f"LDN transmitter IDs: {dict(transmitters)}", flush=True)
    print("Visible ACK/auth/association counts do not prove the radio can mediate them.", flush=True)


if __name__ == "__main__":
    main()
