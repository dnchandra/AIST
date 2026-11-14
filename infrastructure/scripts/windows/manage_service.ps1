param(
  [Parameter(Mandatory=$true)] [string]$ServiceName,
  [Parameter(Mandatory=$true)] [ValidateSet('start','stop','restart','status')] [string]$Action
)

$ErrorActionPreference = 'Stop'

function Get-ServiceSafe {
  param([string]$Name)
  try {
    return Get-Service -Name $Name -ErrorAction Stop
  } catch {
    # Try by display name as a fallback
    try {
      return Get-Service | Where-Object { $_.DisplayName -eq $Name } | Select-Object -First 1
    } catch {
      return $null
    }
  }
}

$svc = Get-ServiceSafe -Name $ServiceName
if (-not $svc) {
  $out = [ordered]@{
    name = $ServiceName
    action = $Action
    success = $false
    error = "Service not found"
    preStatus = "Unknown"
    postStatus = "Unknown"
    timestamp = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
  }
  $out | ConvertTo-Json -Compress
  exit 0
}

$pre = $svc.Status.ToString()
try {
  if ($Action.ToLower() -ne 'status') {
    switch ($Action.ToLower()) {
      'start' { if ($svc.Status -ne 'Running') { Start-Service -Name $svc.Name -ErrorAction Stop } }
      'stop' { if ($svc.Status -ne 'Stopped') { Stop-Service -Name $svc.Name -Force -ErrorAction Stop } }
      'restart' { Restart-Service -Name $svc.Name -Force -ErrorAction Stop }
    }
    Start-Sleep -Milliseconds 300
  }
  $svc2 = Get-ServiceSafe -Name $svc.Name
  $post = if ($svc2) { $svc2.Status.ToString() } else { 'Unknown' }
  $out = [ordered]@{
    name = $svc.Name
    displayName = $svc.DisplayName
    action = $Action
    success = $true
    error = ""
    preStatus = $pre
    postStatus = $post
    timestamp = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
  }
} catch {
  $svc3 = Get-ServiceSafe -Name $svc.Name
  $post2 = if ($svc3) { $svc3.Status.ToString() } else { 'Unknown' }
  $out = [ordered]@{
    name = $svc.Name
    displayName = $svc.DisplayName
    action = $Action
    success = $false
    error = $_.Exception.Message
    preStatus = $pre
    postStatus = $post2
    timestamp = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
  }
}

$out | ConvertTo-Json -Compress
