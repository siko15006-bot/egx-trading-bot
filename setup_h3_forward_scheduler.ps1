$ErrorActionPreference = "Stop"

$taskName = "EGX_H3_Forward"
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $project "h3_forward.py"
$pythonExe = (Get-Command python).Source
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$action = New-ScheduledTaskAction -Execute $pythonExe -Argument ('"{0}"' -f $scriptPath) -WorkingDirectory $project
# After the daily runner's last retry (19:45); the script itself decides if a rebalance is due (every 21 sessions).
$trigger = New-ScheduledTaskTrigger -Daily -At "20:15"
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Description "H3 AI Score forward test (no money): rebalance every 21 sessions." `
    -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "Task created: $taskName (daily 20:15)"
