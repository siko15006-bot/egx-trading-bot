$ErrorActionPreference = "Stop"

$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$dashboard = Join-Path $project "egx_dashboard.py"
$logs = Join-Path $project "logs"
$port = 8501
$pythonExe = (Get-Command python).Source

New-Item -ItemType Directory -Path $logs -Force | Out-Null

# Stop only an existing instance of this dashboard; never take over an unrelated service.
$listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
foreach ($processId in @($listeners.OwningProcess | Sort-Object -Unique)) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
    if ($process.CommandLine -match "streamlit" -and $process.CommandLine -match "egx_dashboard\.py") {
        Stop-Process -Id $processId -Force
    } else {
        throw "Port $port is already used by another application (PID $processId)."
    }
}

# Use the adapter that owns the default IPv4 route, normally Wi-Fi or Ethernet.
$route = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix "0.0.0.0/0" |
    Sort-Object RouteMetric |
    Select-Object -First 1
if (-not $route) {
    throw "No active local IPv4 network was found."
}
$localIp = Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $route.InterfaceIndex |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -ExpandProperty IPAddress -First 1
if (-not $localIp) {
    throw "The active network adapter has no usable IPv4 address."
}

$env:EGX_MOBILE_MODE = "1"
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"
$stdout = Join-Path $logs "mobile_dashboard_stdout.log"
$stderr = Join-Path $logs "mobile_dashboard_stderr.log"
$arguments = @(
    "-m", "streamlit", "run", $dashboard,
    "--server.address", "0.0.0.0",
    "--server.port", "$port",
    "--server.headless", "true",
    "--browser.gatherUsageStats", "false"
)
$process = Start-Process -FilePath $pythonExe -ArgumentList $arguments -WorkingDirectory $project `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru

$ready = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Seconds 1
    if ($process.HasExited) { break }
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$port/_stcore/health" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {}
}
if (-not $ready) {
    throw "Dashboard failed to start. Review $stderr"
}

$mobileUrl = "http://${localIp}:$port"
Write-Host "Dashboard PID: $($process.Id)"
Write-Host "Local laptop URL: http://127.0.0.1:$port"
Write-Host "Mobile URL: $mobileUrl"
Write-Warning "Local network only. Do not expose or forward port $port to the Internet."
