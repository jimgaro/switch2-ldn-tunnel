# Preparar y ejecutar el proyecto

Sigue las etapas en orden. Para diagnosticar un USB basta un PC; para validar el túnel con juegos hacen falta **dos consolas reales, dos extremos Linux y dos radios**. El túnel jugable todavía no está validado.

## 1. Preparar el equipo

Extrae el repositorio o el ZIP completo en una carpeta con permiso de escritura. Abre una terminal en ella: deben verse `pyproject.toml`, `switch2_tunnel/` y este documento. No ejecutes desde dentro del ZIP. Sustituye los valores en MAYÚSCULAS por los de tu equipo.

**Windows 10/11:** instala Python 3.10 o posterior y comprueba `python --version`. Usa PowerShell normal para consultar e instalar el proyecto; abre otra ventana como administrador sólo para `--repair`. Los comandos recomendados usan `python -m` y no requieren cambiar la política de ejecución de PowerShell.

**Linux:** el entorno de referencia es Ubuntu con kernel `*-generic` 6.8 o posterior para RTL8188EU. Prepara las herramientas del sistema:

```sh
sudo apt update
sudo apt install python3 python3-venv python3-pip iw iproute2 kmod usbutils
python3 --version
uname -r
```

Esos comandos APT son para Ubuntu/Debian. En otras distribuciones usa paquetes equivalentes; las recetas automáticas de drivers tienen un alcance menor que el diagnóstico.

**Windows + VM:** arranca Ubuntu, conecta el USB al invitado desde el menú de dispositivos USB del hipervisor y comprueba `lsusb` dentro de Ubuntu. Trabaja con una copia del proyecto accesible en el invitado. Windows y la VM no pueden controlar el mismo USB a la vez. Usa NAT/Ethernet virtual para Internet y reserva el USB para radio. La prueba anterior usó Ubuntu en VirtualBox; WSL se descartó porque su kernel no tenía `mt7601u`.

## 2. Instalar la aplicación

Desde la raíz del proyecto, **sin administrador/root**:

Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
```

Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
```

Necesitas Internet para dependencias ausentes localmente. No uses `sudo pip`. La instalación Python no instala controladores. Estos comandos usan el intérprete de `.venv`, sin necesidad de activarlo. Crea un entorno independiente en cada sistema; no copies la `.venv` de Windows a Linux.

## 3. Detectar y preparar el USB

Conecta el USB al sistema que ejecutará la operación. Consulta primero todos los adaptadores:

Windows:

```powershell
.\.venv\Scripts\python.exe -m switch2_tunnel.doctor
```

Linux:

```sh
.venv/bin/python -m switch2_tunnel.doctor
```

El diagnóstico normal es de lectura y puede ejecutarse incluso antes de instalar el proyecto, con `python` o `python3`. Para un **TL-WN725N confirmado en su etiqueta**, añade `--model TL-WN725N`. Apunta USB ID, interfaz, estado del driver y, en Linux, PHY y monitor. Un ID compartido por distintos modelos no confirma la revisión comercial.

Si falta el driver, solicita reparación. Ejemplo Windows para una etiqueta **Ver: 3.0**, desde PowerShell como administrador y en la misma carpeta:

```powershell
.\.venv\Scripts\python.exe -m switch2_tunnel.doctor --model TL-WN725N --revision 3.0 --repair
```

Para V2/V2.0 usa `--revision 2.0`: si necesita el paquete oficial, indicará la instalación manual con su `Setup.exe`. No uses V3 para V1, V3.46, V3.60 o V4.60. Si no conoces `Ver:`, compruébalo antes de elegir un paquete.

Linux, dentro del sistema que tiene asignado el USB:

```sh
sudo .venv/bin/python -m switch2_tunnel.doctor --model TL-WN725N --repair
```

Se prefieren drivers locales y no se sustituyen los ya instalados. Sólo se descargan paquetes ausentes admitidos por la receta; el firmware se comprueba por separado. Si faltan permisos, soporte o paquetes, sigue la instrucción manual que imprime el programa. Detalles de revisiones y fuentes: [TPLINK.md](TPLINK.md).

**Resultado esperado:** `installed`. Eso acredita el controlador, no el túnel. Salidas del diagnóstico: `0` = drivers presentes en dispositivos confirmados; `2` = ningún USB identificado o algo pendiente; `1` = fallo de consulta. Con `--check-radio`, `0` exige además recepción verificada y limpieza correcta. Para guardar un informe añade `--json > diagnostico.json`; revisa nombres de interfaz que puedan contener una MAC antes de compartirlo.

## 4. Probar el transporte sin radio

Abre **tres terminales en la misma carpeta**. Esta prueba funciona en Windows o Linux, sin USB, consolas, root ni certificado. El servicio escucha sólo en localhost.

En Windows:

```powershell
# Terminal 1: coordinador; dejar abierto.
.\.venv\Scripts\python.exe -m switch2_tunnel.coordinator
# Terminal 2: crear enlace; dejar abierto.
.\.venv\Scripts\python.exe -m switch2_tunnel.agent --name Alicia create
# Terminal 3: sustituir CODIGO-DE-A por el que imprime A.
.\.venv\Scripts\python.exe -m switch2_tunnel.agent --name Bruno join CODIGO-DE-A
```

En Linux:

```sh
.venv/bin/python -m switch2_tunnel.coordinator
.venv/bin/python -m switch2_tunnel.agent --name Alicia create
.venv/bin/python -m switch2_tunnel.agent --name Bruno join CODIGO-DE-A
```

Ejecuta **uno en cada terminal**, en ese orden. Introduce el código antes de que caduque (45 segundos por defecto); después A confirma con `s`. Compara las huellas de clave del par por voz. Deben aparecer agentes enlazados y mediciones RTT. `Ctrl+C` cierra un agente; detén también el coordinador al terminar. No pases a radio si esta etapa falla.

## 5. Usar dos equipos por Internet

Necesitas un servidor accesible y un certificado TLS válido que coincida con su nombre. Prepara previamente `cert.pem` y su clave privada `key.pem`; no subas la clave al repositorio. En el firewall/router **del coordinador**, permite entrada TCP 8765 y UDP 8766; si está detrás de NAT, configura el reenvío correspondiente. Los agentes necesitan poder iniciar HTTPS y UDP hacia él. No necesitan abrir esos puertos entrantes en sus routers para usar el relay.

En el servidor Linux, sin root (los puertos predeterminados son mayores de 1024):

```sh
.venv/bin/python -m switch2_tunnel.coordinator --host 0.0.0.0 --port 8765 --udp-port 8766 --db sessions.sqlite3 --cert cert.pem --key key.pem
```

En Linux A y B respectivamente:

```sh
.venv/bin/python -m switch2_tunnel.agent --server https://SERVIDOR:8765 --name Alicia create
.venv/bin/python -m switch2_tunnel.agent --server https://SERVIDOR:8765 --name Bruno join CODIGO-DE-A
```

En Windows cambia sólo el intérprete por `.\.venv\Scripts\python.exe`. Mantén los tres procesos abiertos, confirma en A y verifica RTT. No desactives TLS para resolver errores de certificado.

## 6. Comprobar recepción de radio en Linux

Sólo sobre un USB **dedicado** y con Internet por otra interfaz. Identifica la interfaz mediante el diagnóstico e `iw dev`. Debe anunciar monitor. Sustituye `INTERFAZ` por ese USB, nunca por tu conexión de Internet.

Anota el modo inicial con `iw dev INTERFAZ info`. Si NetworkManager gestiona esa radio, anota también su estado con `nmcli device show INTERFAZ`. Para impedir que la reconecte durante la prueba puedes ejecutar `sudo nmcli device set INTERFAZ managed no`. Este paso es sólo para equipos con NetworkManager; después restaura su estado inicial.

```sh
sudo ip link set dev INTERFAZ down
sudo .venv/bin/python -m switch2_tunnel.doctor --model TL-WN725N --device 0bda:8179 --check-radio --frequency 2462 --seconds 30
```

Debe haber un único USB seleccionado y **todas las interfaces de su mismo PHY** deben estar DOWN. La prueba crea un monitor temporal, escucha sin emitir, lo elimina al terminar y deja las interfaces originales DOWN. Usa la frecuencia medida: 2412/2437/2462 MHz corresponden a canales 1/6/11. Con la consola en la modalidad local del juego, busca `receive_verified` y `ldn_status: advertisements_seen`. No recibir anuncios no demuestra por sí solo incompatibilidad: revisa frecuencia y estado del juego. Interpretación completa: [TPLINK.md](TPLINK.md).

## 7. Ensayo experimental con dos consolas

Requiere una consola/juego compatible y un Linux con radio dedicada en cada extremo. Confirma antes las etapas 4–6. Este paso **transmite tramas**. El monitor temporal de la etapa 6 ya fue eliminado: prepara una interfaz monitor persistente en cada USB dedicado:

```sh
sudo ip link set dev INTERFAZ down
sudo iw dev INTERFAZ set type monitor
sudo ip link set dev INTERFAZ up
sudo iw dev INTERFAZ set channel 11
```

El ejemplo fija canal 11; adapta canal y frecuencia al valor medido, igual en ambos extremos. Con el coordinador HTTPS de la etapa 5 abierto, ejecuta en Linux A y B respectivamente:

```sh
sudo .venv/bin/python -m switch2_tunnel.agent --server https://SERVIDOR:8765 --name Alicia --interface INTERFAZ --frequency 2462 create
sudo .venv/bin/python -m switch2_tunnel.agent --server https://SERVIDOR:8765 --name Bruno --interface INTERFAZ --frequency 2462 join CODIGO-DE-A
```

Introduce el código, confirma en A y compara huellas. Observa contadores y pantallas de las consolas. **Sólo jugadores visibles y una operación real completada validan el juego.** El programa no implementa firmware de ACK ni estado de asociación; no promete que reproducir tramas baste para LDN. Esa limitación no se resuelve sólo instalando paquetes Python o bajando RTT.

## 8. Terminar y recuperar la radio

Detén agentes y coordinador con `Ctrl+C`. Si sólo hiciste la prueba pasiva de la etapa 6, vuelve a subir la interfaz original con `sudo ip link set dev INTERFAZ up`. Si cambiaste tu USB desde managed a monitor en la etapa 7:

```sh
sudo ip link set dev INTERFAZ down
sudo iw dev INTERFAZ set type managed
sudo ip link set dev INTERFAZ up
```

Si desactivaste NetworkManager y originalmente gestionaba la interfaz, restaura `sudo nmcli device set INTERFAZ managed yes`. Reconecta mediante el gestor de red habitual. Restaura sólo los ajustes que cambiaste, sin alterar otros adaptadores. Si el diagnóstico informa que no pudo borrar un monitor temporal `s2mon...`, ejecuta su comando de limpieza exacto.

## Problemas frecuentes

| Síntoma | Comprobación siguiente |
| --- | --- |
| No aparece el USB | Conexión física; `lsusb`; asignación a VM/WSL; host/invitado correcto |
| Falta módulo o firmware | Mensaje de `--repair`; kernel y paquetes reales; [USB_WIFI.md](USB_WIFI.md) |
| Falta acceso CIM/WMI | Ejecutar fuera del entorno restringido y comprobar permisos de Windows |
| Monitor no anunciado | Esa combinación driver/kernel no acredita soporte; no sustituir drivers automáticamente |
| Prueba de radio rechazada | USB/PHY único, interfaces DOWN, root y radio dedicada |
| Error HTTPS | Certificado válido, nombre correcto y TCP 8765 accesible |
| Agentes enlazados sin RTT | UDP 8766, firewall y los tres procesos abiertos |
| RTT correcto pero el juego falla | ACK/asociación/capacidad de radio siguen sin validar |

Para desarrollo ejecuta las pruebas del [README.md](README.md). Para entregar a otra persona, regenera el ZIP con `python -m switch2_tunnel.tplink bundle` (Linux: `python3`); añade `--download` sólo para obtener originales ausentes. El ZIP incluye estas instrucciones y no depende de la VM del autor.
