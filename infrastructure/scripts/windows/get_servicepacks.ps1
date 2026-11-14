$ErrorActionPreference = 'Stop'

function Format-DateString([object]$value) {
    if ($null -eq $value) { return '' }
    if ($value -is [string]) {
        $id = $value.Trim()
        if ($id.Length -eq 8 -and $id -match '^[0-9]{8}$') {
            try { return ([datetime]::ParseExact($id, 'yyyyMMdd', $null)).ToString('yyyy/MM/dd') } catch { return $id }
        }
        return $id
    }
    if ($value -is [datetime]) { return $value.ToString('yyyy/MM/dd') }
    return ($value | Out-String).Trim()
}

# Get installed software from both 32-bit and 64-bit registry, normalize fields
# Use -Path with both paths so the pipeline applies to the combined result
$software = @(
    Get-ItemProperty -Path "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*", "HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*" -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -and $_.DisplayName -ne '' } |
    ForEach-Object {
        [PSCustomObject]@{
            DisplayName    = ($_.DisplayName    | ForEach-Object { $_ })
            DisplayVersion = ($_.DisplayVersion | ForEach-Object { $_ })
            Publisher      = ($_.Publisher      | ForEach-Object { $_ })
            InstallDate    = (Format-DateString -value $_.InstallDate)
        }
    }
)

# Get all installed hotfixes (service packs/updates), normalize date
$hotfixes = @(Get-HotFix | ForEach-Object {
    [PSCustomObject]@{
        Description = ($_.Description | ForEach-Object { $_ })
        HotFixID    = ($_.HotFixID    | ForEach-Object { $_ })
        InstalledOn = (Format-DateString -value $_.InstalledOn)
    }
})

$result = [PSCustomObject]@{
    InstalledSoftware = $software
    HotFixes          = $hotfixes
}

$result | ConvertTo-Json -Depth 5
