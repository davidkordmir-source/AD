param([Parameter(Mandatory=$true)][string]$Archive, [Parameter(Mandatory=$true)][string]$Output, [string]$PathFix)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$testRoot = Join-Path $env:RUNNER_TEMP ('Complete private kit long download path ' + ('x' * 40) + ' ' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
Expand-Archive -LiteralPath $Archive -DestinationPath $testRoot
$kit = Join-Path $testRoot 'FastViewshed_Private_Logo_Kit'
$builder = Join-Path $kit 'Build_Custom_Setup.ps1'
$shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
. (Join-Path $PSScriptRoot 'Short_Paths.ps1')
# The runner is disposable and already uses admin-only firewall tests below.
# User-facing build/update scripts never change the registry or request elevation.
$registry = 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem'
$longPathsBefore = (Get-ItemProperty -LiteralPath $registry -Name LongPathsEnabled).LongPathsEnabled
$reserved = $null
try {
Set-ItemProperty -LiteralPath $registry -Name LongPathsEnabled -Value 0
if ((Get-ItemProperty -LiteralPath $registry -Name LongPathsEnabled).LongPathsEnabled -ne 0) { throw 'Legacy long-path restriction was not enabled for this regression.' }
$reserved = New-FVShortPath -Directory $testRoot
$mappingsBefore = (& (Join-Path $env:SystemRoot 'System32\subst.exe')) -join "`n"
if ($PathFix) {
    Expand-Archive -LiteralPath $PathFix -DestinationPath $kit -Force
    $sentinel = Join-Path $kit 'Logo_Input\preserve-local-input.txt'
    $previousOutput = Join-Path $kit 'Output\preserve-previous-output.txt'
    [IO.File]::WriteAllText($sentinel, 'Private user input must remain untouched.')
    [IO.File]::WriteAllText($previousOutput, 'Previous output must remain untouched.')
    foreach ($attempt in 1..2) {
        & $shell -NoProfile -STA -ExecutionPolicy Bypass -File (Join-Path $kit 'Apply_Path_Fix.ps1') 2>&1 | Tee-Object -FilePath (Join-Path $Output ('APPLY_PATH_FIX_' + $attempt + '.log'))
        if ($LASTEXITCODE -ne 0) { throw ('Applying the small updater failed, attempt ' + $attempt) }
    }
    if ([IO.File]::ReadAllText($sentinel) -ne 'Private user input must remain untouched.' -or [IO.File]::ReadAllText($previousOutput) -ne 'Previous output must remain untouched.') { throw 'Updater changed user input or previous output.' }
    $builderBytes = [IO.File]::ReadAllBytes($builder)
    try {
        [IO.File]::AppendAllText($builder, "`n# Deliberately changed local file")
        $changedHash = (Get-FileHash -LiteralPath $builder).Hash
        & $shell -NoProfile -STA -ExecutionPolicy Bypass -File (Join-Path $kit 'Apply_Path_Fix.ps1') 2>&1 | Tee-Object -FilePath (Join-Path $Output 'MODIFIED_KIT_REJECTED.log')
        if ($LASTEXITCODE -eq 0 -or (Get-FileHash -LiteralPath $builder).Hash -ne $changedHash) { throw 'Updater failed to reject or preserve a modified kit file.' }
    } finally { [IO.File]::WriteAllBytes($builder, $builderBytes) }
}
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
if (((& (Join-Path $env:SystemRoot 'System32\subst.exe')) -join "`n") -ne $mappingsBefore) { throw 'A builder or updater leaked a mapping or changed an existing mapping.' }
} finally {
    Set-ItemProperty -LiteralPath $registry -Name LongPathsEnabled -Value $longPathsBefore
    if ($reserved) { Remove-FVShortPath -Mapping $reserved }
}
if ((Get-FileHash -LiteralPath $logo -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'The original user logo was modified.' }
$delivery = Join-Path $kit 'Output'
$portable = Join-Path $delivery 'Portable'
foreach ($name in @('FastViewshed.exe','FastViewshed_GUI.py','desktop_customization.py','runtime_win64.zip','runtime_offline\python.exe','runtime_offline\pythonw.exe','runtime_offline\Lib\site-packages\osgeo\gdal.py','assets\default_map\area.shp')) {
    if (-not (Test-Path -LiteralPath (Join-Path $portable $name))) { throw ('Incomplete portable output: ' + $name) }
}
$deepFile = Join-Path $portable 'runtime_offline\Lib\site-packages\numpy\f2py\tests\src\modules\gh26920\two_mods_with_no_public_entities.f90'
if ($deepFile.Length -le 260 -or -not [IO.File]::Exists($deepFile)) { throw 'The exact long-path NumPy regression file was not produced.' }
if (@(Get-ChildItem -LiteralPath $kit -Directory -Filter '_Build_*').Count -ne 0) { throw 'Temporary build files were not cleaned up.' }
if ($PathFix) {
    $savedOutputs = @(Get-ChildItem -LiteralPath $kit -Directory -Filter 'Output.previous.*')
    if ($savedOutputs.Count -ne 1 -or -not (Test-Path -LiteralPath (Join-Path $savedOutputs[0].FullName 'preserve-previous-output.txt'))) { throw 'Rebuilding did not preserve the previous Output.' }
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
@{status='passed';version='3.5.0';builder_version='3.5.1';long_paths_disabled_during_build=$true;longest_regression_file=$deepFile.Length;existing_mapping_preserved=$true;temporary_mappings_released=$true;temporary_build_files_removed=$true;small_updater_tested=[bool]$PathFix;private_local_build=$true;complete_portable_files=$true;preextracted_runtime_reused=$true;fast_initialization_check=$true;separate_logo_absent=$true;logo_locked=$true;original_logo_preserved=$true;arbitrary_png_filename=$true;embedded_logo_sha256=$expected;radius_limit_km=5000;compact_numeric_display=$true;portable=$portableReport;windows=$report} |
    ConvertTo-Json -Depth 15 | Set-Content -LiteralPath (Join-Path $Output 'PRIVATE_LONG_PATH_VALIDATION_v3.5.1.json') -Encoding UTF8
Write-Host 'PASS: full portable files, transfer, cached startup, embedded logo, radius, number display, real installed GUI and uninstall.'
# Only the isolated test copy is removed; updater/build scripts preserve user files.
Remove-Item -LiteralPath $testRoot -Recurse -Force
