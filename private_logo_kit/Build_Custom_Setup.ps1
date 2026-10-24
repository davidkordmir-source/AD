param([string]$OutputDirectory, [string]$LogoFile, [switch]$NonInteractive)
$ErrorActionPreference = 'Stop'
$work = $null
$pathMapping = $null
try {
    $kitOriginal = $PSScriptRoot
    . (Join-Path $kitOriginal 'Short_Paths.ps1')
    $pathMapping = New-FVShortPath -Directory $kitOriginal
    $kit = $pathMapping.Root
    $logoFolder = Join-Path $kit 'Logo_Input'
    if ($LogoFile) {
        $logo = [IO.Path]::GetFullPath($LogoFile)
    } else {
        $candidates = @()
        if (Test-Path -LiteralPath $logoFolder -PathType Container) {
            $candidates = @(Get-ChildItem -LiteralPath $logoFolder -File -Force | Where-Object { $_.Extension -ieq '.png' })
        }
        if ($candidates.Count -eq 1) {
            $logo = $candidates[0].FullName
        } elseif ($NonInteractive) {
            if ($candidates.Count -eq 0) { throw ('No PNG image found. Searched folder: ' + $logoFolder) }
            throw ('Multiple PNG images found in ' + $logoFolder + '. Keep one image or pass -LogoFile with its full path.')
        } else {
            Write-Host ('PNG input folder: ' + $logoFolder)
            Write-Host 'Select your logo in the file window. Nothing will be uploaded.'
            Add-Type -AssemblyName System.Windows.Forms
            $picker = New-Object System.Windows.Forms.OpenFileDialog
            try {
                $picker.Title = 'Choose your private PNG logo (local file only)'
                $picker.Filter = 'PNG images (*.png)|*.png|All files (*.*)|*.*'
                $picker.InitialDirectory = $kit
                if (Test-Path -LiteralPath $logoFolder -PathType Container) { $picker.InitialDirectory = $logoFolder }
                if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { throw 'Logo selection cancelled. No installer was changed.' }
                $logo = $picker.FileName
            } finally { $picker.Dispose() }
        }
    }
    if (-not (Test-Path -LiteralPath $logo -PathType Leaf)) { throw ('Selected logo file does not exist: ' + $logo) }
    Write-Host ('Selected PNG: ' + $logo)
    Add-Type -AssemblyName System.Drawing
    $image = [System.Drawing.Image]::FromFile($logo)
    try {
        if ($image.RawFormat.Guid -ne [System.Drawing.Imaging.ImageFormat]::Png.Guid) {
            throw 'The logo must be a real PNG image, not a renamed JPG.'
        }
        if ($image.Width -lt 1 -or $image.Height -lt 1) { throw 'The logo image is empty.' }
    } finally { $image.Dispose() }
    $manifest = Get-Content -LiteralPath (Join-Path $kit 'KIT_FILES_SHA256.json') -Raw | ConvertFrom-Json
    Write-Host 'Checking local installer and compiler files...'
    foreach ($entry in $manifest.files) {
        $file = Join-Path $kit $entry.path
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw ('Missing kit file: ' + $entry.path) }
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) {
            throw ('Kit checksum mismatch: ' + $entry.path + '. Extract the original kit again.')
        }
    }
    if (-not $OutputDirectory) { $OutputDirectory = Join-Path $kit 'Output' }
    $destination = [IO.Path]::GetFullPath($OutputDirectory)
    $originalPrefix = [IO.Path]::GetFullPath($kitOriginal).TrimEnd('\') + '\'
    if ($destination.StartsWith($originalPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        $destination = Join-Path $kit $destination.Substring($originalPrefix.Length)
    }
    $runtimeInfo = Get-Content -LiteralPath (Join-Path $kit 'Payload\RUNTIME_MANIFEST.json') -Raw | ConvertFrom-Json
    $archiveSize = (Get-Item -LiteralPath (Join-Path $kit 'Payload\runtime_win64.zip')).Length
    $required = [long]$runtimeInfo.uncompressed_bytes + 4 * $archiveSize + 512MB
    $drive = New-Object System.IO.DriveInfo([IO.Path]::GetPathRoot($kitOriginal))
    if ($drive.AvailableFreeSpace -lt $required) { throw ('Not enough free disk space. Need about ' + [math]::Ceiling($required / 1GB) + ' GB for the complete output.') }
    $work = Join-Path $kit ('_Build_' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $work | Out-Null
    Copy-Item -LiteralPath $logo -Destination (Join-Path $work 'logo.png')
    $stage = Join-Path $work 'App'
    New-Item -ItemType Directory -Path $stage | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $kit 'Payload') -Force | Copy-Item -Destination $stage -Recurse
    $desktopModule = Join-Path $stage 'desktop_customization.py'
    $source = [IO.File]::ReadAllText($desktopModule)
    if (-not $source.Contains('REQUIRE_EMBEDDED_LOGO = False')) { throw 'The logo protection module is not the expected version.' }
    [IO.File]::WriteAllText($desktopModule, $source.Replace('REQUIRE_EMBEDDED_LOGO = False', 'REQUIRE_EMBEDDED_LOGO = True'), [Text.Encoding]::UTF8)
    $csc = Join-Path $env:SystemRoot 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    if (-not (Test-Path -LiteralPath $csc)) { throw 'The Windows .NET Framework compiler is unavailable.' }
    $launcher = Join-Path $stage 'FastViewshed.exe'
    & $csc /nologo /target:winexe /platform:x64 "/win32icon:$stage\assets\aircraft.ico" "/out:$launcher" /reference:System.Windows.Forms.dll (Join-Path $kit 'FastViewshedLauncher.cs')
    if ($LASTEXITCODE -ne 0) { throw 'Compiling the application launcher failed.' }
    & (Join-Path $kit 'Embed_Logo.ps1') -Executable $launcher -Logo (Join-Path $work 'logo.png')
    $compiler = Join-Path $kit 'Toolchain\ISCC.exe'
    $deliverable = Join-Path $work 'Deliverable'
    New-Item -ItemType Directory -Path $deliverable | Out-Null
    Write-Host 'Building the complete offline installer locally. No files are uploaded.'
    & $compiler "/DStageDir=$stage" "/DOutputDir=$deliverable" (Join-Path $kit 'PrivateLogo.iss')
    if ($LASTEXITCODE -ne 0) { throw 'The local installer compiler failed.' }
    $built = Join-Path $deliverable 'FastViewshed_With_Logo_Setup.exe'
    if (-not (Test-Path -LiteralPath $built)) { throw 'The compiler did not produce an installer.' }
    $portable = Join-Path $deliverable 'Portable'
    New-Item -ItemType Directory -Path $portable | Out-Null
    Get-ChildItem -LiteralPath $stage -Force | Copy-Item -Destination $portable -Recurse
    $runtime = Join-Path $portable 'runtime_offline'
    New-Item -ItemType Directory -Path $runtime | Out-Null
    Write-Host 'Extracting all Python, GDAL and Qt files for the complete portable output...'
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (Test-Path -LiteralPath $tar) {
        & $tar -xf (Join-Path $portable 'runtime_win64.zip') -C $runtime
        if ($LASTEXITCODE -ne 0) { throw 'Portable runtime extraction failed.' }
    } else { Expand-Archive -LiteralPath (Join-Path $portable 'runtime_win64.zip') -DestinationPath $runtime }
    $runtimeRoot = [IO.Path]::GetFullPath($runtime).TrimEnd('\') + '\'
    $packedFiles = @(Get-ChildItem -LiteralPath $runtime -File -Recurse | ForEach-Object {
        @{path=$_.FullName.Substring($runtimeRoot.Length);sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
    })
    @{archive_sha256=$runtimeInfo.sha256;files=$packedFiles} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runtime '.packed-files.json') -Encoding UTF8
    Copy-Item -LiteralPath (Join-Path $kit 'OUTPUT_README_FA.txt') -Destination (Join-Path $deliverable 'README_FA.txt')
    $inventory = @(Get-ChildItem -LiteralPath $deliverable -File -Recurse | ForEach-Object {
        @{path=$_.FullName.Substring($deliverable.Length + 1);bytes=$_.Length}
    })
    @{version='3.5.0';files=$inventory;embedded_logo=$true} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $deliverable 'FILES.json') -Encoding UTF8
    $checks = @()
    $checks += ((Get-FileHash -LiteralPath $built -Algorithm SHA256).Hash.ToLowerInvariant() + '  FastViewshed_With_Logo_Setup.exe')
    $checks += ((Get-FileHash -LiteralPath (Join-Path $portable 'FastViewshed.exe') -Algorithm SHA256).Hash.ToLowerInvariant() + '  Portable/FastViewshed.exe')
    [IO.File]::WriteAllText((Join-Path $deliverable 'SHA256SUMS.txt'), ($checks -join [Environment]::NewLine), [Text.Encoding]::ASCII)
    $previous = $null
    if (Test-Path -LiteralPath $destination) {
        $previous = $destination + '.previous.' + [guid]::NewGuid().ToString('N')
        Move-Item -LiteralPath $destination -Destination $previous
    }
    try { Move-Item -LiteralPath $deliverable -Destination $destination } catch {
        if ($previous -and -not (Test-Path -LiteralPath $destination)) { Move-Item -LiteralPath $previous -Destination $destination }
        throw
    }
    Write-Host ('Ready: ' + (Get-FVPhysicalPath -Path $destination -Mapping $pathMapping)) -ForegroundColor Green
    Write-Host 'Output includes the installer AND the full Portable folder, with all runtime files. No separate logo file is included.'
    if ($previous) { Write-Host ('Previous output preserved: ' + (Get-FVPhysicalPath -Path $previous -Mapping $pathMapping)) }
    exit 0
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    try {
        if ($work -and (Test-Path -LiteralPath $work)) { Remove-Item -LiteralPath $work -Recurse -Force }
    } catch {
        Write-Warning ('Temporary files could not be fully removed: ' + (Get-FVPhysicalPath -Path $work -Mapping $pathMapping) + '. ' + $_.Exception.Message)
    } finally {
        if ($pathMapping) { Remove-FVShortPath -Mapping $pathMapping }
    }
}
