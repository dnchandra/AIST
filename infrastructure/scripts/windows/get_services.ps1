Get-CimInstance -ClassName Win32_Service |
    Select-Object Name, DisplayName, State, StartMode, StartName |
    ConvertTo-Json -Depth 3
