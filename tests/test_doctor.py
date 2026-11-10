"""Driver decisions must distinguish absence from errors and avoid needless downloads."""
import contextlib
import io
import json
import unittest
import fnmatch
from pathlib import PurePosixPath
from unittest.mock import patch

from switch2_tunnel import doctor


class WindowsInventoryTests(unittest.TestCase):
    def row(self, **changes):
        row = dict(instance_id=r"USB\VID_148F&PID_7601\PRIVATE-SERIAL", name="802.11 USB WLAN",
                   error_code=0, service="netr28u", driver_inf="oem12.inf", wireless=True)
        row.update(changes)
        return row

    def test_installed_and_broken_drivers_are_not_replaced(self):
        for code, state in [(0, "installed"), (10, "driver_error"), (22, "driver_error"), (43, "driver_error")]:
            device = doctor.windows_devices([self.row(error_code=code)])[0]
            self.assertEqual(device["driver_state"], state)
            with patch.object(doctor, "powershell") as ps:
                doctor.repair(device, "Windows")
                ps.assert_not_called()

    def test_missing_known_device_can_request_repair(self):
        device = doctor.windows_devices([self.row(error_code=28, service=None, driver_inf=None)])[0]
        self.assertEqual(device["driver_state"], "missing")
        with patch.object(doctor, "powershell", return_value={"message": "No hay descarga"}) as ps:
            self.assertEqual(doctor.repair(device, "Windows"), "No hay descarga")
            self.assertEqual(ps.call_args.args[2], device["_instance_id"])

    def test_unknown_usb_wlan_is_candidate_not_permission_to_install(self):
        device = doctor.windows_devices([self.row(instance_id=r"USB\VID_ABCD&PID_1234\X", wireless=False,
                                                service=None, driver_inf=None, error_code=28)])[0]
        self.assertFalse(device["identity_confirmed"])
        with patch.object(doctor, "powershell") as ps:
            doctor.repair(device, "Windows")
            ps.assert_not_called()

    def test_ignore_ethernet_and_storage(self):
        for name in ["USB Ethernet", "USB Mass Storage"]:
            self.assertEqual(doctor.windows_devices([self.row(instance_id=r"USB\VID_ABCD&PID_1234\X",
                                                               name=name, wireless=False)]), [])

    def test_wireless_bluetooth_is_not_a_usb_wifi_adapter(self):
        self.assertEqual(doctor.windows_devices([self.row(instance_id=r"USB\VID_8087&PID_0026\X",
            name="Intel(R) Wireless Bluetooth(R)", service="BTHUSB", wireless=False)]), [])

    def test_json_does_not_export_serial_and_report_is_rechecked(self):
        before = doctor.windows_devices([self.row(error_code=28, service=None, driver_inf=None)])[0]
        after = doctor.windows_devices([self.row()])[0]
        with patch.object(doctor.platform, "system", return_value="Windows"), \
                patch.object(doctor, "inventory", side_effect=[[before], [after]]), \
                patch.object(doctor, "repair", return_value="Repaired"), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(doctor.main(["--json", "--repair"]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["devices"][0]["driver_state"], "installed")
        self.assertNotIn("PRIVATE-SERIAL", output.getvalue())


class LinuxInventoryTests(unittest.TestCase):
    def setUp(self):
        # Virtual sysfs: Linux names contain ':' and cannot be created on NTFS.
        files, directories, links = {}, set(), {}
        class SysPath:
            def __init__(self, value):
                self.value = value.value if isinstance(value, SysPath) else str(value)
            def __truediv__(self, value):
                return SysPath(str(PurePosixPath(self.value) / value))
            @property
            def name(self):
                return PurePosixPath(self.value).name
            def write_text(self, value):
                files[self.value] = value
            def read_text(self, **kwargs):
                if self.value not in files:
                    raise FileNotFoundError(self.value)
                return files[self.value]
            def mkdir(self, **kwargs):
                for parent in [PurePosixPath(self.value), *PurePosixPath(self.value).parents]:
                    directories.add(str(parent))
            def glob(self, pattern):
                return [SysPath(p) for p in sorted(set(files) | directories | set(links))
                        if str(PurePosixPath(p).parent) == self.value and fnmatch.fnmatchcase(PurePosixPath(p).name, pattern)]
            def is_symlink(self):
                return self.value in links
            def symlink_to(self, target, **kwargs):
                links[self.value] = target.value
            def exists(self):
                return self.value in files or self.value in directories or self.value in links
            def resolve(self):
                return SysPath(links.get(self.value, self.value))
        self.path_patch = patch.object(doctor, "Path", SysPath)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.root = SysPath("/sys")
        self.usb = self.root / "bus/usb/devices/1-2"
        self.interface = self.usb / "1-2:1.0"
        self.interface.mkdir(parents=True)
        (self.usb / "idVendor").write_text("148f")
        (self.usb / "idProduct").write_text("7601")
        (self.usb / "product").write_text("802.11 WLAN")
        (self.interface / "modalias").write_text("usb:v148Fp7601")

    def test_no_module_is_missing(self):
        devices = doctor.linux_devices(self.root, lambda args: (1, "", "not found"))
        self.assertEqual(devices[0]["driver_state"], "missing")
        self.assertEqual(devices[0]["expected_module"], "mt7601u")

    def test_missing_kmod_does_not_establish_driver_absence(self):
        device = doctor.linux_devices(self.root, lambda args: (-1, "", "command missing"))[0]
        self.assertEqual(device["driver_state"], "unknown")
        self.assertTrue(device["tools_unavailable"])

    def test_local_module_is_available_without_download(self):
        def runner(args):
            return (0, "mt7601u", "") if args[0] == "modprobe" else (0, "/lib/modules/kernel/drivers/net/wireless/mt7601u.ko", "")
        device = doctor.linux_devices(self.root, runner)[0]
        self.assertEqual(device["driver_state"], "available")
        calls = []
        doctor.repair_linux(device, runner=lambda args: (calls.append(args) or (0, "", "")), is_root=True)
        self.assertEqual(calls, [["modprobe", "mt7601u"]])

    def test_bound_driver_without_interface_is_error_not_missing(self):
        driver = self.root / "bus/usb/drivers/mt7601u"
        driver.mkdir(parents=True)
        (self.interface / "driver").symlink_to(driver, target_is_directory=True)
        device = doctor.linux_devices(self.root, lambda args: (1, "", ""))[0]
        self.assertEqual(device["driver_state"], "driver_error")

    def test_monitor_is_read_for_the_specific_phy(self):
        driver = self.root / "bus/usb/drivers/mt7601u"
        driver.mkdir(parents=True)
        (self.interface / "driver").symlink_to(driver)
        (self.interface / "net/wlan0").mkdir(parents=True)
        (self.root / "class/net/wlan0/wireless").mkdir(parents=True)
        phy = self.root / "class/ieee80211/phy1"
        phy.mkdir(parents=True)
        (self.root / "class/net/wlan0/phy80211").symlink_to(phy)
        calls = []
        def runner(args):
            calls.append(args)
            if args[0] == "iw":
                return 0, "Wiphy phy1\n\tSupported interface modes:\n\t\t * managed\n\t\t * monitor\n\tBand 1:\n", ""
            return 1, "", ""
        device = doctor.linux_devices(self.root, runner)[0]
        self.assertEqual(device["driver_state"], "installed")
        self.assertEqual(device["monitor"], "advertised")
        self.assertIn(["iw", "phy", "phy1", "info"], calls)

    def test_unknown_usb_is_not_assumed_wifi(self):
        (self.usb / "idVendor").write_text("abcd")
        (self.usb / "product").write_text("USB Ethernet")
        self.assertEqual(doctor.linux_devices(self.root, lambda args: (1, "", "")), [])


class LinuxRepairTests(unittest.TestCase):
    def device(self, **changes):
        row = dict(usb_id="148f:7601", name="MT7601U", identity_confirmed=True,
                   driver_state="missing", local_modules=[], expected_module="mt7601u")
        row.update(changes)
        return row

    def test_ubuntu_missing_module_recipe_and_failure_message(self):
        calls = []
        def runner(args, **kwargs):
            calls.append(args)
            if args[0] == "modinfo":
                return 1, "", "not found"
            return 0, "", ""
        message = doctor.repair_linux(self.device(), runner=runner, os_release={"ID": "ubuntu"},
                                      kernel="6.8.0-136-generic", is_root=True)
        self.assertEqual(calls[0], ["modinfo", "mt7601u"])
        self.assertEqual(calls[1], ["apt-get", "install", "--yes", "--no-install-recommends", "linux-modules-extra-6.8.0-136-generic"])
        self.assertEqual(calls[2], ["modprobe", "mt7601u"])
        self.assertIn("cargado", message)

    def test_installed_driver_unknown_chip_nonroot_and_wsl_do_not_download(self):
        for device, release, kernel, root in [
            (self.device(driver_state="installed"), {"ID": "ubuntu"}, "6.8.0-136-generic", True),
            (self.device(expected_module=None), {"ID": "ubuntu"}, "6.8.0-136-generic", True),
            (self.device(), {"ID": "debian"}, "6.1.0", True),
            (self.device(), {"ID": "ubuntu"}, "6.6.87.2-microsoft-standard-WSL2", True),
            (self.device(), {"ID": "ubuntu"}, "6.8.0-136-generic", False),
        ]:
            with self.subTest(device=device, kernel=kernel):
                with patch.object(doctor, "run") as runner:
                    doctor.repair_linux(device, runner=runner, os_release=release, kernel=kernel, is_root=root)
                    runner.assert_not_called()

    def test_failed_local_load_never_falls_through_to_download(self):
        calls = []
        def runner(args):
            calls.append(args)
            return 1, "", "firmware missing"
        message = doctor.repair_linux(self.device(driver_state="available", local_modules=["mt7601u"]), runner=runner, is_root=True)
        self.assertEqual(calls, [["modprobe", "mt7601u"]])
        self.assertIn("No se descargó otro", message)

    def test_module_installed_after_inventory_is_not_downloaded_again(self):
        calls = []
        def runner(args):
            calls.append(args)
            return 0, "", ""
        doctor.repair_linux(self.device(), runner=runner, os_release={"ID": "ubuntu"}, kernel="6.8.0-136-generic", is_root=True)
        self.assertEqual(calls, [["modinfo", "mt7601u"], ["modprobe", "mt7601u"]])

    def test_failed_package_install_gives_exact_package(self):
        def runner(args, **kwargs):
            return 1, "", "offline"
        message = doctor.repair_linux(self.device(), runner=runner, os_release={"ID": "ubuntu"}, kernel="6.8.0-136-generic", is_root=True)
        self.assertIn("linux-modules-extra-6.8.0-136-generic", message)
        self.assertIn("offline", message)


if __name__ == "__main__":
    unittest.main()
