$ErrorActionPreference = "Stop"

$taskName = "EGX_Streamlit_Dashboard"
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = Join-Path (Split-Path -Parent (Get-Command python).Source) "pythonw.exe"
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$action = New-ScheduledTaskAction `
    -Execute $pythonw `
    -Argument "-m streamlit run egx_dashboard.py --server.address=0.0.0.0 --server.port=8501 --server.headless=true" `
    -WorkingDirectory $project

# AtLogOn, not AtStartup: an Interactive task with a boot trigger is skipped because nobody is signed in yet.
# Startup order after sign-in: bot 30s, dashboard 1m, watchdog 2m.
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$trigger.Delay = "PT1M"
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
    -Description "Run the EGX Streamlit dashboard (LAN, port 8501) after Windows sign-in." `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Host "Task created: $taskName"
Write-Host "Trigger: Windows sign-in for $userId (+1 min)"
Write-Host "URL: http://127.0.0.1:8501"
