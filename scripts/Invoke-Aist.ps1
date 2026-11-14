<#
.SYNOPSIS
    AIST Master Automation & Orchestration Script (PowerShell Edition)
    Unified SRE Platform Control Plane for Multi-OS VMware Fleet & Local RTX 5090 AI

.DESCRIPTION
    Native PowerShell CLI interface delegating to manage_aist.py:
    - list / urls : Display live application directory, endpoints, containers, and ports
    - status / test : Execute 21-point automated verification & health matrix
    - start       : Start services (Target: all, webui, apps, obs, or specific service)
    - stop        : Stop services (Target: all, apps, obs, webui, or specific service)
    - restart     : Restart services (Target: all, apps, obs, webui, or specific service)
    - deploy      : Deploy microservices and observability across 4 VMware guest VMs
    - logs        : View live logs for any service across Linux and Windows
    - setup       : Validate vCenter, datastores, VM power states, firewalls
    - chaos       : Inject failure scenarios (cpu_spike, auth_crash, sql_deadlock, etc.)
    - recover     : Restore all services back to 100% healthy state
    - clean       : Reset temporary logs while preserving VM disks

.EXAMPLE
    .\scripts\Invoke-Aist.ps1 -Action list
    .\scripts\Invoke-Aist.ps1 -Action urls
    .\scripts\Invoke-Aist.ps1 -Action status
    .\scripts\Invoke-Aist.ps1 -Action start -Target all
    .\scripts\Invoke-Aist.ps1 -Action stop -Target apps
    .\scripts\Invoke-Aist.ps1 -Action restart -Target ticketflow
    .\scripts\Invoke-Aist.ps1 -Action deploy
    .\scripts\Invoke-Aist.ps1 -Action logs -Target ticketflow
    .\scripts\Invoke-Aist.ps1 -Action chaos -Scenario sql_deadlock
    .\scripts\Invoke-Aist.ps1 -Action recover
#>

param(
    [Parameter(Position=0, Mandatory=$false)]
    [ValidateSet("setup", "setup-infra", "deploy", "deploy-apps", "status", "verify", "start", "stop", "restart", "clean", "clean-infra", "list", "urls", "logs", "chaos", "recover", "traffic", "vm")]
    [string]$Action = "status",

    [Parameter(Position=1, Mandatory=$false)]
    [string]$Target = "",

    [Parameter(Mandatory=$false)]
    [ValidateSet("cpu_spike", "auth_crash", "sql_deadlock", "queue_backlog", "ticket_latency", "ticket_500", "multistage_cascade", "recover")]
    [string]$Scenario = "cpu_spike",

    [Parameter(Mandatory=$false)]
    [string]$Category = "",

    [Parameter(Mandatory=$false)]
    [int]$Lines = 25,

    [Parameter(Mandatory=$false)]
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir

# Locate Python Virtual Environment
$PythonPath = Join-Path $RootDir ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonPath)) {
    $PythonPath = "python"
}

Write-Host @"
======================================================================
     AIST: Autonomous SRE Incident Triage Platform v3.0
   Unified Control Plane across Multi-OS VMware & RTX 5090 AI
======================================================================
"@ -ForegroundColor Cyan

$CtlScript = Join-Path $RootDir "manage_aist.py"
$ArgsList = @($CtlScript, $Action)

if ($Target) {
    $ArgsList += $Target
}

if ($Action -eq "chaos") {
    $ArgsList += @("--scenario", $Scenario)
}

if ($Category) {
    $ArgsList += @("--category", $Category)
}

if ($Action -eq "logs") {
    $ArgsList += @("--lines", $Lines)
}

if ($Json) {
    $ArgsList += "--json"
}

& $PythonPath $ArgsList

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n[+] Action '$Action' completed successfully." -ForegroundColor Green
} else {
    Write-Host "`n[!] Action '$Action' finished with exit code $LASTEXITCODE." -ForegroundColor Red
}

