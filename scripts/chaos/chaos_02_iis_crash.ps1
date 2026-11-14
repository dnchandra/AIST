# CHAOS-02: IIS AppPool Crash on Windows Server 2025
# Triggers AuthGatewayServiceUnavailable (HTTP 503) in Prometheus
Write-Host "=== [CHAOS-02] Stopping Auth Gateway IIS Application Pool ===" -ForegroundColor Yellow
Write-Host "Target: Windows Server 2025 (192.168.1.132)"

try {
    Import-Module WebAdministration -ErrorAction SilentlyContinue
    Stop-WebAppPool -Name "AuthGatewayAppPool" -ErrorAction SilentlyContinue
    Write-Host "Successfully stopped AuthGatewayAppPool. HTTP 503 errors will now fire." -ForegroundColor Green
    Write-Host "Expected AI Triage: mcp_windows_diag detects stopped AppPool -> prompts HITL to restart."
} catch {
    Write-Host "Error stopping AppPool: $_" -ForegroundColor Red
}

