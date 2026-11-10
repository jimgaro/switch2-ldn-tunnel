# Instrucciones para agentes de IA

## Alcance y lectura inicial

Aplican a todo el repositorio. Lee `README.md` y `GUIA_EJECUCION.md` antes de operar. Para TP-Link consulta `TPLINK.md`; para drivers, `USB_WIFI.md`. `LEEME.txt` es la entrada humana en texto plano. Usa `pyproject.toml` y el código actual como referencia de comandos; las notas históricas no describen necesariamente la implementación vigente.

## Estado que debes preservar

- Transporte cifrado, emparejamiento y diagnóstico implementados; túnel jugable entre consolas sin validar.
- La recepción histórica usó MT7601U en Ubuntu dentro de VirtualBox sobre Windows, no Linux instalado directamente.
- El TP-Link indicado fue TL-WN725N; su revisión física y las pruebas con esa unidad siguen pendientes hasta obtener evidencia nueva.
- Driver instalado, monitor anunciado, recepción radiotap, anuncios LDN, emisión y juego son resultados distintos. No presentes uno como prueba de otro.
- La radio usa Linux `AF_PACKET`. El driver Windows no habilita un backend de radio Windows. El alcance actual no necesita `prod.keys`.

## Operación y permisos

- Trabaja desde la raíz con Python 3.10+. El diagnóstico usa la biblioteca estándar. Instala dependencias de pruebas/transporte en `.venv`, sin `sudo pip`.
- Empieza por lectura: `python -m switch2_tunnel.doctor` (Linux: `python3`). Distingue un bloqueo CIM/WMI del entorno de la ausencia de USB.
- Los ejemplos de documentación no son por sí solos una petición de reparar drivers o transmitir radio. Haz esas operaciones cuando estén solicitadas y autorizadas en la sesión; no añadas confirmaciones extra si ya lo están.
- `--repair` necesita administrador/root. Prefiere drivers locales y no sustituyas los existentes. Para paquetes TP-Link exige modelo/revisión confirmados y Hardware ID compatible. No infieras V3 por el chipset ni conviertas V3.46/V3.60/V4.60 en V3.
- Descarga drivers sólo de las fuentes oficiales fijadas y verifica hashes/tamaños. El firmware se comprueba por separado. No desactives firmas ni TLS, no aceptes licencias automáticamente ni reinicies sin una petición que lo autorice.
- Radio: USB dedicado e Internet por otra interfaz. No bajes conexiones activas para una consulta. `--check-radio` requiere una única radio seleccionada y todas las interfaces del PHY DOWN; crea un monitor temporal y no transmite. Los agentes con `--interface` sí transmiten.
- Registra y restaura los cambios de modo/gestión de red que hagas. No alteres otras radios o VMs. Una VM necesita recibir el USB.

## Desarrollo y comprobación

- Mantén diagnóstico y kit utilizables sin dependencias Python adicionales. Reutiliza `doctor.py`, `tplink.py`, `radio_check.py` y el clasificador de `ldn_receive_probe.py`.
- Prueba desde la raíz: `.venv/bin/python -m unittest discover -s tests -v` en Linux; `.\.venv\Scripts\python.exe -m unittest discover -s tests -v` en Windows. El transporte necesita UDP por loopback: un bloqueo del sandbox no acredita un fallo del relay. Usa el mecanismo de permisos disponible cuando sea necesario.
- Para cambios sólo de documentación, comprueba enlaces y opciones reales; no repitas pruebas de hardware ni instales drivers.
- La validación del 10 de noviembre de 2026 pasó 47 pruebas. No acredita el TL-WN725N físico ni el juego. Informa lo comprobado y lo pendiente tras cambios funcionales.
- Si añades instrucciones distribuibles, actualiza la lista explícita de `tplink.build_bundle`, regenera el kit y verifica contenido/integridad. Usa `bundle --download` cuando necesites originales ausentes para el kit.

## Datos y entrega

No incluyas claves, certificados privados, SQLite, capturas, entornos virtuales ni rutas personales en entregables. Las notas `switch2_tunnel_project.md`, `switch2_tunnel_architecture.md`, capturas y scripts locales de investigación no forman parte del kit. Respeta cambios de otras tareas en el directorio.

Construye el ZIP con la lista permitida de `tplink.py`; no comprimas toda la carpeta. `drivers/cache/` y `dist/` están excluidos de Git. Conserva el origen y condiciones de los paquetes oficiales. Antes de publicar el repositorio revisa por separado lo que se vaya a versionar: la lista del ZIP no controla lo que entra en Git.
