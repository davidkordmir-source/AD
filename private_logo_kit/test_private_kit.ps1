param([Parameter(Mandatory=$true)][string]$Archive, [Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$testRoot = Join-Path $env:RUNNER_TEMP ('Private logo kit with spaces ' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
Expand-Archive -LiteralPath $Archive -DestinationPath $testRoot
$kit = Join-Path $testRoot 'FastViewshed_Private_Logo_Kit'
$builder = Join-Path $kit 'Build_Custom_Setup.ps1'
$shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
# Missing input must not silently produce an installer without branding.
& $shell -NoProfile -ExecutionPolicy Bypass -File $builder *> (Join-Path $Output 'MISSING_LOGO_TEST.log')
if ($LASTEXITCODE -eq 0) { throw 'Missing logo incorrectly passed.' }
if (Test-Path -LiteralPath (Join-Path $kit 'Output\FastViewshed_With_Logo_Setup.exe')) { throw 'Unexpected unbranded output.' }
Add-Type -AssemblyName System.Drawing
$logo = Join-Path $kit 'Logo_Input\logo.png'
$image = New-Object System.Drawing.Bitmap(100, 80)
try {
    $graphics = [System.Drawing.Graphics]::FromImage($image)
    try { $graphics.Clear([System.Drawing.Color]::FromArgb(70, 130, 180)) } finally { $graphics.Dispose() }
    $image.Save($logo, [System.Drawing.Imaging.ImageFormat]::Png)
} finally { $image.Dispose() }
$expected = (Get-FileHash -LiteralPath $logo -Algorithm SHA256).Hash.ToLowerInvariant()
& $shell -NoProfile -ExecutionPolicy Bypass -File $builder
if ($LASTEXITCODE -ne 0) { throw 'Local private installer build failed.' }
if ((Get-FileHash -LiteralPath $logo -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'The original user logo was modified.' }
$installer = Join-Path $kit 'Output\FastViewshed_With_Logo_Setup.exe'
# The existing test performs a real fresh installation, firewall isolation,
# GUI startup, native analysis, shortcut checks and uninstallation.
& (Join-Path $root 'FastViewshed_GUI_Windows\scripts\test_windows_installer.ps1') -Installer $installer -Output $Output
$report = Get-Content -LiteralPath (Join-Path $Output 'WINDOWS_INSTALLER_VALIDATION.json') -Raw | ConvertFrom-Json
if ($report.status -ne 'passed') { throw 'The private installer did not pass Windows validation.' }
if ($report.native_gis.shipped_logo -ne 'logo.png' -or $report.native_gis.shipped_logo_sha256 -ne $expected) {
    throw 'A fresh target did not load the exact logo embedded by the local build.'
}
@{status='passed';private_local_build=$true;missing_logo_rejected=$true;original_logo_preserved=$true;embedded_logo_sha256=$expected;installed_logo_verified=$true;windows=$report} |
    ConvertTo-Json -Depth 15 | Set-Content -LiteralPath (Join-Path $Output 'PRIVATE_LOGO_KIT_VALIDATION.json') -Encoding UTF8
Write-Host 'PASS: local build, embedded logo, offline installation, GUI and uninstallation.'
