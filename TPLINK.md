# Kit TP-Link TL-WN725N para el proyecto

Este kit incluye el diagnóstico, los paquetes Windows originales V2/V3, selección por revisión, instalación conservadora y prueba pasiva de radio Linux. No certifica un túnel LDN jugable. La revisión del adaptador físico del usuario sigue pendiente: comprueba `Ver:` en su etiqueta antes de instalar.

## Windows 10 y 11

Extrae el kit en una carpeta. Instala Python 3.10 o posterior si falta. Desde esa carpeta:

```powershell
python -m switch2_tunnel.doctor --model TL-WN725N
```

Si es **V3/V3.0**, en PowerShell como administrador:

```powershell
python -m switch2_tunnel.doctor --model TL-WN725N --revision 3.0 --repair
```

Si es **V2/V2.0**, usa `--revision 2.0`. No se convierte automáticamente una revisión 3.46, 3.60 o 4.60 en V3; esas revisiones necesitan comprobar su página específica. V1 no tiene aquí un paquete oficial verificado para Windows 10/11.

El perfil V2/V3 comprueba el USB ID `0bda:8179`, que corresponde al chipset compartido; ese ID **no prueba por sí solo** que el modelo comercial sea TL-WN725N ni su revisión. `--model` y `--revision` deben coincidir con lo que dice la etiqueta.

Comportamiento:

1. Si ya tiene driver, no descarga ni sustituye otro.
2. Con driver ausente, solicita a Windows revisar y utilizar sus controladores locales.
3. Sólo si no hay candidatos locales, utiliza el paquete oficial de la revisión confirmada. Prefiere la copia del kit y verifica tamaño y SHA-256; si falta, descarga desde `static.tp-link.com` por HTTPS.
4. V3 contiene INF/CAT/SYS de 32 y 64 bits. Selecciona la arquitectura del **sistema**, incluso con Python de 32 bits en Windows x64, y vuelve a comprobar el Hardware ID antes de llamar a PnPUtil. Windows valida la firma del paquete; no se desactiva esa comprobación. ARM64 no está admitido por estos archivos x86/x64.
5. V2 contiene un instalador sin INF directamente accesible. Si se necesita, el mensaje indica el ZIP verificado: extráelo y ejecuta su `Setup.exe` manualmente. El programa no adivina parámetros silenciosos ni ejecuta el instalador.
6. Tras la instalación vuelve a consultar el USB. Si Windows pide reiniciar, lo indica y deja el reinicio al usuario.

El driver Windows sirve para la conectividad del adaptador. El backend de radio del proyecto usa `AF_PACKET` y requiere Linux. **No actives el túnel de radio directamente desde Windows por haber instalado el driver.** Usa Ubuntu con el USB asignado a la VM o Linux instalado directamente. Si el USB está capturado por una VM, puede no estar disponible para el diagnóstico del host.

## Linux: controlador del kernel

En Ubuntu, conecta/asigna el USB al Linux donde corre el proyecto y ejecuta:

```sh
python3 -m switch2_tunnel.doctor --model TL-WN725N
sudo python3 -m switch2_tunnel.doctor --model TL-WN725N --repair
```

Para el RTL8188EU se comprueban primero los módulos locales y sus alias reales. En Ubuntu con kernel `*-generic` 6.8 o posterior, si falta el módulo, la receta instala `linux-modules-extra-$(uname -r)` mediante APT, comprueba el alias del USB y carga `rtl8xxxu`. Los módulos/firmware ya instalados se aprovechan; no se compila un kernel ni se sustituye automáticamente un controlador existente por un DKMS de terceros.

Si falta firmware, el diagnóstico nombra **`rtlwifi/rtl8188eufw.bin`** (puede estar comprimido). Con `--repair`, si el archivo falta, intenta instalar sólo el paquete de firmware: `linux-firmware` en Ubuntu o `firmware-realtek` en Debian. No lo descarga si el archivo ya existe, incluso comprimido. Esto no sustituye el driver existente. Si APT falla o el paquete no aporta el archivo, indica qué instalar o reparar manualmente. En distribuciones y kernels no cubiertos por la receta se muestran instrucciones, sin instalar paquetes de Ubuntu en otro sistema.

No se incluye un `.ko` genérico: debe coincidir con el kernel del usuario. Tampoco se instala el beta Linux V3 de 2018, cuyo rango publicado termina en kernel 4.4.3.

## Comprobar recepción con el código del proyecto

Usa una radio **dedicada**, con Internet por otra interfaz. Si el diagnóstico muestra, por ejemplo, `wlan1`, bájala manualmente y evita que NetworkManager vuelva a conectarla. La prueba se niega a operar si alguna interfaz de ese mismo PHY está UP; no bajará por su cuenta la conexión del usuario.

```sh
sudo ip link set dev wlan1 down
sudo python3 -m switch2_tunnel.doctor --model TL-WN725N --device 0bda:8179 --check-radio --frequency 2462 --seconds 30
```

Sustituye `wlan1` por tu interfaz real. No bajes la interfaz de Internet. Para la Switch dentro de Sala Unión, usa la frecuencia medida: 2412, 2437 o 2462 MHz (canales 1, 6 u 11). Esta prueba selecciona un único USB; si hay varios con el mismo ID, se detiene para evitar elegir uno arbitrariamente.

El programa crea un monitor temporal, fija la frecuencia, escucha con `AF_PACKET`, comprueba radiotap y cuenta anuncios con el mismo clasificador LDN del proyecto. No transmite, no guarda tramas y elimina el monitor al terminar. El canal del PHY puede quedar en el último probado; las interfaces originales deben permanecer DOWN durante toda la prueba. Para reconectar la radio normalmente, restablece la gestión habitual de tu distribución.

Interpretación:

| Resultado | Qué demuestra |
| --- | --- |
| `installed` | El USB tiene un controlador enlazado y una interfaz Wi-Fi |
| `monitor: advertised` | El controlador anuncia monitor |
| `receive_verified` | Llegaron tramas radiotap en la frecuencia solicitada |
| `ldn_status: advertisements_seen` | Se recibieron anuncios reconocidos por el clasificador LDN |
| `inconclusive` | No hubo recepción suficiente; no demuestra por sí solo incompatibilidad |

La emisión, ACK, asociación y conexión del juego quedan explícitamente como `not_tested`. Cuando se confirme recepción, se puede continuar con el [ensayo de dos consolas de la guía](GUIA_EJECUCION.md#7-ensayo-experimental-con-dos-consolas), que requiere preparar una interfaz monitor persistente y un segundo extremo real. El monitor de diagnóstico es temporal y no debe pasarse después al agente.

## Paquetes y verificación

Los originales de Windows están en `drivers/cache/`, separados por revisión, y no se han modificado. El código fuente de la herramienta no requiere incorporar esos binarios a GitHub: la caché y `dist/` están excluidos de Git. Los originales conservan las condiciones y materiales de sus proveedores; la licencia del código del proyecto no se extiende a esos paquetes.

```sh
python -m switch2_tunnel.tplink verify
python -m switch2_tunnel.tplink bundle
```

Para regenerar un kit cuando falten los originales:

```sh
python -m switch2_tunnel.tplink bundle --download
```

Este último comando es una petición explícita de preparar un kit para otros equipos: descarga los originales aunque el equipo que lo construye no necesite instalarlos. El diagnóstico y `--repair` mantienen la regla de no descargar drivers que ya existen en el sistema.

El kit trae `driver-manifest.json` con origen, revisión, tamaño y SHA-256, y `SHA256SUMS.txt` para sus archivos. Los hashes de los originales se calcularon al obtenerlos por HTTPS el 10 de noviembre de 2026; son una referencia local de integridad, no una suma publicada por TP-Link ni un sustituto de la firma que valida Windows.

Fuentes:

- [TP-Link V3, Windows 10/11 y beta Linux](https://www.tp-link.com/us/support/download/tl-wn725n/v3/)
- [TP-Link V2 y sus sistemas publicados](https://www.tp-link.com/us/support/download/tl-wn725n/v2/)
- [TP-Link V1 y su rango publicado](https://www.tp-link.com/us/support/download/tl-wn725n/v1/)
- [Kernel Linux 6.8: IDs RTL8188EU en rtl8xxxu](https://github.com/torvalds/linux/blob/v6.8/drivers/net/wireless/realtek/rtl8xxxu/rtl8xxxu_core.c)
- [Ubuntu: linux-firmware](https://packages.ubuntu.com/noble/linux-firmware)

**Estado de aceptación:** paquetes obtenidos y verificados; código integrable y comprobable por pruebas automatizadas. Falta conectar el TL-WN725N físico, confirmar revisión y realizar las pruebas de driver y radio. No hay evidencia todavía de túnel jugable con este adaptador.

Validación del 10 de noviembre de 2026: **47 pruebas automatizadas pasaron**, incluidas las de transporte UDP y emparejamiento, usando las dependencias instaladas en el entorno virtual del proyecto. Se comprobó la extracción real de ambos drivers V3 y los catálogos CAT de 32/64 bits devolvieron firma válida de **Microsoft Windows Hardware Compatibility Publisher**. La consulta real de Windows no detectó un TL-WN725N conectado. No se ejecutaron instaladores de TP-Link ni se modificaron controladores del host durante la preparación.
