param(
    [Parameter(Mandatory=$true)]
    [string]$P
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# Ensure $P does not include a leading 'Registry::' to avoid duplicate provider prefix
if ($P -like 'Registry::*') { $P = $P -replace '^Registry::', '' }

# Build candidate paths to be tolerant with Wow6432Node differences
$candidates = @($P)
if ($P -match '\\Wow6432Node\\') {
    $candidates += ($P -replace '\\Wow6432Node\\', '\\')
} else {
    # If path starts with HKEY_LOCAL_MACHINE\SOFTWARE, try inserting Wow6432Node
    if ($P -match '^(HKEY_LOCAL_MACHINE|HKLM)\\SOFTWARE\\') {
        $candidates += ($P -replace '^(HKEY_LOCAL_MACHINE|HKLM)\\SOFTWARE', 'HKEY_LOCAL_MACHINE\\SOFTWARE\\Wow6432Node')
    }
}

$found = $null
foreach ($c in $candidates) {
    try {
        if (Test-Path -LiteralPath ('Registry::' + $c)) { $found = $c; break }
    } catch { }
}

if ($null -eq $found) {
    Write-Output ("ERROR: Cannot find path 'Registry::" + $P + "' because it does not exist.")
    exit 0
}

try {
    $k = Get-Item -LiteralPath ('Registry::' + $found) -ErrorAction Stop;
    $out = 'Registry Path: Registry::' + $found + "`n----------------------------------------";
    $dv = $k.GetValue('');
    if ($null -ne $dv) {
        $out += "`n(Default)`t$($k.GetValueKind(''))`t$($dv)";
    } else {
        $out += "`n(Default)`t`t";
    }
    $names = $k.GetValueNames();
    $hasVals = $false;
    foreach ($n in $names) {
        if ($n -ne '') {
            $out += "`n$($n)`t$($k.GetValueKind($n))`t$($k.GetValue($n))";
            $hasVals = $true;
        }
    }
    if (-not $hasVals) {
        $subs = $k.GetSubKeyNames();
        if ($subs.Count -gt 0) {
            $out += "`n--- Subkeys (folders) ---";
            foreach ($s in $subs) { $out += "`n" + $s }
        }
    }
    Write-Output $out
} catch {
    Write-Output ("ERROR: " + $_.Exception.Message)
}
