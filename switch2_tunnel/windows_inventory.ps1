$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$ProgressPreference = 'SilentlyContinue'
try {
$signed = @{}
Get-CimInstance Win32_PnPSignedDriver | ForEach-Object { $signed[$_.DeviceID] = $_ }
$wirelessIds = @{}
Get-NetAdapter -IncludeHidden -ErrorAction SilentlyContinue | Where-Object {
    $_.NdisPhysicalMedium -in @(1, 9)
} | ForEach-Object { $wirelessIds[$_.PnPDeviceID] = $true }
$rows = @(Get-CimInstance Win32_PnPEntity | Where-Object {
    $_.PNPDeviceID -match '^USB\\VID_[0-9A-F]{4}&PID_[0-9A-F]{4}' -and $_.Present -eq $true
} | ForEach-Object {
    $driver = $signed[$_.PNPDeviceID]
    [PSCustomObject]@{
        instance_id = $_.PNPDeviceID
        name = $_.Name
        pnp_class = $_.PNPClass
        service = $_.Service
        error_code = $_.ConfigManagerErrorCode
        driver_inf = $driver.InfName
        driver_version = $driver.DriverVersion
        wireless = $wirelessIds.ContainsKey($_.PNPDeviceID)
    }
})
ConvertTo-Json -InputObject $rows -Depth 4 -Compress
} catch {
    @{ error = ('No se pudo consultar los dispositivos de Windows: ' + $_.Exception.Message + '. Comprueba los permisos de consulta CIM/WMI y ejecuta el diagnóstico fuera de un entorno restringido.') } | ConvertTo-Json -Compress
}
