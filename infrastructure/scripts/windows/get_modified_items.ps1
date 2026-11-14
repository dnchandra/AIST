# get_modified_items.ps1
# Expects these variables to already be set by the caller (your Python preamble):
#   $FolderPath (string)
#   $ModifiedAfter (nullable [datetime])
#   $ModifiedBefore (nullable [datetime])
#   $Recurse ([bool] or [switch])
#   $MaxItems (int)
#   $Extensions (string[])
#   $MaxSeconds (int, optional)
#   $NamePattern (string, optional)  # filename base (no extension), allowed chars: letters/digits/space/_/-

$ErrorActionPreference = 'Stop'

# Optional time budget to avoid excessively long scans (in seconds)
if (-not $MaxSeconds -or $MaxSeconds -le 0) { $MaxSeconds = 150 }
$sw = [System.Diagnostics.Stopwatch]::StartNew()

# ----- Safe defaults and validation -----
if (-not $FolderPath) { 
  Write-Output '{"error":"FolderPath parameter is required"}' | ConvertFrom-Json | ConvertTo-Json -Compress
  return 
}
if (-not $MaxItems -or $MaxItems -le 0) { $MaxItems = 500 }
if (-not $Extensions) { $Extensions = @() }
# ---------------------------------------------------------------

$result = [ordered]@{
  FolderPath     = $FolderPath
  Exists         = $false
  ScannedRecurse = [bool]$Recurse
  ModifiedAfter  = $ModifiedAfter
  ModifiedBefore = $ModifiedBefore
  ParsedAfterLocal = $null
  ParsedBeforeLocal = $null
  ServerTimeZone = [TimeZoneInfo]::Local.Id
  Extensions     = $Extensions
  Items          = @()
}

if (-not (Test-Path -LiteralPath $FolderPath)) {
  $result | ConvertTo-Json -Depth 6 -Compress
  return
}

$result.Exists = $true

# Normalize extensions like ".ext" in lowercase
$extSet = @{}
foreach ($e in $Extensions) {
  if (-not [string]::IsNullOrWhiteSpace($e)) {
    $norm = $e.Trim()
    if ($norm -and -not $norm.StartsWith('.')) { $norm = '.' + $norm }
    $extSet[$norm.ToLowerInvariant()] = $true
  }
}

# Optional safe name pattern (strip disallowed chars and collapse spaces)
$NamePatternSafe = $null
try {
  if ($NamePattern) {
    $tmp = -join ($NamePattern.ToCharArray() | ForEach-Object { if ([char]::IsLetterOrDigit($_) -or $_ -in @(' ','_','-')) { $_ } })
    $tmp = ($tmp -replace '\s+', ' ').Trim()
    if ($tmp) { $NamePatternSafe = $tmp }
  }
} catch { $NamePatternSafe = $null }

$gciParams = @{
  LiteralPath = $FolderPath
  Force       = $true
  ErrorAction = 'SilentlyContinue'
}
if ($Recurse) { $gciParams['Recurse'] = $true }

# Convert string dates to DateTime objects if provided
$afterDateTime = $null
$beforeDateTime = $null

if ($ModifiedAfter) {
  try {
    # Parse as UTC and convert to local time for proper comparison
    if ($ModifiedAfter -match 'Z$' -or $ModifiedAfter -match '[+-]\d{2}:\d{2}$') {
      # ISO format with timezone - parse as DateTimeOffset and convert to local
      $afterDateTime = [DateTimeOffset]::Parse($ModifiedAfter).ToLocalTime().DateTime
    } else {
      # Assume local time if no timezone specified
      $afterDateTime = [DateTime]::Parse($ModifiedAfter)
    }
    $result.ParsedAfterLocal = $afterDateTime.ToString('yyyy-MM-dd HH:mm:ss')
  } catch {
    Write-Warning "Could not parse ModifiedAfter date: $ModifiedAfter"
  }
}

if ($ModifiedBefore) {
  try {
    # Parse as UTC and convert to local time for proper comparison
    if ($ModifiedBefore -match 'Z$' -or $ModifiedBefore -match '[+-]\d{2}:\d{2}$') {
      # ISO format with timezone - parse as DateTimeOffset and convert to local
      $beforeDateTime = [DateTimeOffset]::Parse($ModifiedBefore).ToLocalTime().DateTime
    } else {
      # Assume local time if no timezone specified
      $beforeDateTime = [DateTime]::Parse($ModifiedBefore)
    }
    $result.ParsedBeforeLocal = $beforeDateTime.ToString('yyyy-MM-dd HH:mm:ss')
  } catch {
    Write-Warning "Could not parse ModifiedBefore date: $ModifiedBefore"
  }
}

# Use a growable generic list to avoid array concatenation overhead and op_Addition issues
$script:items = New-Object 'System.Collections.Generic.List[object]'

# Faster file enumeration: when extensions are provided, use -Filter per extension to reduce filesystem scanning
function Add-ItemsFromPipeline {
  param([object]$pipe)
    # Normalize input to an enumerable collection
  if ($null -eq $pipe) { return }
  $collection = $pipe
  if (-not ($collection -is [System.Collections.IEnumerable]) -or ($collection -is [string])) {
    $collection = @($pipe)
  }
  foreach ($entry in $collection) {
    if ($sw.Elapsed.TotalSeconds -ge $MaxSeconds) { return }
    if ($afterDateTime -and $entry.LastWriteTime -lt $afterDateTime) { continue }
    if ($beforeDateTime -and $entry.LastWriteTime -gt $beforeDateTime) { continue }
    $isDir = $entry.PSIsContainer
    $obj = [pscustomobject]@{
      Name          = $entry.Name
      FullName      = $entry.FullName
      Type          = if ($isDir) { 'Folder' } else { 'File' }
      Length        = if ($isDir) { $null } else { $entry.Length }
      LastWriteTime = $entry.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')
    }
    [void]$script:items.Add($obj)
    if ($script:items.Count -ge $MaxItems) { return }
  }
}

# 1) Files (prioritize files; usually what we care about for deployments)
if ($extSet.Count -gt 0) {
  foreach ($extKey in $extSet.Keys) {
    if ($script:items.Count -ge $MaxItems) { break }
    if ($NamePatternSafe) {
      $filter = "*${NamePatternSafe}*${extKey}"
    } else {
      $filter = "*" + $extKey
    }
    $pipe = Get-ChildItem @gciParams -File -Filter $filter
    Add-ItemsFromPipeline -pipe $pipe
  }
} else {
  if ($NamePatternSafe) {
    $filter = "*${NamePatternSafe}*"
    $pipe = Get-ChildItem @gciParams -File -Filter $filter
  } else {
    $pipe = Get-ChildItem @gciParams -File
  }
  Add-ItemsFromPipeline -pipe $pipe
}

# 2) Folders (only if we still have room AND no extension filters were provided)
#    When extensions are specified, the caller expects only matching files.
if ($extSet.Count -eq 0 -and -not $NamePatternSafe -and $script:items.Count -lt $MaxItems) {
  $pipe2 = Get-ChildItem @gciParams -Directory
  Add-ItemsFromPipeline -pipe $pipe2
}

# Force array even when only one item matched
$result.Items = @($script:items.ToArray())

$result | ConvertTo-Json -Depth 6 -Compress


