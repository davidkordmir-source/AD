$ErrorActionPreference = 'Stop'
try {
    $appRoot = Split-Path -Parent $PSScriptRoot
    $manifestPath = Join-Path $appRoot 'RUNTIME_MANIFEST.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        throw 'Missing bundled runtime. Extract the COMPLETE FastViewshed_Offline_Windows_x64 ZIP. The source-only update is insufficient; no internet download will be attempted.'
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $runtimePath = Join-Path $appRoot 'runtime_offline'
    $markerPath = Join-Path $runtimePath '.offline-ready.json'
    if (Test-Path -LiteralPath $markerPath) {
        $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
        if ($marker.path -eq $runtimePath -and $marker.sha256 -eq $manifest.sha256 -and
            (Test-Path -LiteralPath (Join-Path $runtimePath 'python.exe')) -and
            (Test-Path -LiteralPath (Join-Path $runtimePath 'pythonw.exe'))) {
            exit 0
        }
    }
    $archive = Join-Path $appRoot $manifest.runtime_archive
    if (-not (Test-Path -LiteralPath $archive)) { throw 'runtime_win64.zip is missing. Copy the full offline package.' }
    Write-Host 'Verifying bundled packages (local files only)...'
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.sha256) {
        throw 'Runtime checksum mismatch. Copy the original offline ZIP again.'
    }
    if (Test-Path -LiteralPath $markerPath) { Remove-Item -LiteralPath $markerPath -Force }
    New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
    Write-Host 'Extracting the private Python, GDAL, NumPy and Qt runtime...'
    # Re-extracting the immutable payload also repairs a moved installation.
    $tarPath = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (Test-Path -LiteralPath $tarPath) {
        & $tarPath -xf $archive -C $runtimePath
        if ($LASTEXITCODE -ne 0) { throw 'Runtime extraction failed.' }
    } else {
        Expand-Archive -LiteralPath $archive -DestinationPath $runtimePath -Force
    }
    & (Join-Path $appRoot '_Finalize_Offline.bat')
    if ($LASTEXITCODE -ne 0) { throw 'Local runtime validation failed. Keep the console output for troubleshooting.' }
    @{ path = $runtimePath; sha256 = $manifest.sha256; version = $manifest.version } |
        ConvertTo-Json | Set-Content -LiteralPath $markerPath -Encoding UTF8
    Write-Host 'Offline installation verified. Run_Fast_Viewshed.bat opens the GUI.'
    exit 0
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
