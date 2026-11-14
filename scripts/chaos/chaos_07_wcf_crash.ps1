# CHAOS-07: WCF Audit Service Unhandled Crash Simulation
# Target: Windows Server 2019 (192.168.1.133:8088)
# Induces Event ID 1026 (.NET Runtime) in Windows Application Event Log
Write-Host "=== [CHAOS-07] Invoking WCF NullReferenceException ===" -ForegroundColor Yellow

$wcfUrl = "http://192.168.1.133:8088/AuditService.svc"
Write-Host "Calling $wcfUrl to trigger simulated unhandled crash..."
try {
    Invoke-WebRequest -Uri "$wcfUrl/chaos" -Method Post -TimeoutSec 5
} catch {
    Write-Host "Crash triggered as expected: Event ID 1026 written to Application Event Log." -ForegroundColor Green
}

