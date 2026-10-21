param([string]$Stage, [string]$Output, [string]$Version = '3.3.0')
$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $PSScriptRoot
$stagePath = (Resolve-Path -LiteralPath $Stage).Path
$outputPath = (Resolve-Path -LiteralPath $Output).Path
$csc = Join-Path $env:SystemRoot 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $csc)) { throw 'Windows .NET Framework compiler is missing.' }
& $csc /nologo /target:winexe /platform:x64 "/win32icon:$stagePath\assets\aircraft.ico" "/out:$stagePath\FastViewshed.exe" /reference:System.Windows.Forms.dll (Join-Path $appRoot 'installer\FastViewshedLauncher.cs')
if ($LASTEXITCODE -ne 0) { throw 'Native Windows launcher compilation failed.' }
$iscc = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
if (-not (Test-Path -LiteralPath $iscc)) { throw 'Inno Setup 6 is missing from this Windows build runner.' }
& $iscc "/DStageDir=$stagePath" "/DOutputDir=$outputPath" "/DAppVersion=$Version" (Join-Path $appRoot 'installer\FastViewshed.iss')
if ($LASTEXITCODE -ne 0) { throw 'Windows installer compilation failed.' }
