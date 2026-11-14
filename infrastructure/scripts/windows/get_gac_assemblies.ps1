# Get GAC Assemblies
$assemblies = [System.AppDomain]::CurrentDomain.GetAssemblies() | Where-Object { $_.GlobalAssemblyCache }
$gac = @()
foreach ($asm in $assemblies) {
    $info = [PSCustomObject]@{
        Name = $asm.GetName().Name
        Version = $asm.GetName().Version.ToString()
        Location = $asm.Location
    LastWriteTime = if ($asm.Location) { (Get-Item $asm.Location).LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss') } else { $null }
    }
    $gac += $info
}
$gac | ConvertTo-Json -Depth 3
