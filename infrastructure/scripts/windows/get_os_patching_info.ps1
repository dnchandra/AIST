# get_os_patching_info.ps1
# Returns JSON with Server, OSVersion, UptimeSeconds, Notes, IISStoppedSites, StoppedAppPools, AutoStoppedServices
# Expects $null input; script should run on remote machine and output JSON array or object

# Inline function definitions (consolidated to avoid missing modular script issues on remote hosts)
function Get-OSPatchingUptime {
    try {
        $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
        $caption = $os.Caption
        $version = $os.Version
        $lastBoot = $os.LastBootUpTime

        $bootTime = $null
        if ($lastBoot -is [DateTime]) {
            $bootTime = $lastBoot
        } elseif ([string]::IsNullOrWhiteSpace([string]$lastBoot)) {
            $bootTime = $null
        } else {
            try { $bootTime = [Management.ManagementDateTimeConverter]::ToDateTime($lastBoot) } catch { $bootTime = $null }
        }

        if ($bootTime) { $uptimeSeconds = [math]::Floor(((Get-Date) - $bootTime).TotalSeconds); $notes = "" }
        else { $uptimeSeconds = 0; $notes = "LastBootUpTime unavailable or invalid" }

        # Services: any service with StartMode == 'Auto' but State != 'Running'
        $autoStoppedServices = @()
        try {
            $svcCandidates = Get-CimInstance -ClassName Win32_Service -ErrorAction SilentlyContinue |
                Where-Object { ($_.StartMode -eq 'Auto' -or $_.StartMode -eq 'Automatic') -and ($_.State -ne 'Running') }
            foreach ($sv in $svcCandidates) { $autoStoppedServices += $sv.Name }
        } catch { }

        return @{ Server = $env:COMPUTERNAME; OSVersion = "$caption ($version)"; UptimeSeconds = $uptimeSeconds; Notes = $notes; AutoStoppedServices = $autoStoppedServices }
    } catch {
        $err = $_.Exception.Message
        return @{ Server = $env:COMPUTERNAME; OSVersion = ''; UptimeSeconds = 0; Notes = $err; AutoStoppedServices = @() }
    }
}

function Get-OSPatchingIIS {
    try {
        Import-Module WebAdministration -ErrorAction Stop
    } catch {
        return @{ IISStoppedSites = @(); StoppedAppPools = @(); Notes = 'WebAdministration module not available' }
    }

    $stoppedSites = @()
    try {
        $sites = Get-Website -ErrorAction SilentlyContinue
        if ($sites) {
            foreach ($s in $sites) { if ($s.State -ne 'Started') { $stoppedSites += $s.Name } }
        }
    } catch { }

    $stoppedPools = @()
    try {
        $pools = Get-ChildItem IIS:\AppPools -ErrorAction SilentlyContinue
        foreach ($p in $pools) { if ($p.state -ne 'Started') { $stoppedPools += $p.name } }
    } catch {
        try {
            $pools = Get-WebAppPoolState -ErrorAction SilentlyContinue
            foreach ($p in $pools) { if ($p.Value -ne 'Started') { $stoppedPools += $p.Name } }
        } catch { }
    }

    return @{ IISStoppedSites = $stoppedSites; StoppedAppPools = $stoppedPools; Notes = '' }
}

try {
    # Call inline functions directly
    $uptimeObj = Get-OSPatchingUptime
    $iisObj = Get-OSPatchingIIS

    # Merge results safely
    $server = $env:COMPUTERNAME
    $osVersion = ''
    $uptimeSeconds = 0
    $notes = ''
    $autoStoppedServices = @()
    if ($uptimeObj) {
        $osVersion = $uptimeObj.OSVersion
        $uptimeSeconds = $uptimeObj.UptimeSeconds
        $notes = $uptimeObj.Notes
        $autoStoppedServices = $uptimeObj.AutoStoppedServices
    }

    $iisStopped = @()
    $stoppedPools = @()
    if ($iisObj) { 
        $iisStopped = $iisObj.IISStoppedSites
        $stoppedPools = $iisObj.StoppedAppPools
        if ($iisObj.Notes -and $iisObj.Notes.Trim() -ne '') {
            if ($notes -and $notes.Trim() -ne '') {
                $notes = "$notes; $($iisObj.Notes)"
            } else {
                $notes = $iisObj.Notes
            }
        }
    }

    # Ensure arrays are arrays
    if (-not $iisStopped) { $iisStopped = @() }
    if (-not $stoppedPools) { $stoppedPools = @() }
    if (-not $autoStoppedServices) { $autoStoppedServices = @() }

    # Truncate large lists
    $MAX_ITEMS = 200
    if ($iisStopped.Count -gt $MAX_ITEMS) { $iisStopped = $iisStopped[0..($MAX_ITEMS-1)] }
    if ($stoppedPools.Count -gt $MAX_ITEMS) { $stoppedPools = $stoppedPools[0..($MAX_ITEMS-1)] }
    if ($autoStoppedServices.Count -gt $MAX_ITEMS) { $autoStoppedServices = $autoStoppedServices[0..($MAX_ITEMS-1)] }

    $out = @{ 
        Server = $server;
        OSVersion = $osVersion;
        UptimeSeconds = $uptimeSeconds;
        Notes = $notes;
        IISStoppedSites = $iisStopped;
        StoppedAppPools = $stoppedPools;
        AutoStoppedServices = $autoStoppedServices
    }

    $out | ConvertTo-Json -Depth 6
} catch {
    $err = $_.Exception.Message
    @{ Server = $env:COMPUTERNAME; OSVersion = ''; UptimeSeconds = 0; Notes = $err; IISStoppedSites = @(); StoppedAppPools = @(); AutoStoppedServices = @() } | ConvertTo-Json -Depth 6
    Write-Error $err
}
