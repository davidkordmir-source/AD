param([string]$OutputDirectory, [string]$LogoFile, [switch]$NonInteractive)
$ErrorActionPreference = 'Stop'
$work = $null
try {
    $kit = $PSScriptRoot
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
    $work = Join-Path ([IO.Path]::GetTempPath()) ('FastViewshed-local-logo-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $work | Out-Null
    Copy-Item -LiteralPath $logo -Destination (Join-Path $work 'logo.png')
    $compiler = Join-Path $kit 'Toolchain\ISCC.exe'
    $baseHash = (Get-FileHash -LiteralPath (Join-Path $kit 'BaseSetup.exe') -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host 'Building your private installer locally. No files are uploaded.'
    & $compiler "/DKitRoot=$kit" "/DLogoFile=$work\logo.png" "/DOutputDir=$work" "/DBaseSHA256=$baseHash" (Join-Path $kit 'PrivateLogo.iss')
    if ($LASTEXITCODE -ne 0) { throw 'The local installer compiler failed.' }
    $built = Join-Path $work 'FastViewshed_With_Logo_Setup.exe'
    if (-not (Test-Path -LiteralPath $built)) { throw 'The compiler did not produce an installer.' }
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    $outputFile = Join-Path $destination 'FastViewshed_With_Logo_Setup.exe'
    Copy-Item -LiteralPath $built -Destination $outputFile -Force
    $hash = (Get-FileHash -LiteralPath $outputFile -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText((Join-Path $destination 'SHA256SUMS.txt'), ($hash + '  FastViewshed_With_Logo_Setup.exe' + [Environment]::NewLine), [Text.Encoding]::ASCII)
    Write-Host ('Ready: ' + $outputFile) -ForegroundColor Green
    Write-Host 'Give this NEW installer to other computers. The logo is embedded inside it.'
    exit 0
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    if ($work -and (Test-Path -LiteralPath $work)) { Remove-Item -LiteralPath $work -Recurse -Force }
}
