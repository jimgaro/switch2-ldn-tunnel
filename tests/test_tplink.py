import contextlib
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from switch2_tunnel import doctor, tplink


class TplinkTests(unittest.TestCase):
    def setUp(self):
        self.workspace = Path.cwd().resolve()
        self.temp = tempfile.TemporaryDirectory(prefix=".test-temp-", dir=self.workspace)
        self.path = Path(self.temp.name).resolve()
        self.assertTrue(self.path.is_relative_to(self.workspace))
        self.addCleanup(self.temp.cleanup)

    def device(self, **changes):
        device = dict(usb_id="0bda:8179", name="USB WLAN", driver_state="missing",
                      identity_confirmed=True, monitor="unknown", _instance_id=r"USB\VID_0BDA&PID_8179\X")
        device.update(changes)
        return device

    def test_revision_does_not_guess_a_different_hardware_version(self):
        for value, expected in [("V2", "2"), ("2.0", "2"), ("V3", "3"), ("3.0", "3")]:
            self.assertEqual(tplink.package_for(value)[0], expected)
        for value in [None, "", "1", "3.46", "3.60", "4.60"]:
            with self.assertRaises(ValueError):
                tplink.package_for(value)

    def test_no_revision_or_existing_driver_never_downloads(self):
        for device, revision in [(self.device(), None), (self.device(driver_state="installed"), "3.0")]:
            with patch.object(tplink, "acquire") as acquire, patch.object(doctor, "powershell") as ps:
                doctor.repair(device, "Windows", "TL-WN725N", revision, self.path)
                acquire.assert_not_called()
                ps.assert_not_called()

    def test_mismatching_usb_does_not_trigger_package_or_local_repair(self):
        with patch.object(tplink, "acquire") as acquire, patch.object(doctor, "powershell") as ps:
            message = tplink.repair_windows(self.device(usb_id="2357:010c"), "3.0", self.path)
            self.assertIn("no coincide", message)
            acquire.assert_not_called()
            ps.assert_not_called()

    def test_local_driver_prevents_official_download(self):
        with patch.object(doctor, "powershell", return_value={"state": "manual", "message": "Local driver found"}), \
                patch.object(tplink, "acquire") as acquire:
            self.assertEqual(tplink.repair_windows(self.device(), "3.0", self.path), "Local driver found")
            acquire.assert_not_called()

    def test_v3_uses_verified_inf_after_local_absence(self):
        with patch.object(doctor, "powershell", side_effect=[{"state": "missing", "message": "missing"}, {"message": "installed"}]) as ps, \
                patch.object(tplink, "acquire", return_value=self.path / "original.zip"), \
                patch.object(tplink, "windows_architecture", return_value="64bit"), \
                patch.object(tplink, "extract_v3_driver", return_value=self.path / "netrtwlanu.inf"):
            self.assertEqual(tplink.repair_windows(self.device(), "3.0", self.path), "installed")
            self.assertIn("-DriverInf", ps.call_args.args)

    def test_v2_falls_back_to_manual_without_executing_setup(self):
        with patch.object(doctor, "powershell", return_value={"state": "missing", "message": "missing"}) as ps, \
                patch.object(tplink, "acquire", return_value=self.path / "v2.zip"), \
                patch.object(tplink, "windows_architecture", return_value="64bit"):
            message = tplink.repair_windows(self.device(), "2.0", self.path)
            self.assertIn("manualmente", message)
            self.assertEqual(ps.call_count, 1)

    def test_download_url_is_limited_to_official_tls_endpoint(self):
        for url in ["http://static.tp-link.com/file.zip", "https://evil.example/file.zip", "https://static.tp-link.com.evil.example/file.zip"]:
            with self.assertRaises(ValueError):
                tplink.validate_url(url)

    def test_corrupt_cache_is_rejected_without_network(self):
        package = tplink.PACKAGES["3"]
        (self.path / package["filename"]).write_bytes(b"bad zip")
        with patch.object(tplink.urllib.request, "build_opener") as opener:
            with self.assertRaises(ValueError):
                tplink.acquire("3", self.path, download=True)
            opener.assert_not_called()

    def test_existing_download_in_progress_is_not_deleted(self):
        partial = self.path / (tplink.PACKAGES["3"]["filename"] + ".part")
        partial.write_bytes(b"another invocation")
        with self.assertRaises(FileExistsError):
            tplink.acquire("3", self.path, download=True)
        self.assertEqual(partial.read_bytes(), b"another invocation")

    def test_architecture_uses_host_not_python_bitness_and_rejects_arm(self):
        with patch.dict(os.environ, {"PROCESSOR_ARCHITECTURE": "x86", "PROCESSOR_ARCHITEW6432": "AMD64"}, clear=True):
            self.assertEqual(tplink.windows_architecture(), "64bit")
        with patch.dict(os.environ, {"PROCESSOR_ARCHITECTURE": "ARM64"}, clear=True):
            with self.assertRaises(ValueError):
                tplink.windows_architecture()

    def test_real_v3_package_contains_expected_x86_and_x64_driver_dependencies(self):
        archive = Path(__file__).resolve().parents[1] / "drivers/cache" / tplink.PACKAGES["3"]["filename"]
        if not archive.exists():
            self.skipTest("Optional original official package is not in this checkout")
        for architecture in ("32bit", "64bit"):
            inf = tplink.extract_v3_driver(archive, self.path, architecture)
            text = inf.read_text(encoding="utf-16")
            self.assertIn(r"USB\VID_0BDA&PID_8179", text)
            self.assertTrue(inf.with_suffix(".cat").is_file())
            self.assertTrue((inf.parent / "rtwlanu.sys").is_file())

    def test_linux_rtl8xxxu_recipe_requires_kernel_and_matching_alias(self):
        device = self.device(expected_module="rtl8xxxu", local_modules=[], _aliases=["usb:v0BDAp8179d0200dc00dsc00dp00icFFiscFFipFFin00"])
        calls = []
        def runner(args, **kwargs):
            calls.append(args)
            if args == ["modinfo", "rtl8xxxu"]:
                return 1, "", "module absent"
            if args[:3] == ["modinfo", "-F", "alias"]:
                return 0, "usb:v0BDAp8179d*dc*dsc*dp*icFFiscFFipFFin*", ""
            return 0, "", ""
        with patch.object(doctor, "ensure_tplink_firmware", return_value=None):
            message = doctor.repair_linux(device, runner=runner, os_release={"ID": "ubuntu"}, kernel="6.8.0-136-generic", is_root=True)
        self.assertIn("rtl8xxxu cargado", message)
        self.assertEqual(calls[-1], ["modprobe", "rtl8xxxu"])
        calls.clear()
        doctor.repair_linux(device, runner=runner, os_release={"ID": "ubuntu"}, kernel="5.15.0-100-generic", is_root=True)
        self.assertEqual(calls, [])

    def test_no_matching_alias_never_loads_module(self):
        device = self.device(expected_module="rtl8xxxu", local_modules=[], _aliases=["usb:v0BDAp8179d*"])
        calls = []
        def runner(args, **kwargs):
            calls.append(args)
            return 0, "usb:v0BDAp9999d*", ""
        doctor.repair_linux(device, runner=runner, os_release={"ID": "ubuntu"}, kernel="6.8.0-136-generic", is_root=True)
        self.assertNotIn(["modprobe", "rtl8xxxu"], calls)
        self.assertFalse(any(args[0] == "apt-get" for args in calls))

    def test_existing_compressed_firmware_prevents_package_download(self):
        firmware = self.path / "rtlwifi"
        firmware.mkdir()
        (firmware / "rtl8188eufw.bin.zst").write_bytes(b"compressed firmware placeholder")
        with patch.object(doctor, "run") as runner:
            self.assertIsNone(doctor.ensure_tplink_firmware(runner, {"ID": "ubuntu"}, [self.path]))
            runner.assert_not_called()

    def test_missing_firmware_installs_only_its_distro_package(self):
        calls = []
        def runner(args, **kwargs):
            calls.append(args)
            firmware = self.path / "rtlwifi"
            firmware.mkdir()
            (firmware / "rtl8188eufw.bin").write_bytes(b"firmware placeholder")
            return 0, "", ""
        self.assertIsNone(doctor.ensure_tplink_firmware(runner, {"ID": "debian"}, [self.path]))
        self.assertEqual(calls, [["apt-get", "install", "--yes", "--no-install-recommends", "firmware-realtek"]])


if __name__ == "__main__":
    unittest.main()
