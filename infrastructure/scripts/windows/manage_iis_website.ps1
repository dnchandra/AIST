param(
  [Parameter(Mandatory=$true)] [string]$SiteName,
  [Parameter(Mandatory=$true)] [ValidateSet('start','stop','restart','status')] [string]$Action
)

Import-Module WebAdministration
$ErrorActionPreference = 'Stop'

function Get-WebsiteSafe {
  param([string]$Name)
  try {
    return Get-Website -Name $Name -ErrorAction Stop
  } catch {
    return $null
  }
}

$site = Get-WebsiteSafe -Name $SiteName
if (-not $site) {
  $out = [ordered]@{
    name = $SiteName
    action = $Action
    success = $false
    error = "Website not found"
    preStatus = "Unknown"
    postStatus = "Unknown"
    timestamp = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
  }
  $out | ConvertTo-Json -Compress
  exit 0
}

$pre = $site.State.ToString()
try {
  switch ($Action.ToLower()) {
    'start'   { if ($site.State -ne 'Started') { Start-Website -Name $site.Name -ErrorAction Stop } }
    'stop'    { if ($site.State -ne 'Stopped') { Stop-Website -Name $site.Name -ErrorAction Stop } }
    'restart' { Stop-Website -Name $site.Name -ErrorAction SilentlyContinue; Start-Website -Name $site.Name -ErrorAction Stop }
    'status'  { }
  }
  Start-Sleep -Milliseconds 300
  $site2 = Get-WebsiteSafe -Name $site.Name
  $post = if ($site2) { $site2.State.ToString() } else { 'Unknown' }
  $out = [ordered]@{
    name = $site.Name
    action = $Action
    success = $true
    error = ""
    preStatus = $pre
    postStatus = $post
    timestamp = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
  }
} catch {
  $site3 = Get-WebsiteSafe -Name $site.Name
  $post2 = if ($site3) { $site3.State.ToString() } else { 'Unknown' }
  $out = [ordered]@{
    name = $site.Name
    action = $Action
    success = $false
    error = $_.Exception.Message
    preStatus = $pre
    postStatus = $post2
    timestamp = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
  }
}

$out | ConvertTo-Json -Compress
