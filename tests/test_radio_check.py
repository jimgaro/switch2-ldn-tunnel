import os
import socket
import struct
import unittest
from unittest.mock import Mock, patch

from switch2_tunnel import radio_check


class RadioCheckTests(unittest.TestCase):
    def device(self):
        return dict(driver_state="installed", monitor="advertised", phy="phy1")

    def runner(self, active=False, delete_fails=False):
        calls = []
        def run(args):
            calls.append(args)
            if args == ["iw", "dev"]:
                return 0, "phy#0\n Interface internet0\nphy#1\n Interface wlan1", ""
            if args[0] == "ip" and "show" in args:
                return 0, "3: wlan1: <BROADCAST,MULTICAST" + (",UP" if active else "") + ">", ""
            if args[-1] == "del" and delete_fails:
                return 1, "", "busy"
            return 0, "", ""
        return calls, run

    def test_active_phy_is_never_disconnected(self):
        calls, runner = self.runner(active=True)
        with self.assertRaisesRegex(RuntimeError, "DOWN"):
            radio_check.ensure_idle("phy1", runner)
        self.assertFalse(any("set" in call or "add" in call for call in calls))

    def check(self, runner, packet=None, open_error=False):
        radio = Mock()
        if packet is not None:
            radio.recv.return_value = packet
        factory = Mock(side_effect=OSError("socket failed")) if open_error else Mock(return_value=radio)
        with patch.object(socket, "AF_PACKET", 17, create=True), patch.object(os, "geteuid", return_value=0, create=True):
            result = radio_check.inspect(self.device(), seconds=1, runner=runner, socket_factory=factory,
                                         clock=Mock(side_effect=[0, 0.1, 2]))
        return radio, result

    def test_passive_ldn_detection_and_monitor_cleanup(self):
        calls, runner = self.runner()
        frame = bytearray(32)
        frame[0] = 0xD0
        frame[24:29] = b"\x7f\x00\x22\xaa\x04"
        frame[30:32] = (257).to_bytes(2, "big")
        packet = struct.pack("<BBHIHH", 0, 0, 12, 1 << 3, 2462, 0) + frame
        radio, result = self.check(runner, packet)
        self.assertEqual(result["status"], "receive_verified")
        self.assertEqual(result["ldn_advertisements"], 1)
        self.assertEqual(result["transmit"], "not_tested")
        radio.send.assert_not_called()
        radio.close.assert_called_once()
        self.assertEqual(calls[-1][-1], "del")
        self.assertFalse(any("down" in call for call in calls))

    def test_malformed_capture_is_inconclusive(self):
        _, runner = self.runner()
        _, result = self.check(runner, b"bad")
        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(result["malformed_packets"], 1)

    def test_cleanup_runs_even_if_socket_open_fails(self):
        calls, runner = self.runner()
        with self.assertRaisesRegex(RuntimeError, "socket failed"):
            self.check(runner, open_error=True)
        self.assertEqual(calls[-1][-1], "del")

    def test_cleanup_failure_is_visible(self):
        _, runner = self.runner(delete_fails=True)
        _, result = self.check(runner, b"bad")
        self.assertIn("busy", result["cleanup_errors"][0])


if __name__ == "__main__":
    unittest.main()
