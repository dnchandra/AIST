param(
  [string[]]$Drives = @(),
  [string[]]$Folders = @(),
  [int]$MaxDepth = 5,
  [int]$TopN = 50,
  [bool]$IncludeFiles = $true,
  [int]$MaxSeconds = 120
)

# Clamp MaxDepth to a safe range (UI/back-end allow 1..20)
$MaxDepth = [Math]::Max(1, [Math]::Min(20, [int]$MaxDepth))

function New-HRSize {
  param([long]$Bytes)
  if ($Bytes -lt 1024) { return "$Bytes B" }
  $kb = [math]::Round($Bytes/1KB,2)
  if ($kb -lt 1024) { return "$kb KB" }
  $mb = [math]::Round($Bytes/1MB,2)
  if ($mb -lt 1024) { return "$mb MB" }
  $gb = [math]::Round($Bytes/1GB,2)
  return "$gb GB"
}

function Get-DriveInfo {
  param([string]$Letter)
  try {
    $d = Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DeviceID='$($Letter.ToUpper()):'" -ErrorAction Stop
    if ($null -eq $d) { return $null }
    $total = [int64]($d.Size)
    $free = [int64]($d.FreeSpace)
    $used = $total - $free
    return [pscustomobject]@{
      Letter = $Letter.ToUpper()
      Label = $d.VolumeName
      FileSystem = $d.FileSystem
      TotalBytes = $total
      FreeBytes = $free
      UsedBytes = $used
      TotalHR = New-HRSize $total
      FreeHR = New-HRSize $free
      UsedHR = New-HRSize $used
    }
  } catch {
    return [pscustomobject]@{ Letter=$Letter.ToUpper(); Error=$_.Exception.Message }
  }
}

function Get-DirTree {
  param(
    [string]$Path,
    [int]$Depth,
    [datetime]$Deadline,
    [int]$TopN = 50,
    [bool]$IncludeFiles = $true
  )
  if ((Get-Date) -gt $Deadline) {
    $leaf = (Split-Path -Leaf $Path)
    if ([string]::IsNullOrWhiteSpace($leaf)) { $leaf = $Path }
    return [pscustomobject]@{ Name=$leaf; Path=$Path; Type='Folder'; SizeBytes=0; SizeHR='0 B'; Children=@(); Truncated=$true }
  }
  $leafName = (Split-Path -Leaf $Path)
  if ([string]::IsNullOrWhiteSpace($leafName)) { $leafName = $Path }
  $item = [pscustomobject]@{ Name=$leafName; Path=$Path; Type='Folder'; SizeBytes=0; SizeHR='0 B'; Children=@(); Truncated=$false }
  try {
    $children = @()
    if ($Depth -gt 0) {
      try {
        $dirs = Get-ChildItem -LiteralPath $Path -Directory -Force -ErrorAction SilentlyContinue
      } catch { $dirs = @() }
      foreach ($d in $dirs) {
        if ((Get-Date) -gt $Deadline) { $item.Truncated = $true; break }
        # Skip reparse points (junctions/symlinks) to avoid loops and misleading virtual folders
        $isReparse = ($d.Attributes -band [System.IO.FileAttributes]::ReparsePoint)
        if ($isReparse) {
          $dn = if ([string]::IsNullOrWhiteSpace($d.Name)) { $d.FullName } else { $d.Name }
          $children += [pscustomobject]@{ Name=$dn; Path=$d.FullName; Type='ReparsePoint'; SizeBytes=0; SizeHR='0 B'; Children=@(); Truncated=$false }
        } else {
          $sub = Get-DirTree -Path $d.FullName -Depth ($Depth-1) -Deadline $Deadline -TopN $TopN -IncludeFiles:$IncludeFiles
          $children += $sub
        }
      }
      if ($IncludeFiles) {
        try {
          $files = Get-ChildItem -LiteralPath $Path -File -Force -ErrorAction SilentlyContinue
        } catch { $files = @() }
        foreach ($f in $files) {
          if ((Get-Date) -gt $Deadline) { $item.Truncated = $true; break }
          $fn = if ([string]::IsNullOrWhiteSpace($f.Name)) { $f.FullName } else { $f.Name }
          $children += [pscustomobject]@{ Name=$fn; Path=$f.FullName; Type='File'; SizeBytes=[int64]$f.Length; SizeHR=(New-HRSize $f.Length); Children=@() }
        }
      }
      # Compute sizes by summing child sizes (sum is over all children, not just TopN)
      if ($TopN -le 0) {
        $item.Children = @($children | Sort-Object -Property SizeBytes -Descending)
      } else {
        $item.Children = @($children | Sort-Object -Property SizeBytes -Descending | Select-Object -First $TopN)
      }
      $item.SizeBytes = ($children | Measure-Object -Property SizeBytes -Sum).Sum
      $item.SizeHR = New-HRSize $item.SizeBytes
    } else {
      # shallow compute only files at this level for size
      try {
        $files2 = Get-ChildItem -LiteralPath $Path -File -Force -ErrorAction SilentlyContinue
      } catch { $files2 = @() }
      $sum = ($files2 | Measure-Object -Property Length -Sum).Sum
      if ($null -eq $sum) { $sum = 0 }
      $item.SizeBytes = [int64]$sum
      $item.SizeHR = New-HRSize $item.SizeBytes
  $item.Children = @()
    }
  } catch {
    $item.Truncated = $true
  }
  return $item
}

try {
  $deadline = (Get-Date).AddSeconds([Math]::Max(30, $MaxSeconds))
  $out = [pscustomobject]@{
    Server = $env:COMPUTERNAME
    Drives = @()
    Targets = @()
  }
  # Normalize drives letters C..Z
  $dl = @()
  foreach ($d in $Drives) { if ($d -match '^[C-Zc-z]$') { $dl += $d.ToUpper() } }
  $dl = $dl | Select-Object -Unique
  foreach ($d in $dl) { $di = Get-DriveInfo -Letter $d; if ($di) { $out.Drives += $di } }

  # Normalize folders
  $fl = @(); foreach ($p in $Folders) { if ($p -and $p.Trim().Length -gt 0) { $fl += $p.Trim() } }
  $fl = $fl | Select-Object -Unique
  foreach ($p in $fl) {
    try {
      if (Test-Path -LiteralPath $p) {
        $tree = Get-DirTree -Path $p -Depth $MaxDepth -Deadline $deadline -TopN $TopN -IncludeFiles:$IncludeFiles
        $out.Targets += [pscustomobject]@{ Target=$p; Tree=$tree; Truncated=($tree.Truncated -eq $true) }
      } else {
        $out.Targets += [pscustomobject]@{ Target=$p; Error='Path not found' }
      }
    } catch {
      $out.Targets += [pscustomobject]@{ Target=$p; Error=$_.Exception.Message }
    }
  }
  # Use a high JSON depth to preserve deep directory trees (UI allows up to 20 levels)
  $out | ConvertTo-Json -Depth 64
} catch {
  @{ Error = $_.Exception.Message } | ConvertTo-Json -Depth 4
}
