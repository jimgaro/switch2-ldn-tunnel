"""Pinned official TL-WN725N packages and a reproducible local support kit."""
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


MODEL = "TL-WN725N"
PACKAGES = {
    "2": {
        "filename": "TL-WN725N_V2_Windows10-11.zip",
        "url": "https://static.tp-link.com/TL-WN725N%28UN%29_V2_160822_1475895480690j.zip",
        "source": "https://www.tp-link.com/us/support/download/tl-wn725n/v2/",
        "sha256": "55421469b9f16e1afa7de0bb6857c0308a281a73c078b1460b28f7070cf2769f",
        "size": 66969001,
        "automatic_inf": False,
    },
    "3": {
        "filename": "TL-WN725N_V3_Windows10-11.zip",
        "url": "https://static.tp-link.com/upload/software/2021/202108/20210810/TL-WN725N_US_V3_200821_Win10.zip",
        "source": "https://www.tp-link.com/us/support/download/tl-wn725n/v3/",
        "sha256": "dd4f8467d2661eafd6dfd4a5fd86fb35b150b4bbf6076cb8a6dcf6987eafeb86",
        "size": 15187164,
        "automatic_inf": True,
    },
}
DRIVER_PREFIX = "TL-WN725N_US_V3_200821_Win10/plugins/Driver Files/Driver/"
LINUX_SOURCE = "https://github.com/torvalds/linux/blob/v6.8/drivers/net/wireless/realtek/rtl8xxxu/rtl8xxxu_core.c"


def source_root():
    for candidate in (Path(__file__).resolve().parent.parent, Path.cwd()):
        if (candidate / "pyproject.toml").is_file() and (candidate / "switch2_tunnel/tplink.py").is_file():
            return candidate
    return None


def default_cache():
    root = source_root()
    if root:
        return root / "drivers/cache"
    if platform.system() == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Switch2Tunnel/drivers"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "switch2-tunnel/drivers"


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def package_for(revision):
    # Deliberately do not collapse 3.46/3.60/4.60 into V3.
    normalized = re.sub(r"^[vV]", "", revision or "")
    normalized = {"2.0": "2", "3.0": "3"}.get(normalized, normalized)
    if normalized not in PACKAGES:
        raise ValueError("Confirma Ver: en la etiqueta: este kit tiene paquetes Windows para V2/V2.0 y V3/V3.0. Para otras revisiones usa su página oficial específica; no se aplicará V3 por suposición.")
    return normalized, PACKAGES[normalized]


def verify(path, package):
    path = Path(path)
    if path.stat().st_size != package["size"] or digest(path) != package["sha256"]:
        raise ValueError(f"El paquete {path.name} no coincide con el SHA-256 y tamaño fijados. No se ejecutará ni extraerá. Descárgalo de nuevo desde {package['source']}.")
    if not zipfile.is_zipfile(path):
        raise ValueError("La descarga no es un ZIP válido")
    return path


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


def validate_url(url):
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "static.tp-link.com" or parsed.port not in (None, 443) or parsed.username:
        raise ValueError("Sólo se permiten descargas HTTPS desde static.tp-link.com")


def acquire(revision, cache, download=False):
    _, package = package_for(revision)
    cache = Path(cache)
    target = cache / package["filename"]
    if target.is_file():
        return verify(target, package)
    if not download:
        raise ValueError(f"No está el paquete local {target.name}. Ejecuta el comando bundle con --download para obtener el original oficial.")
    validate_url(package["url"])
    cache.mkdir(parents=True, exist_ok=True)
    # An exclusive temporary file also prevents competing downloads overwriting each other.
    temporary = target.with_suffix(".zip.part")
    try:
        with temporary.open("xb") as output:
            opener = urllib.request.build_opener(OfficialRedirects())
            with opener.open(package["url"], timeout=30) as response:
                validate_url(response.geturl())
                total = 0
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > package["size"]:
                        raise ValueError("La descarga supera el tamaño esperado")
                    output.write(block)
        verify(temporary, package)
        temporary.replace(target)
    except Exception:
        # Only clean up the temporary file created by this attempt.
        # An existing .part file must not be removed by a competing invocation.
        if 'output' in locals():
            temporary.unlink(missing_ok=True)
        raise
    return target


def windows_architecture():
    arch = os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE") or platform.machine()
    if arch.upper() in ("AMD64", "X86_64"):
        return "64bit"
    if arch.upper() in ("X86", "I386", "I686"):
        return "32bit"
    raise ValueError(f"No hay paquete Windows nativo verificado para arquitectura {arch}; no se instalará el de x64 en ARM64.")


def extract_v3_driver(archive, cache, architecture):
    verify(archive, PACKAGES["3"])
    if architecture not in ("32bit", "64bit"):
        raise ValueError("Arquitectura no admitida")
    destination = Path(cache) / f"TL-WN725N_V3_{architecture}"
    prefix = DRIVER_PREFIX + f"Windows_10_{architecture}/"
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            if entry.is_dir() or not entry.filename.startswith(prefix):
                continue
            relative = PurePosixPath(entry.filename[len(prefix):])
            if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative) or ":" in str(relative):
                raise ValueError("Ruta no válida en el paquete")
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Refresh from the hash-checked archive, including CAT/SYS dependencies.
            with source.open(entry) as input_file, target.open("wb") as output_file:
                shutil.copyfileobj(input_file, output_file)
    inf = destination / "netrtwlanu.inf"
    if not inf.is_file():
        raise ValueError("El paquete no contiene el INF esperado")
    return inf.resolve()


def repair_windows(device, revision, cache):
    from . import doctor
    rev, package = package_for(revision)
    if device["usb_id"] != "0bda:8179":
        return "El USB ID no coincide con el RTL8188EU admitido por el perfil TL-WN725N V2/V3. No se descargó ni instaló nada. Comprueba modelo y revisión."
    # Reuse the system's local driver store check before touching any package.
    local = doctor.powershell("windows_repair.ps1", "-InstanceId", device["_instance_id"], "-Mode", "LocalOnly", timeout=120)
    if local.get("state") != "missing":
        return local["message"]
    architecture = windows_architecture()
    archive = acquire(rev, cache, download=True)
    if not package["automatic_inf"]:
        return (f"No existe un INF directamente utilizable en el ZIP oficial V2. El paquete verificado está en {archive.resolve()}. "
                "Extráelo y ejecuta Setup.exe manualmente para TL-WN725N V2; vuelve a ejecutar el diagnóstico. No se ejecutó ese instalador automáticamente.")
    inf = extract_v3_driver(archive, cache, architecture)
    result = doctor.powershell("windows_repair.ps1", "-InstanceId", device["_instance_id"], "-DriverInf", str(inf), timeout=180)
    return result["message"]


def build_bundle(root, output, download=False):
    root, output = Path(root).resolve(), Path(output).resolve()
    archives = [acquire(rev, root / "drivers/cache", download) for rev in PACKAGES]
    # Explicit allowlist: never package personal lab notes, VM keys or screenshots.
    files = [root / name for name in ("README.md", "LEEME.txt", "GUIA_EJECUCION.md", "AGENTS.md", "USB_WIFI.md", "TPLINK.md", "pyproject.toml", "requirements.txt", "ldn_receive_probe.py")]
    files += sorted((root / "switch2_tunnel").glob("*.py"))
    files += sorted((root / "switch2_tunnel").glob("*.ps1"))
    files += sorted((root / "scripts").glob("diagnose.*"))
    files += sorted((root / "scripts").glob("tplink-*"))
    files += sorted((root / "tests").glob("test_*.py"))
    files += archives
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"model": MODEL, "retrieved": "2026-11-10", "windows_packages": PACKAGES,
                "linux": {"strategy": "kernel/distribution modules; no universal .ko binary", "source": LINUX_SOURCE},
                "radio_validation": "pending_physical_adapter", "ldn_tunnel_validation": "not_validated"}
    checksums = "".join(f"{digest(path)}  {path.relative_to(root).as_posix()}\n" for path in files)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            bundle.write(path, path.relative_to(root).as_posix())
        bundle.writestr("driver-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        bundle.writestr("SHA256SUMS.txt", checksums)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description="Preparar el kit TL-WN725N sin instalar ni ejecutar drivers")
    parser.add_argument("action", choices=["bundle", "verify"])
    parser.add_argument("--download", action="store_true", help="Descargar originales oficiales que no estén en la caché")
    parser.add_argument("--output", default="dist/TL-WN725N-project-kit.zip")
    args = parser.parse_args(argv)
    root = source_root()
    try:
        if args.action == "bundle":
            if root is None:
                raise ValueError("Para generar un kit completo, ejecuta este comando desde una copia del repositorio que incluya TPLINK.md.")
            output = build_bundle(root, args.output, args.download)
            print(f"Kit preparado: {output}\nSHA-256: {digest(output)}")
        else:
            for revision in PACKAGES:
                archive = acquire(revision, default_cache(), download=False)
                print(f"V{revision}: SHA-256 y tamaño correctos — {archive.name}")
        return 0
    except (ValueError, OSError) as exc:
        print(f"No se pudo preparar el kit: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
