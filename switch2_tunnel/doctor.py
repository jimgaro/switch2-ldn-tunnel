"""USB Wi-Fi inventory and conservative missing-driver repair (standard library only)."""
import argparse
import base64
import fnmatch
import json
import os
import platform
import re
import subprocess
from pathlib import Path


# USB IDs identify chip families, not necessarily a retail model or hardware revision.
KNOWN = {
    "148f:7601": ("MediaTek/Ralink MT7601U", "mt7601u"),
    "0bda:8176": ("Realtek RTL8188CUS (modelo comercial y revisión por confirmar)", "rtl8192cu"),
    "0bda:8179": ("Realtek RTL8188EU (TL-WN725N V2/V3 candidato; confirmar etiqueta)", "rtl8xxxu"),
    "2357:010c": ("TP-Link TL-WN722N V2 / RTL8188EU", "rtl8xxxu"),
}
TP_LINK = "https://www.tp-link.com/support/download/"
WIRELESS_NAME = re.compile(r"wi[ -]?fi|wireless|wlan|802\.11", re.I)
MODULE_NAME = re.compile(r"[A-Za-z0-9_+-]+\Z")


def run(args, timeout=30):
    try:
        result = subprocess.run(args, capture_output=True, text=True, errors="replace",
                                encoding="utf-8", timeout=timeout, check=False)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, "", str(exc)


def read(path):
    try:
        return Path(path).read_text(errors="replace").strip()
    except OSError:
        return ""


def powershell(script, *args, timeout=60):
    path = Path(__file__).with_name(script)
    # Invoke a script block without changing the user's execution policy. Quote
    # values as PS literals, never interpolate a device ID as executable syntax.
    arguments = []
    for index in range(0, len(args), 2):
        if args[index] not in ("-InstanceId", "-Mode", "-DriverInf"):
            raise RuntimeError("Parámetro PowerShell no admitido")
        arguments.extend([args[index], "'" + args[index + 1].replace("'", "''") + "'"])
    source = "& {\n" + path.read_text(encoding="utf-8") + "\n} " + " ".join(arguments)
    encoded = base64.b64encode(source.encode("utf-16le")).decode("ascii")
    code, output, error = run([
        "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
        "-EncodedCommand", encoded], timeout)
    if code:
        raise RuntimeError(error or output or "PowerShell no pudo completar la consulta")
    try:
        result = json.loads(output.lstrip("\ufeff"))
    except ValueError as exc:
        raise RuntimeError("PowerShell no devolvió un informe JSON válido") from exc
    if isinstance(result, dict) and "error" in result:
        raise RuntimeError(result["error"])
    return result


def windows_devices(rows):
    devices = []
    for row in rows:
        match = re.search(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", row["instance_id"], re.I)
        if not match:
            continue
        usb_id = ":".join(match.groups()).lower()
        name = row.get("name") or "USB sin nombre"
        if (row.get("service") or "").upper() == "BTHUSB" or row.get("pnp_class") == "Bluetooth":
            continue
        confirmed = bool(row.get("wireless") or usb_id in KNOWN)
        candidate = bool(WIRELESS_NAME.search(name))
        if not confirmed and not candidate:
            continue
        error = row.get("error_code")
        service = row.get("service")
        # Code 28 means missing drivers. Other codes must not trigger replacement.
        if error == 28:
            state = "missing"
        elif error == 0 and service:
            state = "installed"
        elif service or row.get("driver_inf"):
            state = "driver_error" if error != 0 else "installed"
        else:
            state = "unknown"
        devices.append(dict(usb_id=usb_id, name=name, identity_confirmed=confirmed,
                            driver=service, driver_version=row.get("driver_version"),
                            driver_state=state, error_code=error,
                            monitor="unknown", _instance_id=row["instance_id"]))
    return devices


def linux_devices(root=Path("/sys"), runner=run):
    root = Path(root)
    devices = []
    for usb in sorted((root / "bus/usb/devices").glob("*")):
        vid, pid = read(usb / "idVendor"), read(usb / "idProduct")
        if not re.fullmatch(r"[0-9a-fA-F]{4}", vid) or not re.fullmatch(r"[0-9a-fA-F]{4}", pid):
            continue
        usb_id = f"{vid}:{pid}".lower()
        name = " ".join(filter(None, [read(usb / "manufacturer"), read(usb / "product")]))
        # USB class driver 'usb' is not a WLAN driver: inspect USB interfaces.
        usb_interfaces = list(usb.glob(usb.name + ":*"))
        aliases, modules, bound, wifi_interfaces = set(), set(), set(), []
        tools_unavailable = False
        confirmed = usb_id in KNOWN
        for interface in usb_interfaces:
            if confirmed and (interface / "driver").is_symlink():
                bound.add((interface / "driver").resolve().name)
            alias = read(interface / "modalias")
            if alias:
                aliases.add(alias)
            for net in (interface / "net").glob("*"):
                if (root / "class/net" / net.name / "wireless").exists() or (root / "class/net" / net.name / "phy80211").exists():
                    confirmed = True
                    wifi_interfaces.append(net.name)
                    driver = interface / "driver"
                    if driver.is_symlink():
                        bound.add(driver.resolve().name)
            if alias:
                status, output, _ = runner(["modprobe", "--resolve-alias", alias])
                tools_unavailable = tools_unavailable or status == -1
                if status == 0:
                    for module in output.splitlines():
                        if MODULE_NAME.fullmatch(module):
                            _, filename, _ = runner(["modinfo", "-F", "filename", module])
                            if "/wireless/" in filename or module in ("mt7601u", "rtl8xxxu", "r8188eu", "8188eu"):
                                confirmed = True
                                modules.add(module)
                                if (interface / "driver").is_symlink():
                                    bound.add((interface / "driver").resolve().name)
        if not confirmed and not WIRELESS_NAME.search(name):
            continue
        known_name, known_module = KNOWN.get(usb_id, (None, None))
        if not modules and known_module:
            status, _, _ = runner(["modinfo", known_module])
            tools_unavailable = tools_unavailable or status == -1
            if status == 0:
                if known_module == "rtl8xxxu":
                    code, patterns, _ = runner(["modinfo", "-F", "alias", known_module])
                    if code == 0 and any(fnmatch.fnmatchcase(alias.upper(), pattern.upper()) for alias in aliases for pattern in patterns.splitlines()):
                        modules.add(known_module)
                else:
                    modules.add(known_module)
        state = "installed" if bound and wifi_interfaces else "driver_error" if bound else "available" if modules else "missing" if confirmed else "unknown"
        if not bound and not modules and tools_unavailable:
            state = "unknown"
        monitor = "unknown"
        phy = None
        if wifi_interfaces:
            phy_link = root / "class/net" / wifi_interfaces[0] / "phy80211"
            if phy_link.exists():
                phy = phy_link.resolve().name
                status, output, _ = runner(["iw", "phy", phy, "info"])
                if status == 0:
                    # Only read the supported modes section, not interface combinations.
                    section = re.search(r"Supported interface modes:\s*\n((?:\s*\*[^\n]*\n?)+)", output)
                    if section:
                        monitor = "advertised" if re.search(r"\*\s+monitor\b", section[1]) else "not_advertised"
        devices.append(dict(usb_id=usb_id, name=name or known_name or "USB Wi-Fi",
                            identity_confirmed=confirmed, driver=", ".join(sorted(bound)) or None,
                            driver_state=state, local_modules=sorted(modules),
                            expected_module=known_module, interfaces=wifi_interfaces,
                            monitor=monitor, phy=phy, tools_unavailable=tools_unavailable, _aliases=sorted(aliases)))
    return devices


def inventory(system):
    if system == "Windows":
        return windows_devices(powershell("windows_inventory.ps1"))
    if system == "Linux":
        return linux_devices()
    raise RuntimeError("Sistema no compatible. Usa Windows o Linux.")


def repair_linux(device, runner=run, os_release=None, kernel=None, is_root=None):
    if device["driver_state"] not in ("missing", "available") or not device["identity_confirmed"]:
        return "Sin cambios: el controlador existe, hay un error distinto o la identidad no está confirmada."
    if is_root is None:
        is_root = os.geteuid() == 0
    if not is_root:
        return "Se necesitan permisos root. Ejecuta sudo python3 -m switch2_tunnel.doctor --repair."
    modules = device.get("local_modules", [])
    if modules:
        if device["usb_id"] == "0bda:8179" and "rtl8xxxu" in modules:
            firmware_error = ensure_tplink_firmware(runner, os_release)
            if firmware_error:
                return firmware_error
        # A module is already installed: never download another driver in this branch.
        errors = []
        for module in modules:
            if not MODULE_NAME.fullmatch(module):
                continue
            code, _, error = runner(["modprobe", module])
            if code == 0:
                return f"Módulo local {module} cargado; se volverá a comprobar el dispositivo."
            errors.append(error)
        return "El módulo ya existe, pero no se pudo cargar. No se descargó otro. " + "; ".join(errors)
    release = platform.freedesktop_os_release() if os_release is None else os_release
    kernel = platform.release() if kernel is None else kernel
    # Audited download recipes: MT7601U and the in-kernel RTL8188EU backend.
    # Other distributions/chips get precise manual guidance, never a guessed DKMS build.
    module = device.get("expected_module")
    if release.get("ID") != "ubuntu" or not re.fullmatch(r"[0-9][A-Za-z0-9.+-]*-generic", kernel) or module not in ("mt7601u", "rtl8xxxu"):
        return "No hay receta automática verificada para este chipset/distribución/kernel. " + manual_message(device, "Linux")
    if module == "rtl8xxxu":
        version = tuple(int(n) for n in kernel.split("-", 1)[0].split(".")[:2])
        if version < (6, 8):
            return "Para RTL8188EU este perfil necesita Ubuntu con kernel 6.8 o posterior, o un módulo local que coincida con el alias USB. No se instalará el beta antiguo ni un kernel nuevo automáticamente."
    # Check again immediately before any package download; inventory can be stale.
    status, _, error = runner(["modinfo", module])
    if status == 0:
        if module == "rtl8xxxu" and not matching_alias(device, module, runner):
            return "rtl8xxxu existe, pero sus alias no acreditan soporte para este USB. No se descargó ni sustituyó otro driver. Usa el soporte de tu distribución."
        if device["usb_id"] == "0bda:8179" and module == "rtl8xxxu":
            firmware_error = ensure_tplink_firmware(runner, release)
            if firmware_error:
                return firmware_error
        code, _, error = runner(["modprobe", module])
        return "El módulo ya existe; se intentó cargar sin descargar otro. " + (error if code else "Se volverá a comprobar el USB.")
    if status == -1:
        return "No se pudo comprobar el controlador local. Instala las herramientas kmod (modinfo/modprobe) de tu distribución y repite el diagnóstico. No se descargó ningún driver."
    package = "linux-modules-extra-" + kernel
    code, _, error = runner(["apt-get", "install", "--yes", "--no-install-recommends", package], timeout=600)
    if code:
        return f"No se pudo instalar {package} desde APT: {error}. Instálalo desde los repositorios de Ubuntu y comprueba el firmware mt7601u."
    if module == "rtl8xxxu" and not matching_alias(device, module, runner):
        return "El paquete se instaló, pero el módulo no anuncia un alias compatible con este USB. No se cargará por suposición; consulta tu distribución."
    if device["usb_id"] == "0bda:8179":
        firmware_error = ensure_tplink_firmware(runner, release)
        if firmware_error:
            return firmware_error
    code, _, error = runner(["modprobe", module])
    return f"Paquete instalado; {module} cargado. Se volverá a comprobar el USB." if code == 0 else f"El paquete se instaló, pero {module} no carga: {error}. Revisa firmware y registro del kernel."


def matching_alias(device, module, runner=run):
    code, patterns, _ = runner(["modinfo", "-F", "alias", module])
    return code == 0 and any(fnmatch.fnmatchcase(alias.upper(), pattern.upper()) for alias in device.get("_aliases", []) for pattern in patterns.splitlines())


def ensure_tplink_firmware(runner=run, os_release=None, firmware_roots=None):
    roots = firmware_roots if firmware_roots is not None else (Path("/lib/firmware"), Path("/usr/lib/firmware"))
    def present():
        return any((Path(root) / ("rtlwifi/rtl8188eufw.bin" + extension)).is_file()
                   for root in roots for extension in ("", ".xz", ".zst"))
    if present():
        return None
    release = platform.freedesktop_os_release() if os_release is None else os_release
    package = {"ubuntu": "linux-firmware", "debian": "firmware-realtek"}.get(release.get("ID"))
    if not package:
        return "Falta rtlwifi/rtl8188eufw.bin. Instala el paquete de firmware Realtek de tu distribución. No se sustituyó el controlador existente."
    # Firmware is separate from the existing driver. Download only when its file is absent.
    code, _, error = runner(["apt-get", "install", "--yes", "--no-install-recommends", package], timeout=600)
    if code or not present():
        return (f"Falta el firmware rtlwifi/rtl8188eufw.bin y no se pudo resolver con {package}. "
                f"Instala o repara ese paquete desde tu distribución y vuelve a conectar el USB. {error}")
    return None


def repair(device, system, model=None, revision=None, cache=None):
    if device["driver_state"] not in ("missing", "available") or not device["identity_confirmed"]:
        return "Sin cambios: no se ha confirmado un controlador ausente."
    if system == "Linux":
        return repair_linux(device)
    if model == "TL-WN725N":
        if not revision:
            return "Confirma Ver: en la etiqueta y añade --revision 2.0 o --revision 3.0. No se elegirá un paquete por suposición."
        from .tplink import default_cache, repair_windows
        return repair_windows(device, revision, cache or default_cache())
    result = powershell("windows_repair.ps1", "-InstanceId", device["_instance_id"], timeout=600)
    return result["message"]


def manual_message(device, system):
    name = KNOWN.get(device["usb_id"], (device["name"], None))[0]
    prefix = f"Dispositivo: {name}; USB {device['usb_id']}. "
    if device["usb_id"].startswith("2357:") or re.search(r"tp[ -]?link|TL-WN", device["name"], re.I):
        return prefix + ("Instala el controlador oficial TP-Link para el modelo y Ver: impresos en su etiqueta, "
                         f"tu {system} y arquitectura. Descargas: {TP_LINK} "
                         "El USB ID no confirma la revisión; no selecciones V3 sin comprobarla. "
                         "En Linux prefiere el módulo del kernel; no instales un paquete beta para kernels antiguos en un kernel moderno.")
    if system == "Linux":
        module = device.get("expected_module") or "el módulo que tu distribución asocie a este USB ID"
        return prefix + f"Instala {module} y su firmware desde tu distribución, para el kernel {platform.release()}. Si el modelo no está identificado, consulta su etiqueta y soporte del fabricante."
    return prefix + "Instala el controlador firmado del fabricante para este USB ID, modelo/revisión, versión de Windows y arquitectura; también puedes buscarlo en Windows Update > Actualizaciones opcionales."


def device_messages(device, system):
    state = device["driver_state"]
    messages = {
        "installed": "Controlador instalado. No se descargará ni sustituirá.",
        "available": "Controlador disponible en el sistema, sin enlazar. Se intentará cargar localmente con --repair, sin descargar otro.",
        "driver_error": "Hay un controlador, pero el dispositivo presenta un error o no crea una interfaz Wi-Fi. No se descargará otro automáticamente.",
        "missing": "No se detectó un controlador utilizable para este dispositivo.",
        "unknown": "No se puede confirmar si es Wi-Fi o si tiene controlador. No se instalará nada automáticamente.",
    }
    result = [messages[state]]
    if not device["identity_confirmed"]:
        result.insert(0, "Dispositivo candidato: el nombre sugiere Wi-Fi, pero su función no está confirmada. No se instalará nada automáticamente.")
    if device.get("tools_unavailable"):
        result.append("No se pudieron ejecutar modprobe/modinfo. Instala kmod con el gestor de tu distribución para comprobar los módulos locales.")
    if state in ("missing", "unknown", "driver_error"):
        result.append(manual_message(device, system))
    if system == "Linux" and device["usb_id"] == "0bda:8179" and state != "installed":
        result.append("RTL8188EU: comprueba el firmware rtlwifi/rtl8188eufw.bin (también puede estar comprimido). Si falta, instala linux-firmware en Ubuntu o firmware-realtek en Debian; no se sustituirá el driver para resolver un firmware ausente.")
    result.append({
        "advertised": "Modo monitor anunciado por el driver; falta comprobar recepción real y compatibilidad LDN.",
        "not_advertised": "Este driver no anuncia modo monitor. Instalarlo para Internet no acredita compatibilidad con el proyecto.",
        "unknown": "Modo monitor sin verificar. La detección del USB o del driver no demuestra compatibilidad LDN.",
    }[device["monitor"]])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Detectar USB Wi-Fi y diagnosticar controladores sin cambiar la red")
    parser.add_argument("--repair", action="store_true", help="Intentar instalación sólo de controladores ausentes; requiere administrador/root")
    parser.add_argument("--device", help="Limitar a VID:PID, por ejemplo 148f:7601")
    parser.add_argument("--json", action="store_true", help="Informe JSON sin números de serie ni identificadores de instancia")
    parser.add_argument("--model", choices=["TL-WN725N"], help="Perfil del modelo confirmado en la etiqueta")
    parser.add_argument("--revision", help="Ver: de la etiqueta; para Windows se admiten 2/2.0 y 3/3.0")
    parser.add_argument("--check-radio", action="store_true", help="Linux/root: prueba pasiva en una radio dedicada con interfaces DOWN; crea y elimina un monitor temporal")
    parser.add_argument("--frequency", type=int, default=2462, choices=[2412, 2437, 2462])
    parser.add_argument("--seconds", type=int, default=10, choices=range(1, 61), metavar="1-60")
    args = parser.parse_args(argv)
    if args.device and not re.fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{4}", args.device):
        parser.error("--device debe tener formato VID:PID")
    if args.check_radio and (not args.model or not args.device):
        parser.error("--check-radio necesita --model TL-WN725N y --device VID:PID para elegir la radio dedicada")
    system = platform.system()
    try:
        devices = inventory(system)
        if args.model:
            devices = [d for d in devices if d["usb_id"] in ("0bda:8176", "0bda:8179") or "TL-WN725N" in d["name"].upper()]
        if args.device:
            devices = [d for d in devices if d["usb_id"] == args.device.lower()]
        for device in devices:
            if args.repair:
                try:
                    if args.model:
                        device["repair_result"] = repair(device, system, args.model, args.revision)
                    else:
                        device["repair_result"] = repair(device, system)
                except (RuntimeError, ValueError, OSError) as exc:
                    device["repair_result"] = f"No se pudo completar la instalación automática: {exc}. " + manual_message(device, system)
        if args.repair and devices:
            # Verify the observed state, not the installer's exit status alone.
            fresh = inventory(system)
            for device in devices:
                key = "_instance_id" if system == "Windows" else "_aliases"
                matches = [d for d in fresh if d["usb_id"] == device["usb_id"] and d.get(key) == device.get(key)]
                if len(matches) == 1:
                    device.update(matches[0])
        for device in devices:
            device["messages"] = device_messages(device, system)
            if args.check_radio:
                if len(devices) != 1 or system != "Linux":
                    device["radio_check"] = {"status": "not_run", "reason": "La prueba necesita Linux y un único USB seleccionado. En Windows usa la VM Ubuntu."}
                else:
                    from .radio_check import inspect
                    try:
                        device["radio_check"] = inspect(device, args.frequency, args.seconds)
                    except (ValueError, RuntimeError, OSError) as exc:
                        device["radio_check"] = {"status": "not_run", "reason": str(exc)}
        report = {"system": system, "devices": [{k: v for k, v in d.items() if not k.startswith("_")} for d in devices],
                  "note": "" if devices else "No se detectó un USB Wi-Fi identificable. Conéctalo al entorno que ejecuta el diagnóstico; una VM/WSL necesita recibir el USB. Un USB desconocido sin driver puede requerir identificación manual."}
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"Diagnóstico USB Wi-Fi — {system}")
            if report["note"]:
                print(report["note"])
            for device in report["devices"]:
                print(f"\n{device['name']} [{device['usb_id']}] — {device['driver_state']}")
                print("Controlador:", device.get("driver") or "sin enlazar")
                if "repair_result" in device:
                    print(device["repair_result"])
                for message in device["messages"]:
                    print(message)
                if "radio_check" in device:
                    print("Prueba de radio:", json.dumps(device["radio_check"], ensure_ascii=False))
        ready = devices and all(d["driver_state"] == "installed" and d["identity_confirmed"] for d in devices)
        if args.check_radio:
            ready = ready and all(d["radio_check"]["status"] == "receive_verified" and not d["radio_check"].get("cleanup_errors") for d in devices)
        return 0 if ready else 2
    except (RuntimeError, OSError) as exc:
        if args.json:
            print(json.dumps({"system": system, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"No se pudo completar el diagnóstico: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
