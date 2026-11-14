# get_certificates.ps1
# Enumerate certificates from several common stores and output JSON array of objects
# Each object: Subject, Issuer, Thumbprint, Store, NotBefore, NotAfter, Valid

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function CertToObj($c, $storeName) {
    # Extract CN from Subject
    $cn = ''
    if ($c.Subject) {
        $m = [regex]::Match($c.Subject, 'CN=([^,;]+)')
        if ($m.Success) { $cn = $m.Groups[1].Value.Trim() }
    }

    return [PSCustomObject]@{
    Subject = $c.Subject
    IssuedTo = $cn
    IssuedBy = $c.Issuer
        Thumbprint = $c.Thumbprint
        SerialNumber = $c.GetSerialNumberString()
        Store = $storeName
        NotBefore = $c.NotBefore.ToString('yyyy-MM-ddTHH:mm:ss')
        NotAfter = $c.NotAfter.ToString('yyyy-MM-ddTHH:mm:ss')
        Valid = ($c.NotAfter -gt (Get-Date)) -and ($c.NotBefore -lt (Get-Date))
    }
}

$stores = @(
    @{Machine = $true; Name = 'LocalMachine\My'},
    @{Machine = $true; Name = 'LocalMachine\Root'},
    @{Machine = $true; Name = 'LocalMachine\CA'},
    @{Machine = $false; Name = 'CurrentUser\My'},
    @{Machine = $false; Name = 'CurrentUser\Root'},
    @{Machine = $false; Name = 'CurrentUser\CA'}
)

$out = @()
foreach ($s in $stores) {
    try {
    $storeParts = $s.Name -split '\\', 2
    $name = $storeParts[1]
        $cs = New-Object System.Security.Cryptography.X509Certificates.X509Store($name, ([System.Security.Cryptography.X509Certificates.StoreLocation]::LocalMachine))
        if (-not $s.Machine) {
            $cs = New-Object System.Security.Cryptography.X509Certificates.X509Store($name, ([System.Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser))
        }
        $cs.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadOnly)
        foreach ($c in $cs.Certificates) {
            $obj = CertToObj $c ($s.Name)
            $out += $obj
        }
        $cs.Close()
    } catch {
        # ignore individual store errors
    }
}

# Convert Valid boolean to true/false and output as JSON array
$out | ConvertTo-Json -Depth 3
