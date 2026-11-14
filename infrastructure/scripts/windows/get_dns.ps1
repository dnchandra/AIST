param(
    [Parameter(Mandatory=$true)]
    [string]$QueryTarget,
    
    [Parameter(Mandatory=$false)]
    [ValidateSet("A", "AAAA", "CNAME", "MX", "PTR", "NS", "TXT", "SOA")]
    [string]$RecordType = "A",
    
    [Parameter(Mandatory=$false)]
    [string]$DnsServer = $null
)

$ErrorActionPreference = 'Stop'

# Function to format output as JSON-like structure for easy parsing
function Write-DNSResult {
    param(
        [string]$Status,
        [string]$Query,
        [string]$Type,
        [string]$Result,
        [string]$DnsServerUsed,
        [string]$ConfiguredDnsServer = "Unknown",
        [string]$ErrorMessage = $null
    )
    
    $output = @{
        status = $Status
        query = $Query
        type = $Type
        result = $Result
        dnsServer = $DnsServerUsed
        configuredDnsServer = $ConfiguredDnsServer
        error = $ErrorMessage
        timestamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    }
    
    Write-Output "DNS_RESULT|$($output | ConvertTo-Json -Compress)"
}

# Function to get DNS server configuration
function Get-DNSConfiguration {
    try {
        $dnsServers = Get-DnsClientServerAddress | Where-Object { 
            $_.InterfaceAlias -notlike '*Loopback*' -and 
            $_.ServerAddresses.Count -gt 0 
        } | Select-Object -First 1
        
        if ($dnsServers -and $dnsServers.ServerAddresses.Count -gt 0) {
            $primaryDNS = $dnsServers.ServerAddresses[0]
            $interfaceAlias = $dnsServers.InterfaceAlias
            Write-Output "DNS_CONFIG|$primaryDNS|$interfaceAlias"
            return $primaryDNS
        } else {
            Write-Output "DNS_CONFIG|System Default|Unknown"
            return "System Default"
        }
    } catch {
        Write-Output "DNS_CONFIG|Unknown|Error"
        return "Unknown"
    }
}

# Try Resolve-DnsName first for robust parsing, fall back to nslookup
function Test-ResolveDnsName {
    param(
        [string]$Name,
        [string]$Type,
        [string]$Server,
        [string]$ConfiguredDns
    )
    try {
        $params = @{ Name = $Name; Type = $Type; ErrorAction = 'Stop' }
        if ($Server) { $params['Server'] = $Server }
        $resp = Resolve-DnsName @params

        $vals = @()
        switch ($Type.ToUpper()) {
            'A'     { $vals = ($resp | Where-Object { $_.Type -eq 'A' } | Select-Object -ExpandProperty IPAddress) }
            'AAAA'  { $vals = ($resp | Where-Object { $_.Type -eq 'AAAA' } | Select-Object -ExpandProperty IPAddress) }
            'CNAME' { $vals = ($resp | Where-Object { $_.Type -eq 'CNAME' } | Select-Object -ExpandProperty NameHost) }
            'MX'    { $vals = ($resp | Where-Object { $_.Type -eq 'MX' } | Select-Object -ExpandProperty NameExchange) }
            'PTR'   { $vals = ($resp | Where-Object { $_.Type -eq 'PTR' } | Select-Object -ExpandProperty NameHost) }
            'NS'    { $vals = ($resp | Where-Object { $_.Type -eq 'NS' } | Select-Object -ExpandProperty NameHost) }
            'TXT'   { $vals = ($resp | Where-Object { $_.Type -eq 'TXT' } | ForEach-Object { ($_.Strings -join ' ') }) }
            'SOA'   { $vals = ($resp | Where-Object { $_.Type -eq 'SOA' } | Select-Object -ExpandProperty PrimaryServer) }
            default { $vals = @() }
        }
        if ($null -ne $vals -and $vals.Count -gt 0) {
            $used = if ($Server) { $Server } else { $ConfiguredDns }
            Write-DNSResult -Status "SUCCESS" -Query $Name -Type $Type -Result ($vals -join ", ") -DnsServerUsed $used -ConfiguredDnsServer $ConfiguredDns
            return $true
        }
        return $false
    } catch {
        return $false
    }
}

# Main DNS resolution logic
try {
    # Get current DNS configuration
    $dnsConfigOutput = Get-DNSConfiguration
    $configuredDnsServer = "Unknown"
    
    if ($dnsConfigOutput -and $dnsConfigOutput.StartsWith("DNS_CONFIG|")) {
        $configParts = $dnsConfigOutput -split '\|'
        if ($configParts.Length -ge 2) {
            $configuredDnsServer = $configParts[1]
        }
        # $configuredInterface is not used, so we skip assigning it
    }
    
    # Prefer Resolve-DnsName; if it cannot produce an answer, fall back to nslookup parsing
    if (Test-ResolveDnsName -Name $QueryTarget -Type $RecordType -Server $DnsServer -ConfiguredDns $configuredDnsServer) {
        return
    }
    
    # Build nslookup command
    $nslookupArgs = @()
    
    # Add record type if not A record
    if ($RecordType -ne "A") {
        $nslookupArgs += "-type=$RecordType"
    }
    
    # Add target query
    $nslookupArgs += $QueryTarget
    
    # Add specific DNS server if provided
    if ($DnsServer) {
        $nslookupArgs += $DnsServer
    }
    
    # Execute nslookup command (fallback)
    $nslookupResult = & nslookup.exe @nslookupArgs 2>&1 | Out-String
    
    # Clean up PowerShell error formatting from the output
    $cleanResult = ""
    $lines = $nslookupResult -split "`n"
    $inCleanOutput = $false
    
    foreach ($line in $lines) {
        # Skip PowerShell error formatting lines
        if ($line -match '^nslookup\.exe\s*:' -or 
            $line -match '^At\s+.*\.ps1:' -or 
            $line -match '^\+\s+' -or 
            $line -match '^CategoryInfo\s*:' -or 
            $line -match '^FullyQualifiedErrorId\s*:') {
            continue
        }
        
        # Start including lines after we see "Server:" which indicates actual nslookup output
        if ($line -match '^Server:\s*' -or $inCleanOutput) {
            $inCleanOutput = $true
            $cleanResult += $line + "`n"
        }
    }
    
    # If we didn't find clean output, use the original (for cases without errors)
    if (-not $inCleanOutput) {
        $cleanResult = $nslookupResult
    }
    
    $lines = $cleanResult -split "`n"
    
    # Parse nslookup output based on record type
    $success = $false
    $resultValue = ""
    $errorMessage = $null
    $actualDnsServer = "Unknown"
    
    # Find the DNS server used in the response
    $serverLine = $lines | Where-Object { $_ -match 'Server:\s*(.+)' }
    if ($serverLine -and $serverLine -match 'Server:\s*(.+)') {
        $actualDnsServer = $matches[1].Trim()
    }
    
    switch ($RecordType.ToUpper()) {
        "A" {
            # Look for IPv4 addresses, but exclude the server address lines
            $ipAddresses = @()
            $serverIP = ""
            $inAnswerSection = $false
            
            # First, identify the DNS server IP to exclude it
            for ($i = 0; $i -lt $lines.Count; $i++) {
                $line = $lines[$i]
                $trimmedLine = $line.Trim()
                
                if ($trimmedLine -match '^Server:\s*' -and ($i + 1) -lt $lines.Count) {
                    $nextLine = $lines[$i + 1].Trim()
                    if ($nextLine -match '^Address:\s*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})') {
                        $serverIP = $matches[1]
                        break
                    }
                }
            }
            
            # Now parse for result addresses, avoiding the server IP
            foreach ($line in $lines) {
                $trimmedLine = $line.Trim()
                
                # Skip empty lines
                if ($trimmedLine -eq "") {
                    continue
                }
                
                # Detect start of answer section
                if ($trimmedLine -match '^(Non-authoritative answer:|Authoritative answer:|Name:\s*)') {
                    $inAnswerSection = $true
                    continue
                }
                
                # Only process IPs in the answer section
                if ($inAnswerSection) {
                    $foundIP = ""
                    
                    # Various IP address patterns in the answer section
                    if ($trimmedLine -match '^Addresses:\s*.*?(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})') {
                        $foundIP = $matches[1]
                    }
                    elseif ($trimmedLine -match '^Address:\s*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})') {
                        $foundIP = $matches[1]
                    }
                    elseif ($trimmedLine -match '^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})$') {
                        $foundIP = $matches[1]
                    }
                    elseif ($trimmedLine -match '^\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})') {
                        $foundIP = $matches[1]
                    }
                    
                    # Add IP if found and it's not the server IP
                    if ($foundIP -ne "" -and $foundIP -ne $serverIP) {
                        $ipAddresses += $foundIP
                    }
                }
            }
            
            if ($ipAddresses.Count -gt 0) {
                $success = $true
                $resultValue = $ipAddresses -join ", "
            } else {
                $errorMessage = "No A records found"
            }
        }
        
        "AAAA" {
            # Look for IPv6 addresses
            $ipv6Lines = $lines | Where-Object { $_ -match 'AAAA IPv6 address = (.+)' }
            if ($ipv6Lines) {
                $ipv6Addresses = @()
                foreach ($line in $ipv6Lines) {
                    if ($line -match 'AAAA IPv6 address = (.+)') {
                        $ipv6Addresses += $matches[1].Trim()
                    }
                }
                if ($ipv6Addresses.Count -gt 0) {
                    $success = $true
                    $resultValue = $ipv6Addresses -join ", "
                }
            } else {
                $errorMessage = "No AAAA records found"
            }
        }
        
        "CNAME" {
            # Look for canonical name
            $cnameLine = $lines | Where-Object { $_ -match 'canonical name = (.+)' }
            if ($cnameLine -and $cnameLine -match 'canonical name = (.+)') {
                $success = $true
                $resultValue = $matches[1].Trim()
            } else {
                $errorMessage = "No CNAME record found"
            }
        }
        
        "MX" {
            # Look for mail exchanger records
            $mxLines = $lines | Where-Object { $_ -match 'mail exchanger = (.+)' }
            if ($mxLines) {
                $mxRecords = @()
                foreach ($line in $mxLines) {
                    if ($line -match 'mail exchanger = (.+)') {
                        $mxRecords += $matches[1].Trim()
                    }
                }
                if ($mxRecords.Count -gt 0) {
                    $success = $true
                    $resultValue = $mxRecords -join "; "
                }
            } else {
                $errorMessage = "No MX records found"
            }
        }
        
        "PTR" {
            # Look for hostname in reverse lookup
            $nameLine = $lines | Where-Object { $_ -match 'Name:\s*(.+)' }
            if ($nameLine -and $nameLine -match 'Name:\s*(.+)') {
                $success = $true
                $resultValue = $matches[1].Trim()
            } else {
                $errorMessage = "No PTR record found"
            }
        }
        
        "NS" {
            # Look for name server records
            $nsLines = $lines | Where-Object { $_ -match 'nameserver = (.+)' }
            if ($nsLines) {
                $nsRecords = @()
                foreach ($line in $nsLines) {
                    if ($line -match 'nameserver = (.+)') {
                        $nsRecords += $matches[1].Trim()
                    }
                }
                if ($nsRecords.Count -gt 0) {
                    $success = $true
                    $resultValue = $nsRecords -join "; "
                }
            } else {
                $errorMessage = "No NS records found"
            }
        }
        
        "TXT" {
            # Look for text records
            $txtLines = $lines | Where-Object { $_ -match '"(.+)"' }
            if ($txtLines) {
                $txtRecords = @()
                foreach ($line in $txtLines) {
                    if ($line -match '"(.+)"') {
                        $txtRecords += $matches[1].Trim()
                    }
                }
                if ($txtRecords.Count -gt 0) {
                    $success = $true
                    $resultValue = $txtRecords -join "; "
                }
            } else {
                $errorMessage = "No TXT records found"
            }
        }
        
        "SOA" {
            # Look for start of authority record
            $soaLine = $lines | Where-Object { $_ -match 'primary name server = (.+)' }
            if ($soaLine -and $soaLine -match 'primary name server = (.+)') {
                $success = $true
                $resultValue = $matches[1].Trim()
            } else {
                $errorMessage = "No SOA record found"
            }
        }
        
        default {
            $errorMessage = "Unsupported record type: $RecordType"
        }
    }
    
    # Check for common error conditions
    if ($cleanResult -match "can't find|Non-existent domain|NXDOMAIN|server can't find") {
        $success = $false
        $errorMessage = "Domain not found"
    } elseif ($cleanResult -match "timeout|no response") {
        $success = $false
        $errorMessage = "DNS query timeout"
    }
    
    # Output the result
    if ($success) {
        Write-DNSResult -Status "SUCCESS" -Query $QueryTarget -Type $RecordType -Result $resultValue -DnsServerUsed $actualDnsServer -ConfiguredDnsServer $configuredDnsServer
    } else {
        Write-DNSResult -Status "ERROR" -Query $QueryTarget -Type $RecordType -Result "" -DnsServerUsed $actualDnsServer -ConfiguredDnsServer $configuredDnsServer -ErrorMessage $errorMessage
    }
    
} catch {
    Write-DNSResult -Status "ERROR" -Query $QueryTarget -Type $RecordType -Result "" -DnsServerUsed "Unknown" -ConfiguredDnsServer $configuredDnsServer -ErrorMessage $_.Exception.Message
}
