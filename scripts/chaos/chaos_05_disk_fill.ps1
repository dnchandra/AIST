# CHAOS-05: Disk Space Saturation Simulation on Windows Server 2019
# Creates a temporary dummy file to trigger NodeDiskSpaceCritical (<10% free)
Write-Host "=== [CHAOS-05] Simulating Disk Saturation on Windows Server 2019 ===" -ForegroundColor Yellow
$dummyPath = "C:\AIST_Dummy_Fill_Test.tmp"

try {
    Write-Host "Creating temporary 20GB dummy file at $dummyPath..."
    $file = [System.IO.File]::Create($dummyPath)
    $file.SetLength(20GB)
    $file.Close()
    Write-Host "Dummy file created. Disk alert will fire." -ForegroundColor Green
    Write-Host "To clean up later: Remove-Item $dummyPath"
} catch {
    Write-Host "Failed to create dummy file: $_" -ForegroundColor Red
}

