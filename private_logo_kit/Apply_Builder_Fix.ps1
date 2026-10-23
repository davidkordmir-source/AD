$ErrorActionPreference = 'Stop'
$backup = $null
$backupReady = $false
$manifestTemp = $null
try {
    $kit = $PSScriptRoot
    $manifestPath = Join-Path $kit 'KIT_FILES_SHA256.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        throw 'Extract this small fix INSIDE the original kit folder, beside Build_Custom_Setup.bat, then run Apply_Builder_Fix.bat.'
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    foreach ($entry in $manifest.files) {
        $file = Join-Path $kit $entry.path
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw ('Original kit file is missing: ' + $entry.path) }
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) {
            throw ('Original kit checksum mismatch: ' + $entry.path + '. Restore that file from the original ZIP first.')
        }
    }
    $fixRoot = Join-Path $kit 'Builder_Fix'
    $fix = Get-Content -LiteralPath (Join-Path $fixRoot 'FIX_FILES_SHA256.json') -Raw | ConvertFrom-Json
    $allowed = @('Build_Custom_Setup.bat', 'Build_Custom_Setup.ps1', 'README_FA.txt', 'Logo_Input/README_FA.txt')
    if ($fix.files.Count -ne $allowed.Count) { throw 'Incomplete builder fix.' }
    foreach ($entry in $fix.files) {
        if ($entry.path -cnotin $allowed) { throw 'Unexpected file in builder fix.' }
        $source = Join-Path (Join-Path $fixRoot 'Files') $entry.path
        if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) { throw 'Builder fix checksum mismatch.' }
        $match = @($manifest.files | Where-Object { $_.path -ceq $entry.path })
        if ($match.Count -ne 1) { throw ('Unknown original kit layout: ' + $entry.path) }
    }
    $backup = Join-Path ([IO.Path]::GetTempPath()) ('FastViewshed-fix-backup-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $backup | Out-Null
    Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $backup 'KIT_FILES_SHA256.json')
    foreach ($entry in $fix.files) {
        $saved = Join-Path $backup $entry.path
        New-Item -ItemType Directory -Path (Split-Path $saved -Parent) -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $kit $entry.path) -Destination $saved
    }
    $backupReady = $true
    foreach ($entry in $fix.files) {
        Copy-Item -LiteralPath (Join-Path (Join-Path $fixRoot 'Files') $entry.path) -Destination (Join-Path $kit $entry.path) -Force
        ($manifest.files | Where-Object { $_.path -ceq $entry.path }).sha256 = $entry.sha256
    }
    $manifestTemp = Join-Path $kit ('KIT_FILES_SHA256.' + [guid]::NewGuid().ToString('N') + '.tmp')
    [IO.File]::WriteAllText($manifestTemp, ($manifest | ConvertTo-Json -Depth 10), [Text.Encoding]::UTF8)
    Move-Item -LiteralPath $manifestTemp -Destination $manifestPath -Force
    $backupReady = $false
    Write-Host 'Fix applied. Run Build_Custom_Setup.bat again.' -ForegroundColor Green
    Write-Host 'Any PNG filename is accepted. If needed, select your logo in the file window. Nothing is uploaded.'
    exit 0
} catch {
    if ($backupReady) {
        foreach ($entry in $fix.files) { Copy-Item -LiteralPath (Join-Path $backup $entry.path) -Destination (Join-Path $kit $entry.path) -Force }
        Copy-Item -LiteralPath (Join-Path $backup 'KIT_FILES_SHA256.json') -Destination $manifestPath -Force
    }
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    if ($manifestTemp -and (Test-Path -LiteralPath $manifestTemp)) { Remove-Item -LiteralPath $manifestTemp -Force }
    if ($backup -and (Test-Path -LiteralPath $backup)) { Remove-Item -LiteralPath $backup -Recurse -Force }
}
