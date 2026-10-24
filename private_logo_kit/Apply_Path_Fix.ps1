$ErrorActionPreference = 'Stop'
$mapping = $null
$backup = $null
$backupReady = $false
$manifestTemp = $null
$keepBackup = $false
try {
    $kit = $PSScriptRoot
    $fixRoot = Join-Path $kit 'Path_Fix'
    $fix = Get-Content -LiteralPath (Join-Path $fixRoot 'FIX_FILES_SHA256.json') -Raw | ConvertFrom-Json
    $allowed = @('Build_Custom_Setup.ps1', 'Short_Paths.ps1', 'PrivateLogo.iss', 'README_FA.txt')
    if ($fix.files.Count -ne $allowed.Count) { throw 'Incomplete path fix.' }
    foreach ($name in $allowed) {
        if (@($fix.files | Where-Object { $_.path -ceq $name }).Count -ne 1) { throw 'Unexpected path fix layout.' }
    }
    foreach ($entry in $fix.files) {
        $source = Join-Path (Join-Path $fixRoot 'Files') $entry.path
        if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) { throw ('Path fix checksum mismatch: ' + $entry.path) }
    }
    . (Join-Path $fixRoot 'Files\Short_Paths.ps1')
    $mapping = New-FVShortPath -Directory $kit
    $kit = $mapping.Root
    $fixRoot = Join-Path $kit 'Path_Fix'
    $manifestPath = Join-Path $kit 'KIT_FILES_SHA256.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw 'Extract this fix beside Build_Custom_Setup.bat in the complete 3.5 kit, then run Apply_Path_Fix.bat.' }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.version -notin @('3.5.0', '3.5.1')) { throw 'This fix requires the complete private kit 3.5.0 or 3.5.1.' }
    Write-Host 'Verifying the existing complete kit. Your logo and Output are preserved...'
    foreach ($entry in $manifest.files) {
        $file = Join-Path $kit $entry.path
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw ('Original kit file is missing: ' + $entry.path) }
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) { throw ('Original kit checksum mismatch: ' + $entry.path + '. Restore that file from the original ZIP first.') }
    }
    foreach ($entry in $fix.files) {
        $matches = @($manifest.files | Where-Object { $_.path -ceq $entry.path })
        if ($matches.Count -ne 1) {
            if ($entry.path -cne 'Short_Paths.ps1' -or $matches.Count -ne 0 -or (Test-Path -LiteralPath (Join-Path $kit $entry.path))) { throw ('Unknown original kit layout: ' + $entry.path) }
        }
    }
    $backup = Join-Path $kit ('_PathFixBackup_' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $backup | Out-Null
    Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $backup 'KIT_FILES_SHA256.json')
    $originalFiles = @()
    foreach ($entry in $fix.files) {
        $original = Join-Path $kit $entry.path
        if (Test-Path -LiteralPath $original) {
            Copy-Item -LiteralPath $original -Destination (Join-Path $backup $entry.path)
            $originalFiles += $entry.path
        }
    }
    $backupReady = $true
    foreach ($entry in $fix.files) {
        Copy-Item -LiteralPath (Join-Path (Join-Path $fixRoot 'Files') $entry.path) -Destination (Join-Path $kit $entry.path) -Force
        $matches = @($manifest.files | Where-Object { $_.path -ceq $entry.path })
        if ($matches.Count -eq 1) { $matches[0].sha256 = $entry.sha256 } else { $manifest.files = @($manifest.files) + $entry }
    }
    $manifest.version = '3.5.1'
    $manifestTemp = Join-Path $kit ('KIT_FILES_SHA256.' + [guid]::NewGuid().ToString('N') + '.tmp')
    [IO.File]::WriteAllText($manifestTemp, ($manifest | ConvertTo-Json -Depth 10), [Text.Encoding]::UTF8)
    [IO.File]::Replace($manifestTemp, $manifestPath, (Join-Path $backup 'replaced-manifest.json'))
    $backupReady = $false
    Write-Host 'Fix applied (3.5.1). Run Build_Custom_Setup.bat again.' -ForegroundColor Green
    Write-Host 'No administrator access or Windows setting change is needed. Your logo stays local.'
    exit 0
} catch {
    $failure = $_.Exception.Message
    if ($backupReady) {
        try {
            foreach ($entry in $fix.files) {
                $target = Join-Path $kit $entry.path
                if ($entry.path -cin $originalFiles) { Copy-Item -LiteralPath (Join-Path $backup $entry.path) -Destination $target -Force }
                elseif (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Force }
            }
            Copy-Item -LiteralPath (Join-Path $backup 'KIT_FILES_SHA256.json') -Destination $manifestPath -Force
        } catch {
            $keepBackup = $true
            Write-Warning ('Rollback needs attention. Original files preserved at: ' + (Get-FVPhysicalPath -Path $backup -Mapping $mapping))
        }
    }
    Write-Host $failure -ForegroundColor Red
    exit 1
} finally {
    try {
        if ($manifestTemp -and (Test-Path -LiteralPath $manifestTemp)) { Remove-Item -LiteralPath $manifestTemp -Force }
        if ($backup -and -not $keepBackup -and (Test-Path -LiteralPath $backup)) { Remove-Item -LiteralPath $backup -Recurse -Force }
    } catch { Write-Warning ('Temporary update files could not be removed: ' + $_.Exception.Message) }
    finally { if ($mapping) { Remove-FVShortPath -Mapping $mapping } }
}
