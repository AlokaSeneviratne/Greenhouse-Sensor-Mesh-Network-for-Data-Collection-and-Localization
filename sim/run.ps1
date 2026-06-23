# PhytoSense mesh simulation launcher (Windows / PowerShell).
# Builds if needed, starts the broker, spawns all 21 node processes.
# Press Ctrl-C in this window to stop everything.
$ErrorActionPreference = "Stop"

$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo

$bin = "sim\build\phytosense_sim.exe"

# ---- Build if the binary is missing ----
if (-not (Test-Path $bin)) {
    Write-Host ">>> Building node binary..."
    & powershell -ExecutionPolicy Bypass -File "sim\build.ps1"
}

New-Item -ItemType Directory -Force -Path "sim\build" | Out-Null

# ---- Start broker ----
Write-Host ">>> Starting broker (UDP:7000  WS:8765)..."
$broker = Start-Process -FilePath "python" -ArgumentList "sim\broker.py" `
                        -NoNewWindow -PassThru
Start-Sleep -Seconds 2   # give the broker time to bind its ports

# ---- Node table: NODE_ID, GRADIENT_LEVEL ----
$nodes = @(
    @(0,0),
    @(1,1), @(2,1),
    @(3,2), @(4,2), @(5,2), @(6,2),
    @(7,3), @(8,3), @(9,3), @(10,3),
    @(11,4), @(12,4),
    @(13,1), @(14,1),
    @(15,2), @(16,2), @(17,2),
    @(18,3), @(19,3), @(20,3)
)

$procs = @()

Write-Host ">>> Launching 21 node processes..."
foreach ($n in $nodes) {
    $nid  = $n[0]
    $grad = $n[1]

    # Start-Process inherits the current process environment, so set these
    # immediately before each spawn.
    $env:NODE_ID        = "$nid"
    $env:GRADIENT_LEVEL = "$grad"

    if ($nid -eq 0) {
        # Hub: stdout (the JSON feed) goes to a log file for gateway.py
        $p = Start-Process -FilePath $bin -NoNewWindow -PassThru `
                 -RedirectStandardOutput "sim\build\hub_stdout.log" `
                 -RedirectStandardError  "sim\build\node_0.log"
    } else {
        $p = Start-Process -FilePath $bin -NoNewWindow -PassThru `
                 -RedirectStandardOutput "sim\build\node_${nid}_out.log" `
                 -RedirectStandardError  "sim\build\node_${nid}.log"
    }
    $procs += $p
    Start-Sleep -Milliseconds 50   # stagger to avoid port-bind races
}

Write-Host ""
Write-Host ">>> All 21 nodes running."
Write-Host ">>> Hub JSON output: sim\build\hub_stdout.log"
Write-Host ">>> Open sim\viewer.html in your browser to watch the mesh."
Write-Host ">>> Live dashboard:  Get-Content -Wait sim\build\hub_stdout.log | python hub\gateway.py -"
Write-Host ""
Write-Host "Press Ctrl-C to stop all processes."

# ---- Wait, then clean up ----
try {
    Wait-Process -Id $broker.Id
} finally {
    Write-Host ""
    Write-Host ">>> Stopping all processes..."
    foreach ($p in $procs) {
        Stop-Process -Id $p.Id -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $broker.Id -ErrorAction SilentlyContinue
    Write-Host ">>> Done."
}