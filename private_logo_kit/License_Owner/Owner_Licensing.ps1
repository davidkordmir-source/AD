param([switch]$Initialize, [string]$RequestFile, [string]$Customer,
      [ValidateRange(1,36500)][int]$Days=10, [switch]$Unlimited,
      [string]$OutputFile, [string]$DataDirectory)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security
if (-not $DataDirectory) { $DataDirectory = Join-Path (Split-Path $PSScriptRoot -Parent) 'License_OwnerData' }
$privatePath = Join-Path $DataDirectory 'Private_Key.dpapi'
$publicPath = Join-Path $DataDirectory 'public_key.json'

function Get-KeyId($Key) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::ASCII.GetBytes($Key.modulus + ':' + $Key.exponent)))).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Open-SigningKey {
    $csp = New-Object Security.Cryptography.CspParameters
    $csp.ProviderType = 24
    $rsa = New-Object Security.Cryptography.RSACryptoServiceProvider(3072, $csp)
    $rsa.PersistKeyInCsp = $false
    if ((Test-Path -LiteralPath $privatePath) -or (Test-Path -LiteralPath $publicPath)) {
        if (-not ((Test-Path -LiteralPath $privatePath) -and (Test-Path -LiteralPath $publicPath))) { throw 'Owner keys are incomplete. Restore your original License_OwnerData backup. Do not generate a different key for existing customers.' }
        try {
            $private = [Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($privatePath), $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
            $rsa.FromXmlString([Text.Encoding]::UTF8.GetString($private))
        } catch { $rsa.Dispose(); throw 'The owner signing key can only be opened by its original Windows account. Restore that account and its key backup.' }
    } else {
        New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
        $private = [Text.Encoding]::UTF8.GetBytes($rsa.ToXmlString($true))
        $protected = [Security.Cryptography.ProtectedData]::Protect($private, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
        [IO.File]::WriteAllBytes($privatePath, $protected)
        $parameters = $rsa.ExportParameters($false)
        $public = @{version=1;product='FastViewshed';algorithm='RSA3072-SHA256';modulus=[Convert]::ToBase64String($parameters.Modulus);exponent=[Convert]::ToBase64String($parameters.Exponent)}
        [IO.File]::WriteAllText($publicPath, ($public | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    }
    return $rsa
}

function New-LicenseFile([string]$Request, [string]$Name, [int]$Duration, [bool]$Forever, [string]$Target) {
    $Name = $Name.Trim()
    if ($Name.Length -lt 1 -or $Name.Length -gt 160) { throw 'Enter a customer name (1 to 160 characters).' }
    if (-not (Test-Path -LiteralPath $Request -PathType Leaf) -or (Get-Item -LiteralPath $Request).Length -gt 32768) { throw 'Select a valid .fvrequest file from the customer computer.' }
    $requestData = Get-Content -LiteralPath $Request -Raw -Encoding UTF8 | ConvertFrom-Json
    $public = Get-Content -LiteralPath $publicPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $keyId = Get-KeyId $public
    if ($requestData.product -cne 'FastViewshed' -or $requestData.version -ne 1 -or $requestData.device_id -cnotmatch '^[0-9a-f]{64}$' -or $requestData.key_id -cne $keyId) { throw 'This request belongs to another owner key or is not a valid device request. Use the same License_OwnerData that built the customer application.' }
    $rsa = Open-SigningKey
    try {
        $now = [DateTime]::UtcNow
        $epoch = [DateTime]::SpecifyKind([DateTime]'1970-01-01', [DateTimeKind]::Utc)
        $issued = [long][Math]::Floor(($now - $epoch).TotalSeconds)
        $expires = $null
        if (-not $Forever) { $expires = $issued + [long]$Duration * 86400 }
        $payload = @{version=1;product='FastViewshed';key_id=$keyId;device_id=$requestData.device_id;customer=$Name;license_id=[guid]::NewGuid().ToString('N');issued_at=$issued;expires_at=$expires}
        $raw = [Text.Encoding]::UTF8.GetBytes(($payload | ConvertTo-Json -Compress -Depth 5))
        $signature = $rsa.SignData($raw, [Security.Cryptography.CryptoConfig]::MapNameToOID('SHA256'))
        $document = @{payload=[Convert]::ToBase64String($raw);signature=[Convert]::ToBase64String($signature)}
        if (-not $Target) {
            $folder = Join-Path $DataDirectory 'Issued_Licenses'
            New-Item -ItemType Directory -Path $folder -Force | Out-Null
            $Target = Join-Path $folder ($payload.license_id + '.fvlicense')
        }
        if (Test-Path -LiteralPath $Target) { throw 'The output file already exists. Choose a new filename to preserve the old license.' }
        [IO.File]::WriteAllText($Target, ($document | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
        return $Target
    } finally { $rsa.Dispose() }
}

try {
    $key = Open-SigningKey
    $key.Dispose()
    if ($Initialize) { Write-Host 'Owner keys ready. Private signing key stays in License_OwnerData, outside Output.'; exit 0 }
    if ($RequestFile) {
        $result = New-LicenseFile $RequestFile $Customer $Days ([bool]$Unlimited) $OutputFile
        Write-Host ('License created: ' + $result)
        exit 0
    }
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [Windows.Forms.Application]::EnableVisualStyles()
    $form = New-Object Windows.Forms.Form
    $form.Text = 'Fast Viewshed - Owner License Issuer'
    $form.ClientSize = New-Object Drawing.Size(650, 390)
    $form.StartPosition = 'CenterScreen'
    $form.BackColor = [Drawing.Color]::FromArgb(12, 27, 43)
    $form.ForeColor = [Drawing.Color]::White
    $form.Font = New-Object Drawing.Font('Segoe UI', 10)
    $layout = New-Object Windows.Forms.TableLayoutPanel
    $layout.Dock = 'Fill'; $layout.Padding = 20; $layout.ColumnCount = 2
    $layout.ColumnStyles.Add((New-Object Windows.Forms.ColumnStyle('Absolute', 165))) | Out-Null
    $layout.ColumnStyles.Add((New-Object Windows.Forms.ColumnStyle('Percent', 100))) | Out-Null
    $form.Controls.Add($layout)
    $title = New-Object Windows.Forms.Label
    $title.Text = 'Issue a device-bound offline license'; $title.AutoSize = $true
    $layout.Controls.Add($title,0,0); $layout.SetColumnSpan($title,2)
    $select = New-Object Windows.Forms.Button
    $select.Text = 'Select request...'; $select.AutoSize = $true
    $requestBox = New-Object Windows.Forms.TextBox; $requestBox.ReadOnly = $true; $requestBox.Dock = 'Fill'
    $layout.Controls.Add($select,0,1); $layout.Controls.Add($requestBox,1,1)
    $nameLabel = New-Object Windows.Forms.Label; $nameLabel.Text = 'Customer name'; $nameLabel.AutoSize = $true
    $nameBox = New-Object Windows.Forms.TextBox; $nameBox.Dock = 'Fill'; $nameBox.MaxLength = 160
    $layout.Controls.Add($nameLabel,0,2); $layout.Controls.Add($nameBox,1,2)
    $daysLabel = New-Object Windows.Forms.Label; $daysLabel.Text = 'Days from issue (UTC)'; $daysLabel.AutoSize = $true
    $daysBox = New-Object Windows.Forms.NumericUpDown; $daysBox.Minimum = 1; $daysBox.Maximum = 36500; $daysBox.Value = 10
    $layout.Controls.Add($daysLabel,0,3); $layout.Controls.Add($daysBox,1,3)
    $forever = New-Object Windows.Forms.CheckBox; $forever.Text = 'Unlimited / no expiry'; $forever.AutoSize = $true
    $forever.Add_CheckedChanged({ $daysBox.Enabled = -not $forever.Checked })
    $layout.Controls.Add($forever,1,4)
    $notice = New-Object Windows.Forms.Label
    $notice.Text = 'Only send the .fvlicense file to the customer. Keep this issuer and License_OwnerData private. Re-importing a license does not restart its duration.'
    $notice.AutoSize = $true; $notice.MaximumSize = New-Object Drawing.Size(590, 100)
    $layout.Controls.Add($notice,0,5); $layout.SetColumnSpan($notice,2)
    $issue = New-Object Windows.Forms.Button; $issue.Text = 'Create license...'; $issue.AutoSize = $true
    $layout.Controls.Add($issue,1,6)
    foreach ($button in @($select,$issue)) { $button.BackColor = [Drawing.Color]::FromArgb(20,117,149); $button.ForeColor = [Drawing.Color]::White; $button.FlatStyle = 'Flat' }
    $select.Add_Click({
        $picker = New-Object Windows.Forms.OpenFileDialog
        try { $picker.Filter = 'Device requests (*.fvrequest)|*.fvrequest'; if ($picker.ShowDialog() -eq 'OK') { $requestBox.Text = $picker.FileName } }
        finally { $picker.Dispose() }
    })
    $issue.Add_Click({
        $picker = New-Object Windows.Forms.SaveFileDialog
        try {
            $picker.Filter = 'Fast Viewshed licenses (*.fvlicense)|*.fvlicense'; $picker.FileName = [guid]::NewGuid().ToString('N') + '.fvlicense'
            if ($picker.ShowDialog() -ne 'OK') { return }
            $result = New-LicenseFile $requestBox.Text $nameBox.Text ([int]$daysBox.Value) $forever.Checked $picker.FileName
            [void][Windows.Forms.MessageBox]::Show(('License created. Send only this file:' + [Environment]::NewLine + $result), 'Success')
        } catch { [void][Windows.Forms.MessageBox]::Show($_.Exception.Message, 'License not created') }
        finally { $picker.Dispose() }
    })
    [void]$form.ShowDialog()
    exit 0
} catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }
