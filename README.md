# Switch 2: ensayo de túnel LDN entre dos consolas reales

El proyecto incluye diagnóstico USB Wi-Fi, preparación del TL-WN725N, emparejamiento por código y transporte cifrado entre dos agentes. La captura y retransmisión de radio se ensayan en Linux.

**Estado: experimental.** El túnel jugable entre consolas no está validado. Driver instalado, monitor o recepción de anuncios LDN no demuestran ACK, asociación ni juego. No se necesitan `prod.keys`.

## Instrucciones para empezar

| Documento | Uso |
| --- | --- |
| [LEEME.txt](LEEME.txt) | Inicio rápido en texto plano |
| [GUIA_EJECUCION.md](GUIA_EJECUCION.md) | Preparación, permisos, comandos por etapa y recuperación de la radio |
| [TPLINK.md](TPLINK.md) | TL-WN725N: revisiones y controladores Windows 10/11 y Linux |
| [USB_WIFI.md](USB_WIFI.md) | Diagnóstico general y significado de los resultados |
| [AGENTS.md](AGENTS.md) | Instrucciones para una IA que retome el proyecto |

**Empieza por la [guía de ejecución](GUIA_EJECUCION.md).** Ejecuta los comandos desde la raíz extraída del proyecto, donde está `pyproject.toml`. Sustituye `SERVIDOR`, `CODIGO-DE-A` e `INTERFAZ` por los valores reales.

| Operación | Precondiciones | Permisos |
| --- | --- | --- |
| Consultar USB | Python 3.10+; Windows 10/11 o Linux; USB asignado al sistema que consulta | Usuario normal con acceso CIM/WMI o sysfs |
| Reparar driver | Identidad confirmada; revisión física para paquetes TP-Link; Internet si falta el paquete local | Administrador en Windows o root en Linux |
| Probar transporte | Proyecto instalado; coordinador y dos agentes, incluso en un solo PC | Usuario normal |
| Probar radio | Linux; USB dedicado; monitor anunciado; Internet por otra interfaz | Root; para el test pasivo, interfaces de ese PHY DOWN |
| Validar juego | Dos consolas/juegos compatibles, dos extremos Linux y dos radios | Root sólo en los agentes que usan radio |

El backend de radio actual requiere Linux. En Windows puede usarse una VM Ubuntu con el USB asignado al invitado; ése fue el entorno de la prueba anterior, mediante VirtualBox. Instalar el driver Windows no habilita un backend de radio Windows. WSL necesita que su kernel incluya el controlador.

Instalación completa en Windows, sin activar `.venv` ni cambiar la política de PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
```

La instalación Python no instala controladores. La guía enlazada contiene también la preparación de Ubuntu, los tres terminales de prueba local, servidor HTTPS, ensayo de radio y restauración del Wi-Fi.

## Verificación y entrega

Después de instalar, ejecuta las pruebas como usuario normal:

Windows:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Linux:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Las pruebas de transporte necesitan UDP por loopback y no usan la radio física. La validación registrada el 10 de noviembre de 2026 pasó 47 pruebas; no sustituye una prueba con hardware.

Para verificar los originales locales y regenerar el kit, desde el repositorio:

```sh
python -m switch2_tunnel.tplink verify
python -m switch2_tunnel.tplink bundle
```

En Linux usa `python3`. Si faltan originales, `bundle --download` solicita descargarlos. El resultado es `dist/TL-WN725N-project-kit.zip`: código, instrucciones para humanos/IA, paquetes Windows V2/V3 y sumas de integridad. No incluye la VM ni notas privadas. Linux obtiene módulos y firmware de la distribución correspondiente.
