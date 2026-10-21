param([Parameter(Mandatory=$true)][string]$Archive, [Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference = 'Stop'
$archivePath = (Resolve-Path -LiteralPath $Archive).Path
$outputPath = (Resolve-Path -LiteralPath $Output).Path
$testRoot = Join-Path $env:RUNNER_TEMP 'Offline verification with spaces'
if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
& tar.exe -xf $archivePath -C $testRoot
if ($LASTEXITCODE -ne 0) { throw 'Application ZIP extraction failed.' }
$appRoot = Join-Path $testRoot 'FastViewshed_Offline_Windows_x64'
$runtimePath = Join-Path $appRoot 'runtime_offline'
$ruleNames = @('FastViewshed-offline-python', 'FastViewshed-offline-pythonw')
try {
    # Windows Firewall blocks native GIS libraries too, not just Python sockets.
    Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled True
    New-NetFirewallRule -DisplayName $ruleNames[0] -Direction Outbound -Action Block -Program (Join-Path $runtimePath 'python.exe') -Profile Any | Out-Null
    New-NetFirewallRule -DisplayName $ruleNames[1] -Direction Outbound -Action Block -Program (Join-Path $runtimePath 'pythonw.exe') -Profile Any | Out-Null
    & (Join-Path $appRoot 'Install_Fast_Viewshed.bat') --quiet 2>&1 | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { throw 'Offline installation or GUI verification failed.' }
    $report = Get-Content -LiteralPath (Join-Path $appRoot 'OFFLINE_CHECK.json') -Raw | ConvertFrom-Json
    if ($report.status -ne 'passed') { throw 'Offline runtime did not pass.' }
    $report | Add-Member -NotePropertyName windows_firewall_outbound_blocked -NotePropertyValue $true
    $report | Add-Member -NotePropertyName tested_os -NotePropertyValue (Get-CimInstance Win32_OperatingSystem).Caption
    $report | Add-Member -NotePropertyName install_path_contains_spaces -NotePropertyValue $true
    $report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $outputPath 'WINDOWS_OFFLINE_VALIDATION.json') -Encoding UTF8
    # A second invocation checks the installed marker and requires no package manager.
    & (Join-Path $appRoot 'Install_Fast_Viewshed.bat') --quiet 2>&1 | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { throw 'Repeated offline initialization failed.' }
} finally {
    foreach ($name in $ruleNames) { Remove-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue }
}
