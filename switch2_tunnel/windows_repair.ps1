param([Parameter(Mandatory=$true)][string]$InstanceId,
      [ValidateSet('Auto','LocalOnly')][string]$Mode = 'Auto',
      [string]$DriverInf)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$ProgressPreference = 'SilentlyContinue'
function Finish([string]$Message, [string]$State = 'manual') {
    @{ message = $Message; state = $State } | ConvertTo-Json -Compress
    exit 0
}
function Get-Target {
    Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPDeviceID -eq $InstanceId -and $_.Present -eq $true } | Select-Object -First 1
}
try {
    if ($InstanceId -notmatch '^USB\\VID_[0-9A-F]{4}&PID_[0-9A-F]{4}') { throw 'Identificador USB no válido.' }
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Finish 'Se requieren permisos de administrador. Abre PowerShell como administrador y repite el comando con --repair.'
    }
    $target = Get-Target
    if (-not $target) { Finish 'El USB ya no está conectado. No se descargó ningún controlador.' }
    if ($target.ConfigManagerErrorCode -ne 28) { Finish 'El dispositivo no indica controlador ausente (código 28). No se descargó ni sustituyó nada.' }

    # Ask Windows to bind a locally staged driver before any network operation.
    $scanOutput = & pnputil.exe /scan-devices /instanceid $InstanceId 2>&1
    if ($LASTEXITCODE -ne 0) { Finish 'Windows no permitió revisar los controladores locales. Instala el driver desde Administrador de dispositivos; no se inició una descarga.' }
    $target = Get-Target
    if (-not $target) { Finish 'Se desconectó el USB durante la revisión local.' }
    if ($target.ConfigManagerErrorCode -ne 28) { Finish 'Windows volvió a detectar el dispositivo usando los controladores locales. Se comprobará su estado; no se descargó otro driver.' }
    $local = & pnputil.exe /enum-devices /instanceid $InstanceId /drivers 2>&1
    if ($LASTEXITCODE -ne 0) { Finish 'No se pudo comprobar el almacén local. Usa Administrador de dispositivos para instalar el controlador; no se inició una descarga.' }
    $infs = @([regex]::Matches(($local -join "`n"), '(?i)\b[a-z0-9_.-]+\.inf\b') | ForEach-Object { $_.Value } | Select-Object -Unique)
    if ($infs.Count -gt 0) {
        foreach ($inf in $infs) {
            $path = Join-Path (Join-Path $env:windir 'INF') $inf
            if (Test-Path -LiteralPath $path) {
                $installOutput = & pnputil.exe /add-driver $path /install 2>&1
            }
        }
        Finish 'Se encontraron controladores locales compatibles y se intentó instalarlos. No se descargó otro; si persiste el error, completa la instalación en Administrador de dispositivos.'
    }

    if ($Mode -eq 'LocalOnly') { Finish 'No se encontraron controladores locales compatibles; el USB sigue indicando driver ausente.' 'missing' }
    if ($DriverInf) {
        if (-not (Test-Path -LiteralPath $DriverInf -PathType Leaf) -or [IO.Path]::GetExtension($DriverInf) -ne '.inf') {
            Finish 'No existe el INF oficial preparado. Repite la preparación del kit.'
        }
        $text = Get-Content -LiteralPath $DriverInf -Raw
        $matchesDevice = $false
        foreach ($hardwareId in $target.HardwareID) {
            if ($text -match ('(?im)(?<![a-z0-9_&])' + [regex]::Escape($hardwareId) + '(?=[,\s;]|$)')) { $matchesDevice = $true }
        }
        if (-not $matchesDevice) { Finish 'El INF no coincide con los identificadores del USB. No se instalará ese paquete.' }
        $target = Get-Target
        if (-not $target -or $target.ConfigManagerErrorCode -ne 28) { Finish 'El estado del USB cambió. No se instaló el paquete.' }
        # PnPUtil verifies the package catalog/signature. Do not disable signature checks.
        $result = & pnputil.exe /add-driver $DriverInf /install 2>&1
        if ($LASTEXITCODE -notin @(0,3010)) {
            Finish ('Windows no completó la instalación del INF oficial. Usa Administrador de dispositivos > Actualizar controlador > Buscar en mi equipo, carpeta: ' + (Split-Path -Parent $DriverInf) + '. Detalle: ' + ($result -join ' '))
        }
        if ($LASTEXITCODE -eq 3010) { Finish 'Windows instaló el paquete oficial y pide reiniciar. Reinicia manualmente y repite el diagnóstico.' }
        Finish 'Windows procesó el INF oficial TP-Link. Se comprobará de nuevo que el USB tenga el driver instalado.'
    }

    # Windows Update chooses signed driver updates; never download random EXE files.
    $hardwareIds = @($target.HardwareID)
    if ($hardwareIds.Count -eq 0) { Finish 'Faltan identificadores de hardware. Consulta el modelo y Ver: de la etiqueta e instala el paquete oficial del fabricante.' }
    $session = New-Object -ComObject Microsoft.Update.Session
    $searcher = $session.CreateUpdateSearcher()
    $found = $searcher.Search("IsInstalled=0 and Type='Driver' and IsHidden=0")
    $update = $null
    for ($i = 0; $i -lt $found.Updates.Count; $i++) {
        $candidate = $found.Updates.Item($i)
        if ($hardwareIds -contains $candidate.DriverHardwareID) { $update = $candidate; break }
    }
    if ($null -eq $update) { Finish 'Windows Update no ofrece un controlador para los identificadores exactos del USB. Instala manualmente el paquete oficial del fabricante para tu modelo, revisión y Windows.' }
    if (-not $update.EulaAccepted) { Finish 'El controlador requiere aceptar una licencia. Instálalo tú desde Windows Update > Opciones avanzadas > Actualizaciones opcionales > Controladores.' }
    # Recheck absence immediately before downloading.
    $target = Get-Target
    if (-not $target -or $target.ConfigManagerErrorCode -ne 28) { Finish 'El estado del USB cambió. No se inició una descarga.' }
    $updates = New-Object -ComObject Microsoft.Update.UpdateColl
    [void]$updates.Add($update)
    $downloader = $session.CreateUpdateDownloader()
    $downloader.Updates = $updates
    $download = $downloader.Download()
    if ($download.ResultCode -ne 2) { Finish 'Windows Update no pudo descargar el controlador. Usa su sección de actualizaciones opcionales o el soporte oficial del fabricante.' }
    $installer = $session.CreateUpdateInstaller()
    $installer.Updates = $updates
    $installed = $installer.Install()
    if ($installed.ResultCode -ne 2) { Finish 'El controlador se descargó, pero Windows no completó la instalación. Instálalo desde Windows Update o Administrador de dispositivos.' }
    if ($installed.RebootRequired) { Finish 'Controlador instalado mediante Windows Update. Reinicia Windows manualmente y repite el diagnóstico; el programa no reiniciará el PC.' }
    Finish 'Windows Update instaló el controlador. Se volverá a comprobar el dispositivo.'
} catch {
    Finish ("No se pudo completar la instalación automática: " + $_.Exception.Message + '. Instala el controlador firmado del fabricante para el USB, modelo, revisión y Windows indicados en el diagnóstico.')
}
