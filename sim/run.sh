#!/usr/bin/env bash
# PhytoSense mesh simulation launcher
# Builds the node binary, starts the broker, then spawns all 21 node processes.
# Press Ctrl-C to tear everything down cleanly.

set -euo pipefail
cd "$(dirname "$0")/.."    # repo root

BIN="sim/build/phytosense_sim"
BROKER="sim/broker.py"

# ---- Build ----------------------------------------------------------------
echo ">>> Building node binary…"
make -f sim/Makefile
echo

# ---- Start broker ---------------------------------------------------------
echo ">>> Starting broker (UDP:7000  WS:8765)…"
python3 "$BROKER" &
BROKER_PID=$!
sleep 1   # give broker time to bind its ports

# ---- Node table: (NODE_ID GRADIENT_LEVEL) ---------------------------------
declare -a NODES=(
    "0 0"                                       # hub
    "1 1"  "2 1"                                # Romeo g1
    "3 2"  "4 2"  "5 2"  "6 2"                 # Romeo g2
    "7 3"  "8 3"  "9 3"  "10 3"                # Romeo g3
    "11 4" "12 4"                               # Romeo g4
    "13 1" "14 1"                               # Julia g1
    "15 2" "16 2" "17 2"                        # Julia g2
    "18 3" "19 3" "20 3"                        # Julia g3
)

NODE_PIDS=()

echo ">>> Launching 21 node processes…"
for ENTRY in "${NODES[@]}"; do
    read -r NID GRAD <<< "$ENTRY"

    if [[ "$NID" -eq 0 ]]; then
        # Hub: pipe stdout to a log file so gateway.py can read it later
        NODE_ID="$NID" GRADIENT_LEVEL="$GRAD" "$BIN" \
            > sim/build/hub_stdout.log 2>> sim/build/node_${NID}.log &
    else
        NODE_ID="$NID" GRADIENT_LEVEL="$GRAD" "$BIN" \
            > /dev/null 2>> sim/build/node_${NID}.log &
    fi

    NODE_PIDS+=($!)
    sleep 0.05   # 50 ms stagger to avoid port-bind races
done

echo
echo ">>> All 21 nodes running."
echo ">>> Hub JSON output: sim/build/hub_stdout.log"
echo ">>> Open sim/viewer.html in Chrome/Firefox to watch the mesh."
echo ">>> (gateway.py can be pointed at hub_stdout.log via tail -f | python3 hub/gateway.py)"
echo
echo "Press Ctrl-C to stop all processes."

# ---- Cleanup on exit -------------------------------------------------------
cleanup() {
    echo
    echo ">>> Stopping all processes…"
    kill "${NODE_PIDS[@]}" 2>/dev/null || true
    kill "$BROKER_PID"     2>/dev/null || true
    wait 2>/dev/null || true
    echo ">>> Done."
}
trap cleanup EXIT INT TERM

# Wait until killed
wait "$BROKER_PID"
