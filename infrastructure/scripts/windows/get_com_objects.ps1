

# Get COM+ Application details (Name, Application ID, Authentication, Impersonation, Account, Activation, Shutdown, RunAll, Proxy, Enabled)
$comApps = @()
$catalog = New-Object -ComObject COMAdmin.COMAdminCatalog
$apps = $catalog.GetCollection('Applications')
$apps.Populate()

# Mapping tables for Authentication, Impersonation, and Activation
$authMap = @{
    0 = 'Default'
    1 = 'None'
    2 = 'Connect'
    3 = 'Call'
    4 = 'Packet'
    5 = 'Integrity'
    6 = 'Packet Privacy'
}
$impMap = @{
    1 = 'Anonymous'
    2 = 'Identify'
    3 = 'Impersonate'
    4 = 'Delegate'
}
$activationMap = @{
    0 = 'Library'
    1 = 'Server'
}

foreach ($app in $apps) {
    $Name = $null; $ApplicationID = $null; $Authentication = $null; $Impersonation = $null; $Account = $null; $Activation = $null; $Shutdown = $null; $RunAll = $null; $Proxy = $null; $Enabled = $null;
    try { $Name = $app.Value('Name') } catch { $Name = $null }
    try { $ApplicationID = $app.Value('ID') } catch { $ApplicationID = $null }
    try { $Authentication = $app.Value('Authentication') } catch { $Authentication = $null }
    try { $Impersonation = $app.Value('ImpersonationLevel') } catch { $Impersonation = $null }
    try { $Account = $app.Value('Identity') } catch { $Account = $null }
    try { $Activation = $app.Value('Activation') } catch { $Activation = $null }
    try { $Shutdown = $app.Value('ShutdownAfter') } catch { $Shutdown = $null }
    try { $RunAll = $app.Value('RunForever') } catch { $RunAll = $null }
    
    # For Proxy: COM+ applications are typically not proxy applications
    # The Component Services UI shows "No" for most applications
    try { 
        $Proxy = $app.Value('IsProxyApp') 
    } catch { 
        try { 
            $Proxy = $app.Value('Proxy') 
        } catch { 
            # Default to false (No) as shown in Component Services for most apps
            $Proxy = $false
        }
    }
    
    # For Enabled: Use IsEnabled property which we confirmed works
    try { 
        $Enabled = $app.Value('IsEnabled') 
    } catch { 
        # Default to true (Yes) if property is not accessible
        $Enabled = $true
    }

    # Map codes to friendly names
    $AuthenticationStr = if ($null -ne $Authentication -and $authMap.ContainsKey([int]$Authentication)) { $authMap[[int]$Authentication] } else { $Authentication }
    $ImpersonationStr = if ($null -ne $Impersonation -and $impMap.ContainsKey([int]$Impersonation)) { $impMap[[int]$Impersonation] } else { $Impersonation }
    $ActivationStr = if ($null -ne $Activation -and $activationMap.ContainsKey([int]$Activation)) { $activationMap[[int]$Activation] } else { $Activation }

    $comApps += [PSCustomObject]@{
        Name = $Name
        ApplicationID = $ApplicationID
        Authentication = $AuthenticationStr
        Impersonation = $ImpersonationStr
        Account = $Account
        Activation = $ActivationStr
        Shutdown = $Shutdown
        RunAll = $RunAll
        Proxy = $Proxy
        Enabled = $Enabled
    }
}
$comApps | ConvertTo-Json -Depth 3
