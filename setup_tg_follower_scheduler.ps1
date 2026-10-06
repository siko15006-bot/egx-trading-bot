$ErrorActionPreference = "Stop"

$taskName = "EGX_TG_Follower"
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $project "tg_follower.py"
$pythonExe = (Get-Command python).Source
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$action = New-ScheduledTaskAction `
    -Execute $pythonExe `
    -Argument ('"{0}"' -f $scriptPath) `
    -WorkingDirectory $project

# AtLogOn ensures the user's network connection and .env are available after Windows starts.
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
# Startup order after sign-in: bot 30s, follower 45s, dashboard 1m, watchdog 2m
$trigger.Delay = "PT45S"
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Description "Follow EGX Telegram signal groups and forward signals to Ahmed." `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Host "Task created: $taskName"
Write-Host "Trigger: Windows sign-in for $userId"
Write-Host "Script: $scriptPath"
Write-Host "Log: $(Join-Path $project 'logs\tg_follower.log')"
