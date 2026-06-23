# Build the PhytoSense mesh simulation natively on Windows with MinGW gcc.
# Run from anywhere; it locates the repo root from its own path.
$ErrorActionPreference = "Stop"

$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo

New-Item -ItemType Directory -Force -Path "sim\build" | Out-Null

$cc     = "gcc"
$cflags = @(
    "-Wall", "-Wextra", "-DHOST_SIM",
    "-I", "sim/shims",
    "-I", "sim",
    "-I", "firmware/main",
    "-g", "-O2", "-pthread",
    # Link the MinGW runtime (libwinpthread, libgcc) statically so the exe runs
    # from any shell without the MinGW bin directory on PATH.
    "-static"
)
$srcs = @(
    "firmware/main/gradient_mesh.c",
    "sim/transport.c",
    "sim/sensors_sim.c",
    "sim/node_main.c"
)
# Libraries last; ws2_32 supplies Winsock (socket, bind, recvfrom, ...).
$ldlibs = @("-pthread", "-lm", "-lws2_32")

& $cc @cflags -o "sim/build/phytosense_sim.exe" @srcs @ldlibs
if ($LASTEXITCODE -ne 0) { throw "Build failed (exit $LASTEXITCODE)" }

Write-Host "Built: sim\build\phytosense_sim.exe"