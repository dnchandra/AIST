# Windows Native Prometheus Exporter for AIST Enterprise
# Port: 9182 (Standard Prometheus windows_exporter port)
param (
    [int]$Port = 9182
)

$listener = New-Object System.Net.HttpListener
$prefix = "http://+:$Port/"
$listener.Prefixes.Add($prefix)

try {
    $listener.Start()
    Write-Output "AIST Windows Exporter started on port $Port"
} catch {
    Write-Error "Failed to start listener: $_"
    exit 1
}

function Get-MetricsText {
    $sb = New-Object System.Text.StringBuilder

    [void]$sb.AppendLine("# HELP windows_exporter_build_info AIST Enterprise Windows Exporter build information.")
    [void]$sb.AppendLine("# TYPE windows_exporter_build_info gauge")
    [void]$sb.AppendLine('windows_exporter_build_info{version="0.30.0-aist",arch="amd64",os="windows"} 1')

    # 1. System Uptime & OS Metrics
    try {
        $os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
        if ($os) {
            $uptimeSeconds = [math]::Round(((Get-Date) - $os.LastBootUpTime).TotalSeconds)
            $totalMemBytes = [int64]$os.TotalVisibleMemorySize * 1024
            $freeMemBytes = [int64]$os.FreePhysicalMemory * 1024
            $usedMemBytes = $totalMemBytes - $freeMemBytes
            $memRatio = if ($totalMemBytes -gt 0) { [math]::Round(($usedMemBytes / $totalMemBytes), 4) } else { 0 }

            [void]$sb.AppendLine("# HELP windows_system_system_up_time System uptime in seconds.")
            [void]$sb.AppendLine("# TYPE windows_system_system_up_time gauge")
            [void]$sb.AppendLine("windows_system_system_up_time $uptimeSeconds")

            [void]$sb.AppendLine("# HELP windows_cs_physical_memory_bytes Total physical memory in bytes.")
            [void]$sb.AppendLine("# TYPE windows_cs_physical_memory_bytes gauge")
            [void]$sb.AppendLine("windows_cs_physical_memory_bytes $totalMemBytes")

            [void]$sb.AppendLine("# HELP windows_os_physical_memory_free_bytes Free physical memory in bytes.")
            [void]$sb.AppendLine("# TYPE windows_os_physical_memory_free_bytes gauge")
            [void]$sb.AppendLine("windows_os_physical_memory_free_bytes $freeMemBytes")

            [void]$sb.AppendLine("# HELP windows_os_memory_usage_ratio Physical memory usage ratio (0.0 to 1.0).")
            [void]$sb.AppendLine("# TYPE windows_os_memory_usage_ratio gauge")
            [void]$sb.AppendLine("windows_os_memory_usage_ratio $memRatio")
        }
    } catch {}

    # 2. CPU Utilization
    try {
        $cpu = Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue | Measure-Object -Property LoadPercentage -Average
        if ($cpu -and $cpu.Average -ne $null) {
            [void]$sb.AppendLine("# HELP windows_cpu_load_percentage Overall CPU load percentage.")
            [void]$sb.AppendLine("# TYPE windows_cpu_load_percentage gauge")
            [void]$sb.AppendLine("windows_cpu_load_percentage $($cpu.Average)")
        }
    } catch {}

    # 3. Logical Disks
    try {
        $disks = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" -ErrorAction SilentlyContinue
        if ($disks) {
            [void]$sb.AppendLine("# HELP windows_logical_disk_free_bytes Free space in bytes on disk volume.")
            [void]$sb.AppendLine("# TYPE windows_logical_disk_free_bytes gauge")
            [void]$sb.AppendLine("# HELP windows_logical_disk_size_bytes Total capacity in bytes on disk volume.")
            [void]$sb.AppendLine("# TYPE windows_logical_disk_size_bytes gauge")
            foreach ($d in $disks) {
                $vol = $d.DeviceID
                $free = [int64]$d.FreeSpace
                $size = [int64]$d.Size
                [void]$sb.AppendLine("windows_logical_disk_free_bytes{volume=`"$vol`"} $free")
                [void]$sb.AppendLine("windows_logical_disk_size_bytes{volume=`"$vol`"} $size")
            }
        }
    } catch {}

    # 4. Critical Windows Services & Custom Microservices Status
    try {
        $targetServices = @(
            "WinRM", "LanmanServer", "EventLog", "Schedule", 
            "TermService", "Dnscache", "Dhcp", "W32Time", 
            "Spooler", "wuauserv", "MSSQLSERVER", "W3SVC", "VGAuthService"
        )
        $allServices = Get-Service -ErrorAction SilentlyContinue

        [void]$sb.AppendLine("# HELP windows_service_state Windows service state (1=active, 0=inactive).")
        [void]$sb.AppendLine("# TYPE windows_service_state gauge")
        [void]$sb.AppendLine("# HELP windows_service_status Windows service health status.")
        [void]$sb.AppendLine("# TYPE windows_service_status gauge")

        # 4A. System Services
        foreach ($name in $targetServices) {
            $svc = $allServices | Where-Object { $_.Name -eq $name }
            if ($svc) {
                $isRunning = if ($svc.Status -eq "Running") { 1 } else { 0 }
                $isStopped = if ($svc.Status -eq "Stopped") { 1 } else { 0 }

                [void]$sb.AppendLine("windows_service_state{name=`"$name`",state=`"running`"} $isRunning")
                [void]$sb.AppendLine("windows_service_state{name=`"$name`",state=`"stopped`"} $isStopped")
                [void]$sb.AppendLine("windows_service_status{name=`"$name`",status=`"ok`"} $isRunning")
            } else {
                [void]$sb.AppendLine("windows_service_state{name=`"$name`",state=`"not_found`"} 1")
                [void]$sb.AppendLine("windows_service_state{name=`"$name`",state=`"running`"} 0")
            }
        }

        # 4B. Microservice Daemons assigned specifically to this node
        $potentialServices = @(
            @{ Name = "AuthGateway";  Port = 5001; Path = "C:\AIST\AuthGateway\server.ps1" },
            @{ Name = "AuditService"; Port = 8088; Path = "C:\AIST\AuditService\server.ps1" },
            @{ Name = "LoanPortal";   Port = 3000; Path = "C:\AIST\LoanPortal\server.ps1" }
        )

        foreach ($ms in $potentialServices) {
            # Only monitor and export metrics for services provisioned on this specific node
            if (Test-Path $ms.Path) {
                $msName = $ms.Name
                $msPort = $ms.Port
                $isListening = 0
                try {
                    $proc = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*$msName*" }
                    if ($proc) {
                        $isListening = 1
                    } else {
                        $conn = Get-NetTCPConnection -LocalPort $msPort -State Listen -ErrorAction SilentlyContinue
                        if ($conn) { $isListening = 1 }
                    }
                } catch {}

                $isStopped = if ($isListening -eq 1) { 0 } else { 1 }
                [void]$sb.AppendLine("windows_service_state{name=`"$msName`",state=`"running`"} $isListening")
                [void]$sb.AppendLine("windows_service_state{name=`"$msName`",state=`"stopped`"} $isStopped")
                [void]$sb.AppendLine("windows_service_status{name=`"$msName`",status=`"ok`"} $isListening")
            }
        }
    } catch {}

    # 5. Process Working Sets for Microservices
    try {
        $procs = Get-Process -ErrorAction SilentlyContinue | Where-Object { 
            $_.ProcessName -match "powershell|dotnet|sqlservr|w3wp|node|python" 
        }
        if ($procs) {
            [void]$sb.AppendLine("# HELP windows_process_working_set_bytes Process physical memory working set.")
            [void]$sb.AppendLine("# TYPE windows_process_working_set_bytes gauge")
            foreach ($p in $procs) {
                $pname = $p.ProcessName
                $pidNum = $p.Id
                $ws = [int64]$p.WorkingSet64
                [void]$sb.AppendLine("windows_process_working_set_bytes{process=`"$pname`",pid=`"$pidNum`"} $ws")
            }
        }
    } catch {}

    return $sb.ToString()
}

$cachedMetrics = ""
$lastCacheTime = [DateTime]::MinValue

function Get-CachedMetricsText {
    $now = [DateTime]::UtcNow
    if (($now - $global:lastCacheTime).TotalSeconds -lt 4 -and -not [string]::IsNullOrEmpty($global:cachedMetrics)) {
        return $global:cachedMetrics
    }
    $global:cachedMetrics = (Get-MetricsText) -replace "`r`n", "`n"
    $global:lastCacheTime = [DateTime]::UtcNow
    return $global:cachedMetrics
}

while ($listener.IsListening) {
    try {
        $context = $listener.GetContext()
        $request = $context.Request
        $response = $context.Response

        if ($request.Url.AbsolutePath -eq "/metrics" -or $request.Url.AbsolutePath -eq "/") {
            $metrics = Get-CachedMetricsText
            $buffer = [System.Text.Encoding]::UTF8.GetBytes($metrics)
            $response.ContentType = "text/plain; version=0.0.4; charset=utf-8"
            $response.ContentLength64 = $buffer.Length
            $response.StatusCode = 200
            $response.OutputStream.Write($buffer, 0, $buffer.Length)
        } elseif ($request.Url.AbsolutePath -eq "/health") {
            $buffer = [System.Text.Encoding]::UTF8.GetBytes('{"status":"UP","role":"windows_exporter"}')
            $response.ContentType = "application/json"
            $response.ContentLength64 = $buffer.Length
            $response.StatusCode = 200
            $response.OutputStream.Write($buffer, 0, $buffer.Length)
        } else {
            $response.StatusCode = 404
        }
        $response.Close()
    } catch {
        # ignore context cancellation on shutdown
    }
}
