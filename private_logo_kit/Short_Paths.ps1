function New-FVShortPath([string]$Directory) {
    $original = [IO.Path]::GetFullPath($Directory).TrimEnd('\')
    $subst = Join-Path $env:SystemRoot 'System32\subst.exe'
    foreach ($code in (90..68)) {
        $letter = [string][char]$code
        $root = $letter + ':\'
        if (([Environment]::GetLogicalDrives() -contains $root) -or (Get-PSDrive -Name $letter -ErrorAction SilentlyContinue)) { continue }
        & $subst ($letter + ':') $original 2>$null
        if ($LASTEXITCODE -ne 0) { continue }
        $providerCreated = $false
        try {
            if (-not (Get-PSDrive -Name $letter -ErrorAction SilentlyContinue)) {
                New-PSDrive -Name $letter -PSProvider FileSystem -Root $root -Scope Global | Out-Null
                $providerCreated = $true
            }
            if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw 'The temporary short path is unavailable.' }
            return [pscustomobject]@{Root=$root;Letter=$letter;Original=$original;ProviderCreated=$providerCreated}
        } catch {
            if ($providerCreated) { Remove-PSDrive -Name $letter -Scope Global -ErrorAction SilentlyContinue }
            & $subst ($letter + ':') /D 2>$null | Out-Null
            throw
        }
    }
    throw 'No free temporary drive letter is available. Close other local builds and retry.'
}

function Remove-FVShortPath($Mapping) {
    if (-not $Mapping) { return }
    if ($Mapping.ProviderCreated) { Remove-PSDrive -Name $Mapping.Letter -Scope Global -ErrorAction SilentlyContinue }
    & (Join-Path $env:SystemRoot 'System32\subst.exe') ($Mapping.Letter + ':') /D 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Warning ('Unable to release temporary path ' + $Mapping.Root) }
}

function Get-FVPhysicalPath([string]$Path, $Mapping) {
    $absolute = [IO.Path]::GetFullPath($Path)
    if ($Mapping -and $absolute.StartsWith($Mapping.Root, [StringComparison]::OrdinalIgnoreCase)) {
        return Join-Path $Mapping.Original $absolute.Substring($Mapping.Root.Length)
    }
    return $absolute
}
