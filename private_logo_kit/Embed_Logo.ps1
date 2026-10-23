param([Parameter(Mandatory=$true)][string]$Executable, [Parameter(Mandatory=$true)][string]$Logo)
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class FVNativeBranding {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern IntPtr BeginUpdateResource(string name, bool deleteExisting);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool UpdateResource(IntPtr handle, IntPtr type, IntPtr name, ushort language, byte[] data, uint size);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool EndUpdateResource(IntPtr handle, bool discard);
}
'@
$bytes = [IO.File]::ReadAllBytes($Logo)
if ($bytes.Length -gt 32MB) { throw 'The PNG logo must be at most 32 MB.' }
$handle = [FVNativeBranding]::BeginUpdateResource($Executable, $false)
if ($handle -eq [IntPtr]::Zero) { throw (New-Object ComponentModel.Win32Exception) }
$committed = $false
try {
    if (-not [FVNativeBranding]::UpdateResource($handle, [IntPtr]10, [IntPtr]101, 0, $bytes, $bytes.Length)) { throw (New-Object ComponentModel.Win32Exception) }
    if (-not [FVNativeBranding]::EndUpdateResource($handle, $false)) { throw (New-Object ComponentModel.Win32Exception) }
    $committed = $true
} finally {
    if (-not $committed) { [void][FVNativeBranding]::EndUpdateResource($handle, $true) }
}
