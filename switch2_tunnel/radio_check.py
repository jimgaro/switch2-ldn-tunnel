"""Bounded passive radio check using a temporary monitor interface on an idle PHY."""
import os
import re
import socket
import time

from ldn_receive_probe import is_ldn_advertisement, radiotap_metadata
from .doctor import run


def checked(args, runner=run):
    code, output, error = runner(args)
    if code:
        raise RuntimeError(f"{' '.join(args)}: {error or output}")
    return output


def ensure_idle(phy, runner=run):
    output = checked(["iw", "dev"], runner)
    current_phy = None
    interfaces = []
    for line in output.splitlines():
        match = re.match(r"\s*phy#(\d+)", line)
        if match:
            current_phy = "phy" + match[1]
        match = re.match(r"\s*Interface\s+(\S+)", line)
        if match and current_phy == phy:
            interfaces.append(match[1])
    if not interfaces:
        raise RuntimeError("No se pudo confirmar qué interfaces pertenecen al PHY; no se alterará la radio.")
    for interface in interfaces:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", interface):
            raise RuntimeError("Nombre de interfaz inesperado")
        output = checked(["ip", "-o", "link", "show", "dev", interface], runner)
        flags = re.search(r"<([^>]+)>", output)
        if not flags or "UP" in flags[1].split(","):
            raise RuntimeError(f"La interfaz {interface} no está confirmada como DOWN. Usa una radio dedicada y bájala manualmente antes de la prueba; el programa no desconectará tu red.")


def inspect(device, frequency=2462, seconds=10, runner=run, socket_factory=socket.socket, clock=time.monotonic):
    if not hasattr(socket, "AF_PACKET"):
        raise RuntimeError("La prueba de radio necesita Linux con AF_PACKET; en Windows usa la VM Ubuntu con el USB asignado.")
    if os.geteuid() != 0:
        raise RuntimeError("La prueba de radio requiere root en Linux.")
    if device.get("driver_state") != "installed" or device.get("monitor") != "advertised" or not device.get("phy"):
        raise RuntimeError("Necesitas un driver instalado que anuncie monitor y un PHY identificado.")
    if not 1 <= seconds <= 60 or frequency not in (2412, 2437, 2462):
        raise ValueError("Para TL-WN725N usa 2412/2437/2462 MHz y entre 1 y 60 segundos.")
    phy = device["phy"]
    if not re.fullmatch(r"phy\d+", phy):
        raise RuntimeError("Identificador de radio no válido")
    ensure_idle(phy, runner)
    monitor = f"s2mon{os.getpid():x}"[:15]
    created = False
    radio = None
    total = valid = ldn = malformed = frequency_verified = 0
    cleanup_errors = []
    result = {}
    failure = None
    try:
        checked(["iw", "phy", phy, "interface", "add", monitor, "type", "monitor"], runner)
        created = True
        checked(["ip", "link", "set", "dev", monitor, "up"], runner)
        checked(["iw", "dev", monitor, "set", "freq", str(frequency)], runner)
        radio = socket_factory(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
        radio.bind((monitor, 0))
        radio.settimeout(0.2)
        deadline = clock() + seconds
        while clock() < deadline:
            try:
                packet = radio.recv(4096)
            except socket.timeout:
                continue
            total += 1
            try:
                offset, observed_frequency, _ = radiotap_metadata(packet)
            except ValueError:
                malformed += 1
                continue
            valid += 1
            if observed_frequency == frequency:
                frequency_verified += 1
                if is_ldn_advertisement(packet[offset:]):
                    ldn += 1
        result.update(status="receive_verified" if frequency_verified else "inconclusive",
                      frequency=frequency, seconds=seconds, packets=total,
                      radiotap_packets=valid, packets_at_requested_frequency=frequency_verified,
                      malformed_packets=malformed, ldn_advertisements=ldn,
                      ldn_status="advertisements_seen" if ldn else "not_observed",
                      transmit="not_tested", association_ack="not_tested", game="not_tested")
    except (RuntimeError, OSError) as exc:
        failure = exc
    finally:
        if radio is not None:
            try:
                radio.close()
            except OSError as exc:
                cleanup_errors.append(f"No se pudo cerrar el socket: {exc}")
        if created:
            code, output, error = runner(["iw", "dev", monitor, "del"])
            if code:
                cleanup_errors.append(f"No se pudo eliminar {monitor}: {error or output}. Ejecuta sudo iw dev {monitor} del.")
        result["cleanup_errors"] = cleanup_errors
    if failure:
        raise RuntimeError(str(failure) + (". " + " ".join(cleanup_errors) if cleanup_errors else "")) from failure
    return result
