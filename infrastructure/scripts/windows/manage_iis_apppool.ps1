param(
  [Parameter(Mandatory=$true)] [string]$AppPoolName,
  [Parameter(Mandatory=$true)] [ValidateSet('start','stop','recycle','status')] [string]$Action
)

Import-Module WebAdministration
$ErrorActionPreference = 'Stop'

function Get-AppPoolSafe {
  param([string]$Name)
  try {
    return Get-WebAppPoolState -Name $Name -ErrorAction Stop
  } catch {
    return $null
  }
}

# For status we can always query state; for other actions use iisappcmd or WebAdministration cmdlets
$preState = 'Unknown'
try {
  $state = Get-AppPoolSafe -Name $AppPoolName
  if ($state) { $preState = $state.Value }
} catch { }

try {
  switch ($Action.ToLower()) {
    'start'   { Start-WebAppPool -Name $AppPoolName -ErrorAction Stop }
    'stop'    { Stop-WebAppPool -Name $AppPoolName -ErrorAction Stop }
    'recycle' { Restart-WebAppPool -Name $AppPoolName -ErrorAction Stop }
    'status'  { }
  }
  Start-Sleep -Milliseconds 300
  $postState = 'Unknown'
  try { $postState = (Get-AppPoolSafe -Name $AppPoolName).Value } catch { }
  $out = [ordered]@{
    name = $AppPoolName
    action = $Action
    success = $true
    error = ""
    preStatus = $preState
    postStatus = $postState
    timestamp = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
  }
} catch {
  $postState = 'Unknown'
  try { $postState = (Get-AppPoolSafe -Name $AppPoolName).Value } catch { }
  $out = [ordered]@{
    name = $AppPoolName
    action = $Action
    success = $false
    error = $_.Exception.Message
    preStatus = $preState
    postStatus = $postState
    timestamp = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
  }
}

$out | ConvertTo-Json -Compress
