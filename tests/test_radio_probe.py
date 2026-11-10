import struct
import unittest

from ldn_receive_probe import frame_class, is_ldn_advertisement, radiotap_frequency
from switch2_tunnel.radio import frame_bssid


class RadioProbeTests(unittest.TestCase):
    def test_radiotap_frequency_uses_packet_header(self):
        # TSFT + flags + rate + channel, with channel aligned to two bytes.
        header = struct.pack("<BBHI", 0, 0, 22, 0b1111)
        fields = b"\0" * 8 + b"\0" + b"\x02" + struct.pack("<HH", 2462, 0)
        self.assertEqual(radiotap_frequency(header + fields + b"frame"), (22, 2462))

    def test_missing_frequency_and_malformed_header(self):
        self.assertEqual(radiotap_frequency(struct.pack("<BBHI", 0, 0, 8, 0)), (8, None))
        with self.assertRaises(ValueError):
            radiotap_frequency(b"\x00\x00\xff\xff\0\0\0\0")

    def test_ldn_classification(self):
        frame = bytearray(32)
        frame[0] = 0xD0
        frame[24:29] = b"\x7f\x00\x22\xaa\x04"
        frame[30:32] = (257).to_bytes(2, "big")
        self.assertEqual(frame_class(frame), "action")
        self.assertTrue(is_ldn_advertisement(frame))
        frame[28] = 5
        self.assertFalse(is_ldn_advertisement(frame))

    def test_bssid_position_depends_on_data_direction(self):
        frame = bytearray(24)
        frame[4:10] = b"\x01" * 6
        frame[10:16] = b"\x02" * 6
        frame[16:22] = b"\x03" * 6
        frame[0:2] = (0x0008 | 0x0100).to_bytes(2, "little")
        self.assertEqual(frame_bssid(frame), b"\x01" * 6)
        frame[0:2] = (0x0008 | 0x0200).to_bytes(2, "little")
        self.assertEqual(frame_bssid(frame), b"\x02" * 6)


if __name__ == "__main__":
    unittest.main()
