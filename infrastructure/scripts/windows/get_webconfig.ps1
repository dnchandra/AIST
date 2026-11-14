
param(
  [Parameter(Mandatory = $true)]
  [string]$FolderPath
)

$ErrorActionPreference = 'Stop'
$web = Join-Path -Path $FolderPath -ChildPath 'web.config'
if (-not (Test-Path -LiteralPath $FolderPath)) {
  Write-Output '{"Error": "Folder not found"}'
  exit 1
}
if (-not (Test-Path -LiteralPath $web)) {
  Write-Output '{"Error": "web.config not found in folder"}'
  exit 1
}
$fi = Get-Item -LiteralPath $web -ErrorAction Stop
$maxDownloadSize = 5MB
if ($fi.Length -gt $maxDownloadSize) {
  Write-Output '{"Error": "web.config too large to download (limit: 5MB)"}'
  exit 1
}
$bytes = [System.IO.File]::ReadAllBytes($web)
$base64 = [System.Convert]::ToBase64String($bytes)
Write-Output ('{"WebConfigBase64": "' + $base64 + '"}')
