"""Interactive pairing agent. Radio transmission is deliberately unavailable."""
import argparse
import json
import struct
import threading
import time
import urllib.error
import urllib.request

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .common import code_digest, fingerprint, make_code
from .transport import Cipher, Link, probe_payload, probe_reply


class API:
    def __init__(self, base):
        if not (base.startswith("https://") or base.startswith("http://127.0.0.1:") or base.startswith("http://localhost:")):
            raise ValueError("usa HTTPS salvo para pruebas en localhost")
        self.base = base.rstrip("/")

    def call(self, method, path, data=None, token=None):
        body = json.dumps(data).encode() if data is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Session-Token"] = token
        request = urllib.request.Request(self.base + path, body, headers, method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                message = json.load(exc)["error"]
            except Exception:
                message = str(exc)
            raise RuntimeError(message) from exc


def keypair():
    private = X25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    return private, public


def watch(api, sid, token, expected, interval=1):
    while True:
        status = api.call("GET", f"/sessions/{sid}/status", token=token)
        state = status["state"]
        if state in expected or state in ("expired", "unconfirmed", "closed"):
            return status
        time.sleep(interval)


def paired_display(status):
    print(f"Agentes enlazados con {status['peer_name']}")
    print(f"Huella del par: {fingerprint(status['peer_public_key'])}")
    print("Compara esta huella por voz con la otra persona.")
    print("Radio: experimental, no validada. Juego: conexión no comprobada.")


def run_session(api, sid, token, private, status, role, udp_port, interface, frequency):
    cipher = Cipher(private, status["peer_public_key"], sid, role)
    link = Link(api.base, udp_port, sid, token, role, cipher)
    radio = None
    stop = threading.Event()
    if interface:
        if not frequency:
            raise ValueError("--frequency is required with --interface")
        from .radio import Radio
        radio = Radio(interface, frequency)
        print(f"Radio experimental activa: {interface} a {frequency} MHz")
        print("La emisión de tramas no garantiza ACK ni asociación de la consola.")

        def capture():
            while not stop.is_set():
                payload = radio.receive()
                if payload:
                    try:
                        link.send(payload)
                    except (OSError, ValueError):
                        radio.discarded += 1

        thread = threading.Thread(target=capture, daemon=True)
        thread.start()
    print("Relay cifrado activo. Ctrl+C para cerrar.")
    pending = {}
    sequence = 0
    last_probe = last_status = last_report = 0
    try:
        while True:
            t = time.monotonic()
            link.hello()
            if role == "a" and t - last_probe >= 1:
                link.send(probe_payload(sequence))
                pending[sequence] = t
                sequence += 1
                last_probe = t
            payload = link.receive()
            if payload:
                if payload[:1] == b"P" and len(payload) == 13:
                    link.send(probe_reply(payload))
                elif payload[:1] == b"R" and len(payload) == 13:
                    number = struct.unpack_from("!I", payload, 1)[0]
                    if number in pending:
                        print(f"RTT entre agentes: {(time.monotonic() - pending.pop(number)) * 1000:.1f} ms")
                elif payload[:1] == b"F" and radio:
                    try:
                        radio.send(payload)
                    except OSError:
                        radio.discarded += 1
            if t - last_status >= 5:
                state = api.call("GET", f"/sessions/{sid}/status", token=token)["state"]
                if state != "paired":
                    print(f"Sesión terminada: {state}")
                    break
                last_status = t
            if t - last_report >= 10:
                report = f"Datagramas: enviados={link.sent} recibidos={link.received} descartados={link.lost}"
                if radio:
                    report += (f" | radio: capturados={radio.captured} emitidos={radio.transmitted} "
                               f"descartados={radio.discarded}")
                print(report, flush=True)
                last_report = t
                pending = {n: sent for n, sent in pending.items() if t - sent < 10}
    finally:
        stop.set()
        if radio:
            thread.join(timeout=1)
            radio.close()
        link.close()


def host(api, name, udp_port, interface, frequency):
    private, public = keypair()
    code = make_code()
    created = api.call("POST", "/invites", {"digest": code_digest(code), "public_key": public, "name": name})
    sid, token = created["session_id"], created["token"]
    try:
        print(f"Código: {code} (45 segundos; caducidad según servidor)")
        print(f"Tu huella: {fingerprint(public)}")
        print("Esperando a B. Ctrl+C cancela.")
        status = watch(api, sid, token, {"reserved"})
        if status["state"] != "reserved":
            print(f"Enlace no establecido: {status['state']}")
            return
        print(f"Solicitud de {status['peer_name']}; huella: {fingerprint(status['peer_public_key'])}")
        if input("¿Confirmar enlace? [s/N] ").strip().lower() != "s":
            print("Solicitud rechazada.")
            return
        api.call("POST", f"/sessions/{sid}/confirm", {"token": token})
        status = api.call("GET", f"/sessions/{sid}/status", token=token)
        paired_display(status)
        run_session(api, sid, token, private, status, "a", udp_port, interface, frequency)
    finally:
        # Keep the private key only in process memory; this object is never serialized.
        del private
        try:
            api.call("POST", f"/sessions/{sid}/close", {"token": token})
        except Exception:
            pass


def join(api, name, code, udp_port, interface, frequency):
    private, public = keypair()
    result = api.call("POST", "/invites/redeem", {"code": code, "public_key": public, "name": name})
    sid, token = result["session_id"], result["token"]
    try:
        print(f"Esperando confirmación de A. Tu huella: {fingerprint(public)}")
        print(f"Huella de A: {fingerprint(result['peer_public_key'])}")
        status = watch(api, sid, token, {"paired"})
        if status["state"] == "paired":
            paired_display(status)
            run_session(api, sid, token, private, status, "b", udp_port, interface, frequency)
        else:
            print(f"Enlace no establecido: {status['state']}")
    finally:
        del private
        try:
            api.call("POST", f"/sessions/{sid}/close", {"token": token})
        except Exception:
            pass


def main():
    p = argparse.ArgumentParser(description="Agente experimental Switch 2")
    p.add_argument("--server", default="http://127.0.0.1:8765")
    p.add_argument("--name", default="Agente")
    p.add_argument("--udp-port", type=int, default=8766)
    p.add_argument("--interface", help="Linux monitor-mode radio interface (experimental)")
    p.add_argument("--frequency", type=int, help="fixed MHz, e.g. 2462 for channel 11")
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("create", help="Crear código A")
    j = sub.add_parser("join", help="Unirse como B")
    j.add_argument("code")
    args = p.parse_args()
    try:
        api = API(args.server)
        if args.action == "create":
            host(api, args.name, args.udp_port, args.interface, args.frequency)
        else:
            join(api, args.name, args.code, args.udp_port, args.interface, args.frequency)
    except KeyboardInterrupt:
        print("\nCancelado")
    except (RuntimeError, ValueError, urllib.error.URLError) as exc:
        p.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
