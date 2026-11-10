# Detección USB Wi-Fi y controladores

El comando `switch2-doctor` detecta adaptadores USB Wi-Fi y distingue controlador instalado, disponible localmente, ausente, con errores e identidad desconocida. Usa sólo la biblioteca estándar: puede ejecutarse desde el repositorio sin instalar `cryptography`.

Windows 10/11, desde PowerShell en esta carpeta:

```powershell
python -m switch2_tunnel.doctor
python -m switch2_tunnel.doctor --json
```

Linux:

```sh
python3 -m switch2_tunnel.doctor
```

También hay lanzadores `scripts/diagnose.ps1` y `sh scripts/diagnose.sh`. Si instalaste el proyecto, usa `switch2-doctor`.

## Reparación de controladores ausentes

La consulta predeterminada no descarga nada, no cambia interfaces ni activa modo monitor. Para solicitar reparación, abre PowerShell como administrador o usa root en Linux:

```powershell
python -m switch2_tunnel.doctor --repair --device 148f:7601
```

```sh
sudo python3 -m switch2_tunnel.doctor --repair --device 148f:7601
```

Sin `--device`, se intentará reparar cada adaptador identificado que tenga el controlador ausente o disponible sin cargar. No se elevan permisos automáticamente ni se reinicia el PC. APT o Windows Update necesitan Internet; ante fallos se muestra la instalación manual requerida. La búsqueda e instalación pueden tardar varios minutos.

### Windows

1. Consulta dispositivos USB presentes, driver firmado, servicio, código de error y tipo de medio de los adaptadores.
2. Sólo un dispositivo confirmado como Wi-Fi y con código PnP 28 puede iniciar reparación. Códigos 10, 22 y 43 no se tratan como ausencia ni provocan sustituciones.
3. Vuelve a detectar el dispositivo y consulta los controladores compatibles del almacén local con PnPUtil. Si existen, intenta usarlos sin descargar otros. Si no se puede consultar el almacén, se detiene y pide instalación manual.
4. Sólo si no hay candidatos locales consulta Windows Update. Selecciona una actualización cuyo Hardware ID coincida exactamente con uno de los IDs del dispositivo; no instala las demás actualizaciones. No acepta licencias por el usuario.
5. Comprueba de nuevo que el driver falte antes de descargar. Tras instalar vuelve a consultar el estado; un instalador exitoso no equivale a un USB funcional. Indica si es necesario reiniciar.

Requiere los comandos de PnPUtil usados por Windows 10 actualizado o Windows 11. Una política empresarial, la falta de elevación o Windows Update sin acceso pueden impedir el proceso. En esos casos el mensaje pide el paquete oficial correspondiente al modelo, revisión, Windows y arquitectura. No descarga ejecutables desde sitios de terceros.

### Linux

Lee sysfs y las interfaces Wi-Fi, resuelve los alias USB con `modprobe --resolve-alias` y consulta módulos con `modinfo`. Usa `iw phy ... info` para informar si el driver anuncia monitor; no lo activa ni prueba recepción/inyección.

Si el módulo ya está disponible, `--repair` sólo intenta cargarlo. Si el driver está enlazado pero no crea una interfaz Wi-Fi, lo trata como error y no descarga otro. Puede faltar firmware, existir un bloqueo de radio o una incompatibilidad: hay que revisar el registro del kernel.

Hay recetas de descarga para MT7601U en Ubuntu con kernel `*-generic` y RTL8188EU/`rtl8xxxu` en Ubuntu con kernel `*-generic` 6.8 o posterior: instalan `linux-modules-extra-$(uname -r)` mediante APT. Para RTL8188EU se comprueba también el alias real del USB antes de cargar el módulo. No compila kernels ni descarga DKMS. Si falta el paquete en los índices locales, APT falla y el diagnóstico indica qué instalar; no modifica las fuentes de paquetes. El perfil RTL8188EU comprueba por separado el firmware y sólo intenta instalar su paquete de Ubuntu/Debian si falta el archivo requerido.

Otros chipsets/distribuciones reciben instrucciones manuales con USB ID y modelo conocido o por confirmar. No existe todavía un catálogo universal. Un dispositivo desconocido sin driver y sin información Wi-Fi suficiente puede no detectarse: no se instala nada por suposición. Los nombres comerciales y USB IDs no confirman siempre la revisión física.

En una VM o WSL, el USB debe asignarse al Linux que ejecuta la consulta. Que WSL vea el USB no significa que su kernel contenga el módulo.

## Informes y códigos de salida

`--json` excluye las rutas de instancia PnP y los alias internos. No consulta SSID, tráfico ni campos MAC o de número de serie. Conserva el nombre del fabricante y los nombres de interfaz; estos últimos pueden contener una MAC (por ejemplo `wlx...`), por lo que debes revisar un informe antes de publicarlo. Devuelve 0 si todos los USB detectados están confirmados como Wi-Fi y tienen driver instalado, 2 si no hay dispositivos o falta resolver alguno y 1 si la consulta falla. El código 0 **no** certifica modo monitor, recepción LDN ni túnel jugable.

## TP-Link TL-WN725N: Windows 10/11 y Linux

Modelo identificado en la conversación anterior: **TL-WN725N**. Revisión de hardware **pendiente de confirmar en la etiqueta `Ver:`**. No se atribuye automáticamente V3 a cualquier USB con el mismo chipset.

El [kit TL-WN725N](TPLINK.md) incluye los originales oficiales de Windows V2 y V3 con verificación de integridad, selección por revisión e instalación INF para V3. Estos paquetes se prepararon por petición explícita; su presencia en el kit no autoriza a aplicarlos a cualquier revisión. Un paquete para conectividad normal no garantiza modo monitor en Windows.

El paquete Linux beta V3 `180510` declara kernels **2.6.18 a 4.4.3**. No es una solución universal para Ubuntu 24.04 u otros kernels actuales. En Linux se prioriza el controlador del kernel/distribución identificado por el alias real del USB. Monitor e inyección requieren pruebas de esa combinación concreta.

Fuentes oficiales consultadas:

- [TP-Link TL-WN725N V3: descargas y sistemas compatibles](https://www.tp-link.com/us/support/download/tl-wn725n/v3/)
- [Microsoft: sintaxis de PnPUtil](https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/pnputil-command-syntax)
- [Microsoft: interfaz IWindowsDriverUpdate](https://learn.microsoft.com/en-us/windows/win32/api/wuapi/nn-wuapi-iwindowsdriverupdate)
- [Linux Wireless: iw](https://wireless.docs.kernel.org/en/latest/en/users/documentation/iw.html)

## Validación

Las pruebas unitarias cubren los casos de driver instalado, ausente, con error, USB desconocido, módulos locales y descarga limitada a Ubuntu/MT7601U; no requieren Internet ni modifican drivers. La consulta Windows se puede comprobar en el host. La reparación real y el backend Linux requieren validación con hardware en cada sistema; un caso simulado no equivale a esa prueba.

La validación más reciente y las instrucciones específicas del TP-Link están en [TPLINK.md](TPLINK.md). El entorno virtual local incluye ahora las dependencias del proyecto para comprobar también emparejamiento y transporte. La consulta real de Windows terminó sin detectar un USB Wi-Fi identificable conectado; no se instalaron controladores.
