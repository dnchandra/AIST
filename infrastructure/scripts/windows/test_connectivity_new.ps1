param(
    [Parameter(Mandatory=$true)]
    [string]$target,
    [Parameter(Mandatory=$true)]
    [ValidateRange(1,65535)]
    [int]$port
)

# ---- quick ICMP reachability (fast timeout) ----
$icmpReachable = $false
$latency = 'N/A'
try {
    $p = Test-Connection -ComputerName $target -Count 1 -TimeoutSeconds 2 | Select-Object -First 1
    if ($p -and $null -ne $p.ResponseTime) {
        $icmpReachable = $true
        $latency = ("{0}ms" -f [math]::Round($p.ResponseTime))
    }
} catch { }

function Test-PortState {
    param(
        [string]$ComputerName,
        [int]$Port,
        [int]$Timeout = 3000
    )

    $tcpClient = $null
    try {
        $tcpClient = New-Object System.Net.Sockets.TcpClient
        # Kick off async connect + timeout race
        $connectTask = $tcpClient.ConnectAsync($ComputerName, $Port)
        $timeoutTask = [System.Threading.Tasks.Task]::Delay($Timeout)
        $completed = [System.Threading.Tasks.Task]::WhenAny($connectTask, $timeoutTask).Result

        if ($completed -eq $connectTask) {
            if ($tcpClient.Connected) {
                $tcpClient.Close()
                return @{ State='open';      Connected=$true;  Error=$null }
            } else {
                return @{ State='refused';   Connected=$false; Error='Connection refused' }
            }
        } else {
            # Timeout → likely filtered/dropped
            $tcpClient.Close()
            return @{ State='filtered'; Connected=$false; Error='Connection timeout' }
        }
    } catch [System.Net.Sockets.SocketException] {
        if ($tcpClient) { $tcpClient.Close() }
        switch ($_.Exception.SocketErrorCode) {
            'ConnectionRefused'  { return @{ State='refused';     Connected=$false; Error='Port refused' } }
            'TimedOut'           { return @{ State='filtered';    Connected=$false; Error='Connection timeout' } }
            'HostUnreachable'    { return @{ State='unreachable'; Connected=$false; Error='Host unreachable' } }
            'NetworkUnreachable' { return @{ State='unreachable'; Connected=$false; Error='Network unreachable' } }
            default              { return @{ State='filtered';    Connected=$false; Error='Connection failed' } }
        }
    } catch {
        if ($tcpClient) { $tcpClient.Close() }
        return @{ State='unreachable'; Connected=$false; Error='Connection error' }
    }
}

# ---- test TCP port with detailed classification ----
$portState = Test-PortState -ComputerName $target -Port $port

# ---- source IP (best-effort) ----
$sourceIP = 'Unknown'
try {
    $addr = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
            Select-Object -First 1
    if ($addr) { $sourceIP = $addr.IPAddress }
} catch { }

# ---- remote address (fast DNS resolution only) ----
$remoteAddress = 'N/A'
try {
    # Fast DNS resolution without Test-NetConnection
    $resolved = [System.Net.Dns]::GetHostAddresses($target) | Where-Object { $_.AddressFamily -eq 'InterNetwork' } | Select-Object -First 1
    if ($resolved) {
        $remoteAddress = $resolved.IPAddressToString
    } else {
        # If target is already an IP, use it directly
        [void][System.Net.IPAddress]::Parse($target)
        $remoteAddress = $target
    }
} catch {
    try {
        # If target is already an IP, use it directly
        [void][System.Net.IPAddress]::Parse($target)
        $remoteAddress = $target
    } catch {
        $remoteAddress = 'N/A'
    }
}

# ---- compose result ----
$resultMsg = switch ($portState.State) {
    'open'         { "Port $port is OPEN on $target" }
    'refused'      { "Port $port is REFUSED on $target" }
    'filtered'     { "Port $port is FILTERED on $target" }
    'unreachable'  { "Connection to $target on port $port FAILED" }
    default        { "Connection state unknown for ${target}:$port" }
}

$output = [ordered]@{
    success       = $portState.Connected
    partial       = (-not $portState.Connected) -and $icmpReachable
    target        = $target
    port          = $port
    result        = $resultMsg
    remoteAddress = $remoteAddress
    latency       = $latency
    sourceIP      = $sourceIP
    error         = $portState.Error
    portState     = $portState.State     # open | refused | filtered | unreachable
    timestamp     = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
}

"CONNECTIVITY_RESULT|$($output | ConvertTo-Json -Compress)"
