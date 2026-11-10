#!/bin/sh
# Run from a checkout, without installing Python packages or changing the network.
set -eu
if ! command -v python3 >/dev/null 2>&1; then
    echo 'Instala Python 3.10 o posterior con el gestor de paquetes de tu distribución.' >&2
    exit 1
fi
cd -- "$(dirname -- "$0")/.."
exec python3 -m switch2_tunnel.doctor "$@"
