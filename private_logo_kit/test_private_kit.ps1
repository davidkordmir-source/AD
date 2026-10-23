param([Parameter(Mandatory=$true)][string]$Archive, [Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$testRoot = Join-Path $env:RUNNER_TEMP ('Complete private kit with spaces ' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
Expand-Archive -LiteralPath $Archive -DestinationPath $testRoot
$kit = Join-Path $testRoot 'FastViewshed_Private_Logo_Kit'
$builder = Join-Path $kit 'Build_Custom_Setup.ps1'
$shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
& $shell -NoProfile -STA -ExecutionPolicy Bypass -File $builder -NonInteractive *> (Join-Path $Output 'MISSING_LOGO_TEST.log')
if ($LASTEXITCODE -eq 0) { throw 'Missing logo incorrectly passed.' }
Add-Type -AssemblyName System.Drawing
$logo = Join-Path $kit 'Logo_Input\My company mark.PNG.PNG'
$image = New-Object System.Drawing.Bitmap(100, 80)
try {
    $graphics = [System.Drawing.Graphics]::FromImage($image)
    try { $graphics.Clear([System.Drawing.Color]::FromArgb(70, 130, 180)) } finally { $graphics.Dispose() }
    $image.Save($logo, [System.Drawing.Imaging.ImageFormat]::Png)
} finally { $image.Dispose() }
$expected = (Get-FileHash -LiteralPath $logo -Algorithm SHA256).Hash.ToLowerInvariant()
$secondLogo = Join-Path $kit 'Logo_Input\another.png'
Copy-Item -LiteralPath $logo -Destination $secondLogo
& $shell -NoProfile -STA -ExecutionPolicy Bypass -File $builder -NonInteractive *> (Join-Path $Output 'AMBIGUOUS_LOGO_TEST.log')
if ($LASTEXITCODE -eq 0) { throw 'Multiple input images were silently accepted.' }
Remove-Item -LiteralPath $secondLogo
& $shell -NoProfile -STA -ExecutionPolicy Bypass -File $builder -NonInteractive 2>&1 | Tee-Object -FilePath (Join-Path $Output 'LOCAL_BUILD_v3.5.0.log')
if ($LASTEXITCODE -ne 0) { throw 'Complete local build failed.' }
if ((Get-FileHash -LiteralPath $logo -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'The original user logo was modified.' }
$delivery = Join-Path $kit 'Output'
$portable = Join-Path $delivery 'Portable'
foreach ($name in @('FastViewshed.exe','FastViewshed_GUI.py','desktop_customization.py','runtime_win64.zip','runtime_offline\python.exe','runtime_offline\pythonw.exe','runtime_offline\Lib\site-packages\osgeo\gdal.py','assets\default_map\area.shp')) {
    if (-not (Test-Path -LiteralPath (Join-Path $portable $name))) { throw ('Incomplete portable output: ' + $name) }
}
# Raw private PNG bytes must never be delivered as a separate image file.
foreach ($file in (Get-ChildItem -LiteralPath $delivery -File -Recurse | Where-Object { $_.Extension -ieq '.png' })) {
    if ((Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -eq $expected) { throw 'The private logo was delivered as a separate PNG file.' }
}
$moved = Join-Path $env:RUNNER_TEMP ('Recipient portable with spaces ' + [guid]::NewGuid().ToString('N'))
Move-Item -LiteralPath $portable -Destination $moved
$rules = @('FV-complete-portable-python','FV-complete-portable-pythonw')
try {
    New-NetFirewallRule -DisplayName $rules[0] -Direction Outbound -Action Block -Program (Join-Path $moved 'runtime_offline\python.exe') -Profile Any | Out-Null
    New-NetFirewallRule -DisplayName $rules[1] -Direction Outbound -Action Block -Program (Join-Path $moved 'runtime_offline\pythonw.exe') -Profile Any | Out-Null
    & (Join-Path $moved 'Install_Fast_Viewshed.bat') --quiet 2>&1 | Tee-Object -FilePath (Join-Path $Output 'PORTABLE_INSTALL_v3.5.0.log')
    if ($LASTEXITCODE -ne 0) { throw 'Transferred portable initialization failed.' }
    $readiness = Get-Content -LiteralPath (Join-Path $moved 'RUNTIME_READY.json') -Raw | ConvertFrom-Json
    if ($readiness.status -ne 'passed' -or $readiness.full_analysis_test) { throw 'Normal initialization did not use the fast runtime prerequisite check.' }
    $markerPath = Join-Path $moved 'runtime_offline\.offline-ready.json'
    $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
    if (-not $marker.used_preextracted_runtime) { throw 'Portable runtime was unnecessarily extracted again.' }
    $markerHash = (Get-FileHash -LiteralPath $markerPath).Hash
    & (Join-Path $moved 'Install_Fast_Viewshed.bat') --quiet
    if ($LASTEXITCODE -ne 0 -or (Get-FileHash -LiteralPath $markerPath).Hash -ne $markerHash) { throw 'Repeated startup did not reuse initialized dependencies.' }
    & (Join-Path $moved 'Check_Offline.bat') --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Portable application full regression failed.' }
    $portableReport = Get-Content -LiteralPath (Join-Path $moved 'OFFLINE_CHECK.json') -Raw | ConvertFrom-Json
    if (-not $portableReport.logo_locked -or $portableReport.shipped_logo_sha256 -ne $expected) { throw 'Portable startup did not use the fixed embedded logo.' }
    if ($portableReport.radius_limit_km -ne 5000 -or -not $portableReport.compact_numeric_display) { throw 'Portable radius or numeric display regression.' }
    $smoke = Join-Path $Output 'PORTABLE_GUI_SMOKE.json'
    $process = Start-Process -FilePath (Join-Path $moved 'FastViewshed.exe') -ArgumentList ('--smoke-test "'+$smoke+'"') -PassThru
    if (-not $process.WaitForExit(60000)) { Stop-Process -Id $process.Id -Force; throw 'Portable GUI startup timed out.' }
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $smoke)) { throw 'Portable GUI did not start.' }
} finally {
    $installLog = Join-Path $moved 'OFFLINE_INSTALL.log'
    if (Test-Path -LiteralPath $installLog) { Copy-Item -LiteralPath $installLog -Destination (Join-Path $Output 'PORTABLE_INSTALL_v3.5.0.log') -Force }
    foreach ($rule in $rules) { Remove-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue }
    # This is the temporary test copy; the deliverable was already verified.
    if (Test-Path -LiteralPath $moved) { Remove-Item -LiteralPath $moved -Recurse -Force }
}
$installer = Join-Path $delivery 'FastViewshed_With_Logo_Setup.exe'
& (Join-Path $root 'FastViewshed_GUI_Windows\scripts\test_windows_installer.ps1') -Installer $installer -Output $Output -Version '3.5.0'
$report = Get-Content -LiteralPath (Join-Path $Output 'WINDOWS_INSTALLER_VALIDATION.json') -Raw | ConvertFrom-Json
if ($report.status -ne 'passed' -or -not $report.native_gis.logo_locked -or $report.native_gis.shipped_logo_sha256 -ne $expected) { throw 'Installed application did not load the exact fixed embedded logo.' }
@{status='passed';version='3.5.0';private_local_build=$true;complete_portable_files=$true;preextracted_runtime_reused=$true;fast_initialization_check=$true;separate_logo_absent=$true;logo_locked=$true;original_logo_preserved=$true;arbitrary_png_filename=$true;embedded_logo_sha256=$expected;radius_limit_km=5000;compact_numeric_display=$true;portable=$portableReport;windows=$report} |
    ConvertTo-Json -Depth 15 | Set-Content -LiteralPath (Join-Path $Output 'PRIVATE_LOGO_COMPLETE_VALIDATION_v3.5.0.json') -Encoding UTF8
Write-Host 'PASS: full portable files, transfer, cached startup, embedded logo, radius, number display, real installed GUI and uninstall.'
