$ErrorActionPreference = "Stop"

$taskName = "EGX_Daily_Runner"
$scriptPath = "C:\Projects\EGX\daily_runner.py"
$pythonExe = (Get-Command python).Source
$workingDirectory = Split-Path -Parent $scriptPath

$arguments = '"{0}" --data-folder "{1}\data" --capital 100000 --notify --download --alert-after 19:30' -f $scriptPath, $workingDirectory
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument $arguments -WorkingDirectory $workingDirectory
$trigger = New-ScheduledTaskTrigger -Daily -At "14:45"
# Retry hourly 14:45-19:45; daily_runner exits early once today succeeded and alerts only after 19:30
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At "14:45" -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Hours 5 -Minutes 5)).Repetition
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force

Write-Host "Task created: $taskName"
Write-Host "Daily run: 14:45 Cairo, hourly retry until 19:45, alert after 19:30"
Write-Host "Review: schtasks /query /tn $taskName"
Write-Host "Delete: schtasks /delete /tn $taskName /f"
