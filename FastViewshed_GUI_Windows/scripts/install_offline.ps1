$ErrorActionPreference = 'Stop'
$started = [Diagnostics.Stopwatch]::StartNew()
function Get-RuntimeSha256([string]$FilePath) {
    $stream = [IO.File]::OpenRead($FilePath)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}
try {
    $appRoot = Split-Path -Parent $PSScriptRoot
    $manifestPath = Join-Path $appRoot 'RUNTIME_MANIFEST.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        throw 'Missing bundled runtime. Extract the COMPLETE FastViewshed_Offline_Windows_x64 ZIP. The source-only update is insufficient; no internet download will be attempted.'
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $runtimePath = Join-Path $appRoot 'runtime_offline'
    $markerPath = Join-Path $runtimePath '.offline-ready.json'
    $hadMarker = Test-Path -LiteralPath $markerPath
    if ($hadMarker) {
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
    $hashStream = [System.IO.File]::OpenRead($archive)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $actualHash = [System.BitConverter]::ToString($sha.ComputeHash($hashStream)).Replace('-','').ToLowerInvariant()
    } finally {
        $hashStream.Dispose()
        $sha.Dispose()
    }
    if ($actualHash -ne $manifest.sha256) {
        throw 'Runtime checksum mismatch. Copy the original offline ZIP again.'
    }
    if (Test-Path -LiteralPath $markerPath) { Remove-Item -LiteralPath $markerPath -Force }
    $prepared = $false
    $packedFiles = Join-Path $runtimePath '.packed-files.json'
    if (-not $hadMarker -and (Test-Path -LiteralPath $packedFiles)) {
        $packed = Get-Content -LiteralPath $packedFiles -Raw | ConvertFrom-Json
        if ($packed.archive_sha256 -eq $manifest.sha256 -and $packed.files.Count -gt 0) {
            Write-Host 'Checking the already extracted portable runtime...'
            $prepared = $true
            $runtimeRoot = [IO.Path]::GetFullPath($runtimePath).TrimEnd('\') + '\'
            foreach ($entry in $packed.files) {
                $file = [IO.Path]::GetFullPath((Join-Path $runtimePath $entry.path))
                if (-not $file.StartsWith($runtimeRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid portable runtime manifest path.' }
                if (-not (Test-Path -LiteralPath $file -PathType Leaf) -or (Get-RuntimeSha256 -FilePath $file) -ne $entry.sha256) {
                    $prepared = $false
                    break
                }
            }
        }
    }
    New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
    if (-not $prepared) {
        Write-Host 'Extracting the private Python, GDAL, NumPy and Qt runtime...'
        # A moved initialized runtime is repaired from the immutable archive.
        $tarPath = Join-Path $env:SystemRoot 'System32\tar.exe'
        if (Test-Path -LiteralPath $tarPath) {
            & $tarPath -xf $archive -C $runtimePath
            if ($LASTEXITCODE -ne 0) { throw 'Runtime extraction failed.' }
        } else {
            Expand-Archive -LiteralPath $archive -DestinationPath $runtimePath -Force
        }
    }
    & (Join-Path $appRoot '_Finalize_Offline.bat')
    if ($LASTEXITCODE -ne 0) { throw 'Local runtime validation failed. Keep the console output for troubleshooting.' }
    @{ path = $runtimePath; sha256 = $manifest.sha256; version = $manifest.version; used_preextracted_runtime = $prepared; initialization_seconds = $started.Elapsed.TotalSeconds } |
        ConvertTo-Json | Set-Content -LiteralPath $markerPath -Encoding UTF8
    Write-Host 'Offline installation verified. Run_Fast_Viewshed.bat opens the GUI.'
    exit 0
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
