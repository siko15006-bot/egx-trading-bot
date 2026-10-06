$ErrorActionPreference = "Stop"

$taskName = "EGX_Daily_Runner"
$scriptPath = "C:\Users\ahmed\Documents\Codex\2026-10-04\1-sshuser-11110000-net-user-sshuser\outputs\daily_runner.py"
$pythonExe = (Get-Command python).Source
$workingDirectory = Split-Path -Parent $scriptPath

$arguments = '"{0}" --data-folder "{1}\data" --capital 100000 --notify --download' -f $scriptPath, $workingDirectory
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument $arguments -WorkingDirectory $workingDirectory
$trigger = New-ScheduledTaskTrigger -Daily -At "14:45"
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force

Write-Host "Task created: $taskName"
Write-Host "Daily run: 14:45 Cairo"
Write-Host "Review: schtasks /query /tn $taskName"
Write-Host "Delete: schtasks /delete /tn $taskName /f"
