param([string]$Installer, [string]$Output)
$ErrorActionPreference = 'Stop'
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$outputPath = (Resolve-Path -LiteralPath $Output).Path
$installed = Join-Path $env:RUNNER_TEMP 'Fast Viewshed installed with spaces'
$reportPath = Join-Path $outputPath 'WINDOWS_INSTALLER_VALIDATION.json'
$rules = @('FastViewshed-installed-python', 'FastViewshed-installed-pythonw')
try {
    Set-NetFirewallProfile -Profile Domain,Private,Public -Enabled True
    New-NetFirewallRule -DisplayName $rules[0] -Direction Outbound -Action Block -Program (Join-Path $installed 'runtime_offline\python.exe') -Profile Any | Out-Null
    New-NetFirewallRule -DisplayName $rules[1] -Direction Outbound -Action Block -Program (Join-Path $installed 'runtime_offline\pythonw.exe') -Profile Any | Out-Null
    $arguments = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',('/DIR="'+$installed+'"'),('/LOG="'+(Join-Path $outputPath 'SETUP_TEST.log')+'"'))
    $process = Start-Process -FilePath $installerPath -ArgumentList $arguments -PassThru
    if (-not $process.WaitForExit(300000)) { Stop-Process -Id $process.Id -Force; throw 'Setup timed out.' }
    if ($process.ExitCode -ne 0) { throw ('Installer failed with code '+$process.ExitCode) }
    $link = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Fast Viewshed.lnk'
    if (-not (Test-Path -LiteralPath $link)) { throw 'Desktop shortcut was not created.' }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($link)
    if ($shortcut.TargetPath -ne (Join-Path $installed 'FastViewshed.exe')) { throw 'Desktop target mismatch.' }
    if ($shortcut.IconLocation -notlike '*aircraft.ico*') { throw 'Aircraft shortcut icon is missing.' }
    $smoke = Join-Path $outputPath 'INSTALLED_GUI_SMOKE.json'
    $launch = Start-Process -FilePath (Join-Path $installed 'FastViewshed.exe') -ArgumentList ('--smoke-test "'+$smoke+'"') -PassThru
    if (-not $launch.WaitForExit(60000)) { Stop-Process -Id $launch.Id -Force; throw 'Installed application launch timed out.' }
    if ($launch.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $smoke)) { throw 'Installed GUI did not open.' }
    $gui = Get-Content -LiteralPath $smoke -Raw | ConvertFrom-Json
    if (-not $gui.icon_loaded -or $gui.offline_map_countries -lt 200 -or $gui.highlighted_groups -ne 3) { throw 'Installed GUI assets or sections are missing.' }
    $native = Get-Content -LiteralPath (Join-Path $installed 'OFFLINE_CHECK.json') -Raw | ConvertFrom-Json
    if ($native.status -ne 'passed') { throw 'Installed runtime verification failed.' }
    $uninstall = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' | Where-Object { $_.DisplayName -like 'Fast Viewshed*' }
    if (-not $uninstall) { throw 'Windows uninstall registration is missing.' }
    $uninstaller = Join-Path $installed 'unins000.exe'
    $remove = Start-Process -FilePath $uninstaller -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART' -PassThru
    if (-not $remove.WaitForExit(120000)) { throw 'Uninstall timed out.' }
    if ($remove.ExitCode -ne 0 -or (Test-Path -LiteralPath $link)) { throw 'Uninstall did not remove the shortcut.' }
    $report = @{status='passed';version='3.3.0';offline=$true;firewall_blocked=$true;desktop_shortcut=$true;aircraft_icon=$true;installed_gui=$gui;native_gis=$native;uninstall_registered=$true;uninstall_tested=$true;per_user_install=$true}
    $report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $reportPath -Encoding UTF8
} catch {
    $details = $_.ToString()
    foreach ($file in @((Join-Path $outputPath 'SETUP_TEST.log'), (Join-Path $installed 'OFFLINE_INSTALL.log'))) {
        if (Test-Path -LiteralPath $file) { $details += "`n"+(Get-Content -LiteralPath $file -Tail 60 | Out-String) }
    }
    $escaped = $details.Replace('%','%25').Replace("`r",'%0D').Replace("`n",'%0A')
    Write-Output "::error title=Windows installer test details::$escaped"
    throw
} finally {
    foreach ($rule in $rules) { Remove-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue }
}
