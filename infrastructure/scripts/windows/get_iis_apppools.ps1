Import-Module WebAdministration

Get-ChildItem IIS:\AppPools | ForEach-Object {
    $pool = Get-Item "IIS:\AppPools\$($_.Name)"
    $cpu = $pool.cpu
    $pm = $pool.processModel
    $rfp = $pool.Failure
    $recycle = $pool.Recycling
    [PSCustomObject]@{
        Name                     = $pool.Name
        State                    = $pool.State
    CLRVersion               = $pool.ManagedRuntimeVersion
        PipelineMode             = $pool.ManagedPipelineMode
        Identity                 = $pm.IdentityType
        AutoStart                = $pool.AutoStart
        Enable32BitAppOnWin64    = $pool.Enable32BitAppOnWin64
        OrphanWorkerProcess      = $pm.OrphanWorkerProcess
        # --- ADVANCED ---
        Advanced = @{
            StartMode               = $pool.StartMode
            QueueLength             = $pool.QueueLength
            IdleTimeoutMinutes      = $pm.IdleTimeout.TotalMinutes
            IdleTimeoutAction       = $pm.IdleTimeoutAction
            MaxProcesses            = $pm.MaxProcesses
            LoadUserProfile         = $pm.LoadUserProfile
            ShutdownTimeLimitSec    = $pm.ShutdownTimeLimit.TotalSeconds
            StartupTimeLimitSec     = $pm.StartupTimeLimit.TotalSeconds
            UserName                = $pm.UserName
            CPU = @{
                LimitPercent        = $cpu.Limit
                Action             = $cpu.Action
                ResetIntervalMin   = $cpu.ResetInterval.TotalMinutes
                ProcessorAffinityEnabled = $cpu.ProcessorAffinityEnabled
                ProcessorAffinityMask = $cpu.ProcessorAffinityMask
                ProcessorAffinityMask64 = $cpu.ProcessorAffinityMask64
            }
            RapidFailProtection = @{
                Enabled         = $rfp.RapidFailProtection
                IntervalMin     = $rfp.RapidFailProtectionInterval.TotalMinutes
                MaxFailures     = $rfp.RapidFailProtectionMaxCrashes
                ShutdownExe     = $rfp.ShutdownExe
                ShutdownParams  = $rfp.ShutdownParams
            }
            Recycling = @{
                DisableOverlappedRecycle      = $recycle.DisableOverlappedRecycle
                DisableRecycleOnConfigChange  = $recycle.DisableRecycleOnConfigChange
                LogEventOnRecycle             = $recycle.LogEventOnRecycle
                PrivateMemoryKB               = $recycle.PrivateMemory
                PeriodicRestartTimeMinutes    = $recycle.PeriodicRestart.Time.TotalMinutes
                PeriodicRestartRequests       = $recycle.PeriodicRestart.Requests
                PeriodicRestartSchedule       = $recycle.PeriodicRestart.Schedule
                VirtualMemoryKB               = $recycle.VirtualMemory
            }
        }
    }
} | ConvertTo-Json -Depth 6
