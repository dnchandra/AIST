param([int]$Port=8088)

$logDir = "C:\AIST\AuditService"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
$logFile = "$logDir\audit_service.log"

function Write-AppLog($level, $msg) {
    $line = "$([DateTime]::UtcNow.ToString('yyyy-MM-dd HH:mm:ss.fff')) [$level] $msg"
    Add-Content -Path $logFile -Value $line -ErrorAction SilentlyContinue
    $nowNs = [string]([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() * 1000000)
    $payload = '{"streams":[{"stream":{"app":"ticketflow","service":"audit-service","os":"win2019","level":"' + $level + '"},"values":[["' + $nowNs + '","' + $msg.Replace('"', '\"') + '"]]}]}'
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
        $req = [System.Net.HttpWebRequest]::Create("http://192.168.1.131:3100/loki/api/v1/push")
        $req.Method = "POST"
        $req.ContentType = "application/json"
        $req.Timeout = 1000
        $stream = $req.GetRequestStream()
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Close()
        $resp = $req.GetResponse()
        $resp.Close()
    } catch {}
}

$l = New-Object System.Net.HttpListener
$l.Prefixes.Add("http://+:$Port/")
$l.Start()
$blocked = 0
$reqs = 0

Write-AppLog "INFO" "Audit & DB Service started on port $Port (Windows Server 2019)"

while ($l.IsListening) {
    $ctx = $l.GetContext()
    $req = $ctx.Request
    $res = $ctx.Response
    $res.Headers.Add("Access-Control-Allow-Origin", "*")
    $p = $req.Url.AbsolutePath
    $reqs++

    if ($p -eq "/health") {
        $res.ContentType = "application/json"
        $b = [System.Text.Encoding]::UTF8.GetBytes('{"status":"HEALTHY","service":"audit-service","os":"Windows Server 2019","database":"TicketFlowDB"}')
        $res.OutputStream.Write($b, 0, $b.Length)
        Write-AppLog "INFO" "GET /health -> 200 OK (SQL Server connection pool active)"
    } elseif ($p -eq "/api/v1/audit/logs") {
        $res.ContentType = "application/json"
        $b = [System.Text.Encoding]::UTF8.GetBytes('{"success":true,"count":3,"data":[{"id":1,"action":"SCHEMA_INIT"},{"id":2,"action":"SECURITY_AUDIT"},{"id":3,"action":"DB_HEALTHY"}]}')
        $res.OutputStream.Write($b, 0, $b.Length)
        Write-AppLog "INFO" "GET /api/v1/audit/logs -> 200 OK fetched audit trail"
    } elseif ($p -eq "/metrics") {
        $res.ContentType = "text/plain; version=0.0.4"
        $m = "# HELP audit_events_total Total events`n# TYPE audit_events_total counter`naudit_events_total $reqs`n# HELP sqlserver_blocked_sessions Blocked sessions`n# TYPE sqlserver_blocked_sessions gauge`nsqlserver_blocked_sessions $blocked`n"
        $b = [System.Text.Encoding]::UTF8.GetBytes($m)
        $res.OutputStream.Write($b, 0, $b.Length)
    } elseif ($p -eq "/api/v1/chaos/deadlock") {
        $blocked = 5
        $res.ContentType = "application/json"
        $b = [System.Text.Encoding]::UTF8.GetBytes('{"chaos":"sql_deadlock_injected","blocked_sessions":5}')
        $res.OutputStream.Write($b, 0, $b.Length)
        Write-AppLog "ERROR" "CHAOS_INJECTION: SQL Server exclusive table lock (TABLOCKX) contention; 5 SPIDs blocked"
    } elseif ($p -eq "/api/v1/chaos/recover") {
        $blocked = 0
        $res.ContentType = "application/json"
        $b = [System.Text.Encoding]::UTF8.GetBytes('{"chaos":"recovered","blocked_sessions":0}')
        $res.OutputStream.Write($b, 0, $b.Length)
        Write-AppLog "INFO" "CHAOS_RECOVERY: SPID killed by DBA; SQL Server lock graph clear"
    } else {
        $res.StatusCode = 404
    }
    $res.Close()
}
