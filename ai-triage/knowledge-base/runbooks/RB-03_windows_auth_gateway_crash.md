# SRE Runbook: RB-03 - Windows Server 2025 Auth Gateway Crash & Outage

## Severity: CRITICAL / P1
**Target Environments**: Windows Server 2025 (`192.168.1.132`)  
**Alert Triggers**: `AuthGatewayServiceUnavailable`, `up{service="auth-gateway"} == 0`

---

### 1. Initial Assessment
When Auth Gateway returns HTTP 500 or becomes unreachable:
1. Verify process state via WinRM:
   ```powershell
   Get-Process powershell | Where-Object { $_.CommandLine -like "*AuthGateway*" }
   ```
2. Verify port 5001 listening state:
   ```powershell
   Get-NetTCPConnection -LocalPort 5001 -State Listen
   ```

### 2. Autonomous Diagnostic Steps
- Read the Auth Gateway transcript log:
   ```powershell
   Get-Content -Path "C:\AIST\AuthGateway\server.log" -Tail 20
   ```
- Verify Windows Firewall status:
   ```powershell
   Get-NetFirewallProfile | Select-Object Name, Enabled
   ```

### 3. Remediation Actions
1. **Low Blast Radius**: Call recovery endpoint or restart the PowerShell daemon:
   ```powershell
   Invoke-RestMethod -Uri "http://192.168.1.132:5001/api/v1/chaos/recover" -Method Post
   ```
2. **Process Recycling via WMI**:
   ```powershell
   Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*AuthGateway*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
   $w = [wmiclass]"\\.\root\cimv2:Win32_Process"
   $w.Create("powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\AIST\AuthGateway\server.ps1")
   ```

