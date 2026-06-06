# PhytoSense mesh simulation

Runs all 21 mesh members (hub + 20 nodes) as host processes that execute the
**real** routing logic from `firmware/main/gradient_mesh.c`.  A Python broker
stands in for the BLE radio and streams events to a browser viewer.

## Dependencies

| What | Package |
|---|---|
| C compiler | `gcc` with pthreads and `libm` |
| Python ≥ 3.11 | `websockets` (`pip install websockets`) |
| Browser | Chrome, Firefox, or any browser with WebSocket |

```bash
pip install websockets
```

## Build

Run from the **repo root**:

```bash
make -f sim/Makefile
```

Output: `sim/build/phytosense_sim`

## Run

```bash
bash sim/run.sh
```

Then open `sim/viewer.html` in your browser.

The script builds if needed, starts the broker on UDP 7000 / WS 8765, then
launches 21 node processes with 50 ms stagger and waits.  Ctrl-C tears
everything down cleanly.

## Radio model

| Parameter | Value |
|---|---|
| Hard delivery cutoff | 5.0 m |
| Tx power | −40 dBm |
| Path-loss exponent | 2.0 |
| Random loss on in-range links | 5 % |

Gradient-2 nodes are 5.5 m+ from the hub; the 5.0 m cutoff prevents any node
from routing directly to hub and forces multi-hop paths.  Verify by watching
`hop_count` in the hub JSON lines — gradient-2 nodes arrive with `hops=1`,
gradient-3/4 arrive with `hops=2`/`3`.

## Checking multi-hop routing

```bash
tail -f sim/build/hub_stdout.log
```

Expected output:
```
{"node":3,"t":25.84,"h":73.12,"s":54.67,"hops":1,"ts":1234}
{"node":7,"t":24.91,"h":75.44,"s":56.01,"hops":2,"ts":1235}
{"node":11,"t":23.67,"h":77.21,"s":57.88,"hops":3,"ts":1236}
```

If every line shows `hops=0`, MAX_RANGE_M in broker.py is too large.

## Kill / revive a node

Click a node in the side panel and press **kill**.  The broker stops delivering
to it; neighbouring nodes see it drop from their neighbour tables after
`NEIGHBOR_TIMEOUT_MS` (30 s) and reroute.  Press **revive** to bring it back.

## Connecting gateway.py

The hub process writes the same JSON format as the real ESP32 serial output.
Once the sim is running:

```bash
tail -f sim/build/hub_stdout.log | python3 hub/gateway.py
```

gateway.py reads from stdin when `SERIAL_PORT` is set to `-` (you may need a
small patch to support stdin; the pipe approach is left as a future step).

## struct sizes (verified at build time by _Static_assert)

| Struct | Bytes | Python format |
|---|---|---|
| `sim_hdr_t` | 12 | `<HHIb3x` |
| `sensor_data_msg_t` | 19 | `<BBBIfff` |

Note: the original comment in `gradient_mesh.h` said 23 bytes; the correct
packed size is 19 bytes (3 × uint8 + uint32 + 3 × float, no padding).
