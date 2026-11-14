param(
  [Parameter(Mandatory=$true)]
  [ValidateSet('Application','System','Security','Setup','Windows PowerShell')]
  [string]$Channel,

  [ValidateRange(1,168)]
  [int]$Hours = 24,

  [string]$StartTime = "",
  [string]$EndTime = "",

  [ValidateRange(1,10000)]
  [int]$MaxEvents = 200
)

$ErrorActionPreference = 'Stop'

# helper to try-parse ISO or common formats
function Test-DateString([string]$s, [ref]$dt) {
  if (-not $s) { $dt.Value = $null; return $true }
  
  # Try simple parse first
  try {
    $parsed = [datetime]::Parse($s)
    $dt.Value = $parsed
    return $true
  } catch {
    # If simple parse fails, try with specific culture
    try {
      $parsed = [datetime]::ParseExact($s, 'o', [System.Globalization.CultureInfo]::InvariantCulture)
      $dt.Value = $parsed
      return $true
    } catch {
      # Try common formats
      $formats = @('yyyy-MM-ddTHH:mm:ss', 'yyyy-MM-dd HH:mm:ss', 'MM/dd/yyyy HH:mm:ss', 'dd/MM/yyyy HH:mm:ss')
      foreach ($format in $formats) {
        try {
          $parsed = [datetime]::ParseExact($s, $format, [System.Globalization.CultureInfo]::InvariantCulture)
          $dt.Value = $parsed
          return $true
        } catch {
          continue
        }
      }
    }
  }
  return $false
}

try {
  $after = $null; $before = $null
  if ($StartTime -and $StartTime.Trim()) {
    if (-not (Test-DateString $StartTime ([ref]$after))) { throw 'Invalid StartTime format. Use ISO8601 or a recognizable datetime.' }
    # $after is set by reference inside Test-DateString
  } else {
    $after = (Get-Date).AddHours(-1 * $Hours)
  }

  if ($EndTime -and $EndTime.Trim()) {
    if (-not (Test-DateString $EndTime ([ref]$before))) { throw 'Invalid EndTime format. Use ISO8601 or a recognizable datetime.' }
    # $before is set by reference inside Test-DateString
  } else {
    $before = $null
  }

  # Build FilterHashtable robustly
  $filter = @{ LogName = $Channel }
  if ($after)  { $filter['StartTime'] = $after }
  if ($before) { $filter['EndTime'] = $before }

  # Use -FilterHashtable when possible. If both times present, Get-WinEvent handles it.
  try {
    $events = Get-WinEvent -FilterHashtable $filter -MaxEvents $MaxEvents -ErrorAction Stop
  } catch [System.Exception] {
    # Handle "No events found" specifically
    if ($_.Exception.Message -like "*No events were found*") {
      # Return empty array with metadata for debugging
      $debugInfo = [PSCustomObject]@{
        Message = "No events found in the specified time range"
        Channel = $Channel
        StartTime = if ($after) { $after.ToString('o') } else { "Not specified" }
        EndTime = if ($before) { $before.ToString('o') } else { "Not specified" }
        MaxEvents = $MaxEvents
        QueryType = if ($after -and $before) { "Date Range" } elseif ($after -and -not $before) { "Since StartTime" } elseif (-not $after -and $before) { "Until EndTime" } else { "Last $Hours hours" }
      }
      @($debugInfo) | ConvertTo-Json -Depth 4
      return
    } else {
      # Re-throw other exceptions
      throw
    }
  }

  $MAX_MESSAGE = 2000
  $out = $events | ForEach-Object {
    $msg = ($_.Message -replace '[\r\n]+',' ')
    if ($msg.Length -gt $MAX_MESSAGE) { $msg = $msg.Substring(0,$MAX_MESSAGE) + '...[TRUNC]' }
    [PSCustomObject]@{
      RecordId         = $_.RecordId
      TimeCreated      = ($_.TimeCreated).ToString('o')
      ProviderName     = ($_.ProviderName -as [string])
      Id               = $_.Id
      LevelDisplayName = ($_.LevelDisplayName -as [string])
      Message          = $msg
      UserId           = ($_.UserId -as [string])
      MachineName      = $_.MachineName
    }
  }

  if (-not $out) { $out = @() }
  $out | ConvertTo-Json -Depth 4
} catch {
  # Build structured error object
  $errObj = [PSCustomObject]@{
    Error = $_.Exception.Message
    Type  = $_.Exception.GetType().FullName
  }
  $errObj | ConvertTo-Json -Depth 3
}

