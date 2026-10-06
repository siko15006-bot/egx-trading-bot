$ErrorActionPreference = "Stop"

$taskName = "EGX_Telegram_Bot"
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $project "bot_handlers.py"
$pythonExe = (Get-Command python).Source
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$action = New-ScheduledTaskAction `
    -Execute $pythonExe `
    -Argument ('"{0}"' -f $scriptPath) `
    -WorkingDirectory $project

# AtLogOn ensures the user's network connection and .env are available after Windows starts.
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
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
    -Description "Run the EGX interactive Telegram advisor after Windows sign-in." `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Host "Task created: $taskName"
Write-Host "Trigger: Windows sign-in for $userId"
Write-Host "Script: $scriptPath"
Write-Host "Log: $(Join-Path $project 'logs\telegram_advisor.log')"
