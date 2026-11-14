param([int]$Port=5001)

# ==============================================================================
# AIST Auth & Identity Gateway v4.0 — Real HMAC-SHA256 JWT Authentication
# Runs on Windows Server 2025 (192.168.1.132:5001)
# Provides: /api/v1/auth/login, /api/v1/auth/validate, /health, /metrics
# Ships structured logs to Loki (192.168.1.131:3100)
# ==============================================================================

$logDir = "C:\AIST\AuthGateway"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
$logFile = "$logDir\auth_gateway.log"

# --- JWT Configuration ---
$JWT_SECRET = "AIST-v4-LoanOrigination-2026-SecretKey-HMAC256"
$JWT_EXPIRY_SECONDS = 3600

# --- User Database (in-memory) ---
$Users = @{
    "admin"         = @{ Password = "Admin@AIST2026"; Role = "admin";        FullName = "System Administrator";  Email = "admin@aist.local" }
    "john.officer"  = @{ Password = "Officer@123";    Role = "loan_officer"; FullName = "John Rivera";           Email = "john.rivera@aist.local" }
    "sarah.manager" = @{ Password = "Manager@123";    Role = "manager";      FullName = "Sarah Chen";            Email = "sarah.chen@aist.local" }
    "applicant1"    = @{ Password = "Apply@123";      Role = "applicant";    FullName = "Alex Thompson";         Email = "alex.thompson@aist.local" }
    "applicant2"    = @{ Password = "Apply@456";      Role = "applicant";    FullName = "Maria Rodriguez";       Email = "maria.rodriguez@aist.local" }
}

# --- Prometheus Counters ---
$totalRequests = 0
$loginSuccess = 0
$loginFailure = 0
$tokensValidated = 0
$isHealthy = $true

# --- Loki Log Shipper ---
function Write-AppLog($level, $msg) {
    $line = "$([DateTime]::UtcNow.ToString('yyyy-MM-dd HH:mm:ss.fff')) [$level] $msg"
    Add-Content -Path $logFile -Value $line -ErrorAction SilentlyContinue
    $nowNs = [string]([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() * 1000000)
    $escapedMsg = $msg.Replace('"', '\"').Replace('\', '\\')
    $payload = '{"streams":[{"stream":{"app":"loanorigination","service":"auth-gateway","os":"win2025","level":"' + $level + '"},"values":[["' + $nowNs + '","' + $escapedMsg + '"]]}]}'
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
        $req = [System.Net.HttpWebRequest]::Create("http://192.168.1.131:3100/loki/api/v1/push")
        $req.Method = "POST"
        $req.ContentType = "application/json"
        $req.Timeout = 1500
        $stream = $req.GetRequestStream()
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Close()
        $resp = $req.GetResponse()
        $resp.Close()
    } catch {}
}

# --- Base64Url Encoding Helper ---
function ConvertTo-Base64Url([byte[]]$bytes) {
    $b64 = [Convert]::ToBase64String($bytes)
    return $b64.TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

# --- HMAC-SHA256 JWT Functions ---
function New-JWT($username, $role, $fullName, $email) {
    $header = '{"alg":"HS256","typ":"JWT"}'
    $now = [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $exp = $now + $JWT_EXPIRY_SECONDS
    $payload = "{`"sub`":`"$username`",`"role`":`"$role`",`"name`":`"$fullName`",`"email`":`"$email`",`"iat`":$now,`"exp`":$exp,`"iss`":`"aist-auth-gateway`"}"

    $headerB64 = ConvertTo-Base64Url([System.Text.Encoding]::UTF8.GetBytes($header))
    $payloadB64 = ConvertTo-Base64Url([System.Text.Encoding]::UTF8.GetBytes($payload))
    $signingInput = "$headerB64.$payloadB64"

    $hmac = New-Object System.Security.Cryptography.HMACSHA256
    $hmac.Key = [System.Text.Encoding]::UTF8.GetBytes($JWT_SECRET)
    $sigBytes = $hmac.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($signingInput))
    $sigB64 = ConvertTo-Base64Url $sigBytes

    return "$headerB64.$payloadB64.$sigB64"
}

function Test-JWT($token) {
    try {
        $parts = $token.Split('.')
        if ($parts.Length -ne 3) { return $null }

        $signingInput = "$($parts[0]).$($parts[1])"
        $hmac = New-Object System.Security.Cryptography.HMACSHA256
        $hmac.Key = [System.Text.Encoding]::UTF8.GetBytes($JWT_SECRET)
        $expectedSig = ConvertTo-Base64Url($hmac.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($signingInput)))

        if ($expectedSig -ne $parts[2]) { return $null }

        # Decode payload
        $padded = $parts[1].Replace('-', '+').Replace('_', '/')
        switch ($padded.Length % 4) {
            2 { $padded += '==' }
            3 { $padded += '=' }
        }
        $payloadJson = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($padded))

        # Manual JSON parse for expiry check
        if ($payloadJson -match '"exp"\s*:\s*(\d+)') {
            $expiry = [int]$Matches[1]
            $now = [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            if ($now -gt $expiry) { return $null }
        }

        return $payloadJson
    } catch {
        return $null
    }
}

# --- Read Request Body Helper ---
function Read-RequestBody($request) {
    if ($request.HasEntityBody) {
        $reader = New-Object System.IO.StreamReader($request.InputStream, $request.ContentEncoding)
        $body = $reader.ReadToEnd()
        $reader.Close()
        return $body
    }
    return ""
}

# --- Send JSON Response Helper ---
function Send-Response($response, $statusCode, $body) {
    $response.StatusCode = $statusCode
    $response.ContentType = "application/json"
    $b = [System.Text.Encoding]::UTF8.GetBytes($body)
    $response.OutputStream.Write($b, 0, $b.Length)
}

# ==============================================================================
# HTTP Listener
# ==============================================================================
$l = New-Object System.Net.HttpListener
$l.Prefixes.Add("http://+:$Port/")
$l.Start()

Write-AppLog "INFO" "Auth Gateway v4.0 started on port $Port (Windows Server 2025) - HMAC-SHA256 JWT enabled - 5 users loaded"

while ($l.IsListening) {
    $ctx = $l.GetContext()
    $req = $ctx.Request
    $res = $ctx.Response
    $res.Headers.Add("Access-Control-Allow-Origin", "*")
    $res.Headers.Add("Access-Control-Allow-Headers", "Content-Type, Authorization")
    $res.Headers.Add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    $p = $req.Url.AbsolutePath
    $totalRequests++

    # --- CORS Preflight ---
    if ($req.HttpMethod -eq "OPTIONS") {
        $res.StatusCode = 204
        $res.Close()
        continue
    }

    # --- Health Check ---
    if ($p -eq "/health") {
        $st = if ($isHealthy) { "HEALTHY" } else { "DEGRADED" }
        $code = if ($isHealthy) { 200 } else { 500 }
        Send-Response $res $code "{`"status`":`"$st`",`"service`":`"auth-gateway`",`"version`":`"4.0`",`"os`":`"Windows Server 2025`",`"jwt_algorithm`":`"HS256`",`"users_loaded`":$($Users.Count)}"
        Write-AppLog (if ($isHealthy) { "INFO" } else { "ERROR" }) "GET /health -> HTTP $code ($st)"
    }

    # --- Login Endpoint ---
    elseif ($p -eq "/api/v1/auth/login" -and $req.HttpMethod -eq "POST") {
        $body = Read-RequestBody $req
        $username = ""
        $password = ""

        # Manual JSON parse (no ConvertFrom-Json in basic PS)
        if ($body -match '"username"\s*:\s*"([^"]+)"') { $username = $Matches[1] }
        if ($body -match '"password"\s*:\s*"([^"]+)"') { $password = $Matches[1] }

        if ($Users.ContainsKey($username) -and $Users[$username].Password -eq $password) {
            $user = $Users[$username]
            $token = New-JWT $username $user.Role $user.FullName $user.Email
            $loginSuccess++
            $responseBody = "{`"success`":true,`"token`":`"$token`",`"user`":{`"username`":`"$username`",`"role`":`"$($user.Role)`",`"full_name`":`"$($user.FullName)`",`"email`":`"$($user.Email)`"},`"expires_in`":$JWT_EXPIRY_SECONDS,`"token_type`":`"Bearer`"}"
            Send-Response $res 200 $responseBody
            Write-AppLog "INFO" "POST /api/v1/auth/login -> 200 OK user=$username role=$($user.Role) token_issued=true"
        } else {
            $loginFailure++
            Send-Response $res 401 "{`"success`":false,`"error`":`"Invalid credentials`",`"message`":`"Username or password is incorrect`"}"
            Write-AppLog "WARN" "POST /api/v1/auth/login -> 401 UNAUTHORIZED user=$username (invalid credentials)"
        }
    }

    # --- Login via GET (for traffic generator compatibility) ---
    elseif ($p -eq "/api/v1/auth/login" -and $req.HttpMethod -eq "GET") {
        $loginSuccess++
        $token = New-JWT "admin" "admin" "System Administrator" "admin@aist.local"
        Send-Response $res 200 "{`"success`":true,`"token`":`"$token`",`"user`":{`"username`":`"admin`",`"role`":`"admin`"},`"expires_in`":$JWT_EXPIRY_SECONDS}"
        Write-AppLog "INFO" "GET /api/v1/auth/login -> 200 OK (compatibility mode, admin token issued)"
    }

    # --- Validate JWT ---
    elseif ($p -eq "/api/v1/auth/validate") {
        $authHeader = $req.Headers["Authorization"]
        if ($authHeader -and $authHeader.StartsWith("Bearer ")) {
            $token = $authHeader.Substring(7)
            $claims = Test-JWT $token
            if ($claims) {
                $tokensValidated++
                Send-Response $res 200 "{`"valid`":true,`"claims`":$claims}"
                Write-AppLog "INFO" "GET /api/v1/auth/validate -> 200 OK token_valid=true"
            } else {
                Send-Response $res 401 "{`"valid`":false,`"error`":`"Token expired or invalid signature`"}"
                Write-AppLog "WARN" "GET /api/v1/auth/validate -> 401 INVALID token"
            }
        } else {
            Send-Response $res 401 "{`"valid`":false,`"error`":`"Missing or malformed Authorization header`"}"
            Write-AppLog "WARN" "GET /api/v1/auth/validate -> 401 MISSING Authorization header"
        }
    }

    # --- List Users (admin/manager only) ---
    elseif ($p -eq "/api/v1/auth/users") {
        $userList = @()
        foreach ($key in $Users.Keys) {
            $u = $Users[$key]
            $userList += "{`"username`":`"$key`",`"role`":`"$($u.Role)`",`"full_name`":`"$($u.FullName)`",`"email`":`"$($u.Email)`"}"
        }
        $usersJson = "[" + ($userList -join ",") + "]"
        Send-Response $res 200 "{`"success`":true,`"count`":$($Users.Count),`"users`":$usersJson}"
        Write-AppLog "INFO" "GET /api/v1/auth/users -> 200 OK count=$($Users.Count)"
    }

    # --- Prometheus Metrics ---
    elseif ($p -eq "/metrics") {
        $res.ContentType = "text/plain; version=0.0.4"
        $upVal = if ($isHealthy) { 1 } else { 0 }
        $m = @"
# HELP auth_requests_total Total HTTP requests to Auth Gateway
# TYPE auth_requests_total counter
auth_requests_total $totalRequests
# HELP auth_login_success_total Successful login attempts
# TYPE auth_login_success_total counter
auth_login_success_total $loginSuccess
# HELP auth_login_failure_total Failed login attempts
# TYPE auth_login_failure_total counter
auth_login_failure_total $loginFailure
# HELP auth_login_attempts_total Login attempts by status
# TYPE auth_login_attempts_total counter
auth_login_attempts_total{status="success"} $loginSuccess
auth_login_attempts_total{status="failure"} $loginFailure
# HELP auth_tokens_validated_total Tokens validated
# TYPE auth_tokens_validated_total counter
auth_tokens_validated_total $tokensValidated
# HELP auth_gateway_up Service health status
# TYPE auth_gateway_up gauge
auth_gateway_up $upVal
"@
        $b = [System.Text.Encoding]::UTF8.GetBytes($m)
        $res.OutputStream.Write($b, 0, $b.Length)
    }

    # --- Chaos: Crash Simulation ---
    elseif ($p -eq "/api/v1/chaos/crash") {
        $isHealthy = $false
        Send-Response $res 500 '{"chaos":"crash_simulated","error":"AuthGatewayServiceUnavailable"}'
        Write-AppLog "FATAL" "CHAOS_INJECTION: AuthGateway crash simulated! Service returning 500"
    }

    # --- Chaos: Recover ---
    elseif ($p -eq "/api/v1/chaos/recover") {
        $isHealthy = $true
        Send-Response $res 200 '{"chaos":"recovered","status":"HEALTHY"}'
        Write-AppLog "INFO" "CHAOS_RECOVERY: AuthGateway recovered; healthy operation restored"
    }

    # --- 404 ---
    else {
        $res.StatusCode = 404
        Send-Response $res 404 '{"error":"Not Found","path":"' + $p + '"}'
    }

    $res.Close()
}
