# PhytoSense mesh simulation

Runs all 21 mesh members (hub plus 20 nodes) as host processes that execute the
**real** routing logic from `firmware/main/gradient_mesh.c`. A Python broker
stands in for the BLE radio and streams events to a browser viewer. On top of
that, a localization layer tracks simulated visitors walking through the two
greenhouses.

This guide is written for **native Windows** (PowerShell + MinGW gcc), which is
the supported setup. Linux equivalents are noted where they differ.

## Dependencies

| What | Package |
|---|---|
| C compiler | MinGW `gcc` on PATH (pthreads + libm) |
| Python 3.8+ | `websockets` (`pip install websockets`) |
| Browser | Chrome, Firefox, or anything with WebSocket |

```powershell
pip install websockets
```

Python 3.8 or newer is required, because that is the first version where asyncio
UDP works on the Windows event loop. The conda `torch-gpu` env is fine.

## Layout

The simulation lives in `sim/`. After adding the localization layer, that
directory holds:

```
sim/
  broker.py          radio model + WebSocket + visitor localization
  localization.py    tag motion, RSSI sensing, position estimators
  viewer.html        mesh + visitor map
  dashboard.html     staff alert view
  build.ps1          builds the C node binary (Windows)
  run.ps1            builds if needed, starts broker + 21 nodes (Windows)
  Makefile, run.sh   Linux equivalents
```

`localization.py` has to sit next to `broker.py`, because `broker.py` imports it
by name. Nothing else needs to move.

## Build

The node binary is C and needs compiling. The broker and localization are pure
Python and do not.

```powershell
powershell -ExecutionPolicy Bypass -File sim\build.ps1
```

Output: `sim\build\phytosense_sim.exe`. The script links the MinGW runtime
statically (`-static`), so the exe runs from any shell without the MinGW `bin`
folder on PATH.

## Run

```powershell
powershell -ExecutionPolicy Bypass -File sim\run.ps1
```

It builds if the exe is missing, starts the broker on UDP 7000 / WS 8765, then
launches 21 node processes with a 50 ms stagger. Open `sim\viewer.html` in a
browser. Ctrl-C in the PowerShell window stops everything.

Watch the hub output (the Windows version of `tail -f`):

```powershell
Get-Content -Wait sim\build\hub_stdout.log
```

First readings appear about 15 seconds in, then every 60 seconds, with `hops`
climbing by gradient ring.

## Radio model (mesh routing)

| Parameter | Value |
|---|---|
| Hard delivery cutoff | 5.0 m |
| Tx power | -40 dBm |
| Path-loss exponent | 2.0 |
| Random loss on in-range links | 5 % |

Gradient-2 nodes sit 5.5 m or more from the hub, so the 5.0 m cutoff stops any
node from routing straight to the hub and forces multi-hop paths. Confirm it by
watching `hop_count` in the hub JSON: gradient-1 arrives at `hops=0`, gradient-2
at `hops=1`, and so on to gradient-4 at `hops=3`.

If every line shows `hops=0`, `MAX_RANGE_M` in `broker.py` is too large.

## Visitor localization

The architecture is the self-contained band. The fixed nodes constantly beacon
their ID and known position. A visitor's band listens, works out where it is on
its own, and drives its own display of nearby plants. No position ever leaves the
band, so there is nothing to route back and nothing to track, and the system
scales to any crowd because the nodes beacon on a fixed schedule no matter how
many bands are listening.

The accuracy is identical to a node hearing the band, because the radio path is
the same in both directions (reciprocity). The estimator itself lives in
`localization.py` (weighted centroid, RSSI trilateration, and a fused solver that
tethers trilateration to the centroid); on real hardware it runs on the band. In
the sim it is the band's own algorithm, kept for reference. The earlier accuracy
study settled at roughly 1 m typical, which clears the zone-level need.

### Two views, on purpose

- **The map (`viewer.html`)** is the sim's god's-eye debug view. It draws every
  person as a moving dot at their true position, over the node mesh and live
  routing traffic. This is ground truth, what the simulator knows, not what the
  hub knows.
- **The staff dashboard (`dashboard.html`)** is the realistic product view. It
  never sees individuals. It shows the sensor cards plus a crowd heatmap built
  only from per-node ack counts. Density, not people.

That split is the privacy model made visible: the map (the sim) can see
everyone, the dashboard (the real deployment) sees only how busy each node is.

### Knobs (in `localization.py`)

| Constant | Meaning |
|---|---|
| `LOC_RANGE_M` | how far a node hears a band (18 m). Larger than the 5 m mesh cutoff on purpose, since real BLE reception reaches much further than that artificial routing limit. |
| `RSSI_NOISE_DB` | std-dev of per-chirp noise (4 dB). Raise it to see the estimate degrade. |
| `LOC_TOPK` | how many of the strongest anchors the fused solver uses (6). |
| `LOC_REG_BETA` | how hard the fused estimate is tethered to the centroid (2.0). |
| `LOC_SMOOTH_ALPHA` | temporal smoothing (0.4). Lower is smoother but laggier. |
| `LOC_AVG_WINDOW` | chirps averaged per anchor (1 = off). Helps a stationary band, lags a moving one. |
| `default_tags()` / `crowd_tags()` | the people and their paths. |

The sim has no wall model yet, so a Julia node can currently hear a band in Romeo
across the hub. Real glass-and-metal separation would block much of that. Adding
attenuation between the two houses is the next bit of realism if the numbers
start to matter.

Kill a node from the map side panel and it stops hearing acks, so its crowd count
drops to zero and it goes dark on the heatmap.

## Crowd heatmap

Even though the band keeps its position to itself, staff still get a crowd view,
without tracking anyone. Each band sends a tiny ack to its nearest node. Each
node counts how many bands acked it recently, and that count rides the existing
sensor mesh up to the hub as one more field beside temperature and humidity. The
hub turns the per-node counts into a live density map. No position is ever sent,
so this is crowd density, not people.

The heatmap lives on the staff dashboard (`dashboard.html`), above the sensor
cards: a compact node map where busy nodes glow, sized by how many bands are near
them, plus Romeo, Julia, and total head counts in the header. The sim drives it
with a wandering crowd; `CROWD_SIZE` in `broker.py` is the dial, so turn it up to
load-test the picture. Because each band is counted once at its single nearest
node, the totals are a true head count, not a smeared one.

Two policy choices are left simple on purpose, since this is a project build. The
ack here carries the band id, so the totals are exact; rotating that id every
minute would keep the head count while making individuals unfollowable. And
counting at the nearest node only gives crowd-per-zone; acking every node in
range instead would give a smoother density field at the cost of double-counting.

## Staff dashboard

```powershell
Get-Content -Wait sim\build\hub_stdout.log | python hub\gateway.py -
```

`gateway.py` reads stdin when `SERIAL_PORT` is `-`. If PySide6 will not start
because of a conda Qt DLL clash, open `sim\dashboard.html` instead. It connects
to the same broker WebSocket and uses the identical alert thresholds, with no
install.

## Struct sizes (checked at build time by `_Static_assert`)

| Struct | Bytes | Python format |
|---|---|---|
| `sim_hdr_t` | 12 | `<HHIb3x` |
| `sensor_data_msg_t` | 19 | `<BBBIfff` |