#!/usr/bin/env python3
"""
PhytoSense simulation broker.

Receives UDP datagrams from all 21 node processes, models BLE radio propagation,
delivers packets to eligible receivers, and streams events to the web viewer over
WebSocket.

Ports
-----
  UDP 7000  : inbound from all nodes (broker listens here)
  UDP 7100+N : outbound to node N (broker sends here; node N binds this port)
  WS  8765  : WebSocket for viewer.html

Wire datagram format (12-byte header, little-endian)
-----------------------------------------------------
  H  src_addr   sender unicast
  H  dst_addr   destination unicast or 0xC000 (group)
  I  opcode     3-byte opcode as uint32
  b  rssi       int8; 0 when sent by node; broker fills before delivery
  3x pad

Sensor data payload  (19 bytes, '<BBBIfff')
  B  origin_node_id
  B  origin_gradient
  B  hop_count
  I  timestamp_s
  f  temperature_c
  f  humidity_pct
  f  soil_moisture_pct

Radio model
-----------
  Hard delivery cutoff: MAX_RANGE_M = 5.0 m
  All nodes ≤5.0 m receive the packet; nodes beyond are silently dropped.
  RSSI within range: rssi = TX_POWER - 10·n·log10(d)
  This feeds best_parent() tie-breaking so physically closer nodes win.
  Optional mild packet loss (LOSS_PCT %) on in-range links.
"""

import asyncio
import json
import logging
import math
import random
import struct
import time
from collections import defaultdict

import websockets

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
LOG = logging.getLogger("broker")

# ---------------------------------------------------------------------------
# Ports and radio constants
# ---------------------------------------------------------------------------
BROKER_UDP_PORT    = 7000
NODE_RECV_BASE     = 7100
WS_PORT            = 8765

MAX_RANGE_M   = 5.0    # hard delivery cutoff
TX_POWER_DBM  = -40.0  # representative indoor BLE Tx power
PATH_LOSS_EXP = 2.0    # indoor path-loss exponent
LOSS_PCT      = 5.0    # random per-packet loss on in-range links (%)

# ---------------------------------------------------------------------------
# Topology (mirrors firmware/main/topology.h)
# ---------------------------------------------------------------------------
# Each entry: node_id → (x_m, y_m, gradient, location)
TOPOLOGY = {
     0: ( 0.0,  0.0, 0, 'H'),
     1: ( 2.5,  1.5, 1, 'R'),  2: ( 2.5, -1.5, 1, 'R'),
     3: ( 5.5,  3.0, 2, 'R'),  4: ( 5.5,  1.0, 2, 'R'),
     5: ( 5.5, -1.0, 2, 'R'),  6: ( 5.5, -3.0, 2, 'R'),
     7: ( 9.0,  3.5, 3, 'R'),  8: ( 9.0,  1.2, 3, 'R'),
     9: ( 9.0, -1.2, 3, 'R'), 10: ( 9.0, -3.5, 3, 'R'),
    11: (13.0,  1.5, 4, 'R'), 12: (13.0, -1.5, 4, 'R'),
    13: (-2.5,  1.5, 1, 'J'), 14: (-2.5, -1.5, 1, 'J'),
    15: (-5.5,  2.5, 2, 'J'), 16: (-5.5,  0.0, 2, 'J'),
    17: (-5.5, -2.5, 2, 'J'),
    18: (-9.0,  2.0, 3, 'J'), 19: (-9.0,  0.0, 3, 'J'),
    20: (-9.0, -2.0, 3, 'J'),
}

# unicast address ↔ node_id
def addr_to_nid(addr: int) -> int:  return addr - 1
def nid_to_addr(nid: int)  -> int:  return nid + 1

GROUP_ADDR = 0xC000   # all-nodes multicast

# ---------------------------------------------------------------------------
# Opcodes (must match ESP_BLE_MESH_MODEL_OP_3 macro and shim encoding)
# ---------------------------------------------------------------------------
OP_SENSOR_DATA  = (0xC0 << 16) | 0x05C3   # 0x00C005C3
OP_GRADIENT_ADV = (0xC1 << 16) | 0x05C3   # 0x00C105C3
OP_GRADIENT_SET = (0xC2 << 16) | 0x05C3   # 0x00C205C3

OPCODE_NAMES = {
    OP_SENSOR_DATA:  "SENSOR_DATA",
    OP_GRADIENT_ADV: "GRADIENT_ADV",
    OP_GRADIENT_SET: "GRADIENT_SET",
}

HDR_FMT    = '<HHIb3x'   # 12 bytes
HDR_SIZE   = struct.calcsize(HDR_FMT)    # must be 12

SENSOR_FMT  = '<BBBIfff'  # 19 bytes: origin_node_id, origin_gradient, hop_count,
SENSOR_SIZE = struct.calcsize(SENSOR_FMT)  # timestamp_s, temp, hum, soil

assert HDR_SIZE   == 12, f"HDR_SIZE={HDR_SIZE}"
assert SENSOR_SIZE == 19, f"SENSOR_SIZE={SENSOR_SIZE}"

# ---------------------------------------------------------------------------
# Radio model
# ---------------------------------------------------------------------------

def _dist(nid_a: int, nid_b: int) -> float:
    xa, ya, *_ = TOPOLOGY[nid_a]
    xb, yb, *_ = TOPOLOGY[nid_b]
    return math.sqrt((xa - xb) ** 2 + (ya - yb) ** 2)

def _rssi(dist_m: float) -> int:
    d = max(dist_m, 0.1)
    val = TX_POWER_DBM - 10.0 * PATH_LOSS_EXP * math.log10(d)
    return max(-128, min(127, int(val)))

def _can_deliver(dist_m: float) -> bool:
    if dist_m > MAX_RANGE_M:
        return False
    if random.random() < LOSS_PCT / 100.0:
        return False   # mild random loss on in-range links
    return True

# Pre-compute reachable neighbours for every node (static topology)
# neighbours[nid] = list of (nid, rssi)
_neighbours: dict[int, list[tuple[int, int]]] = {}
for _src in TOPOLOGY:
    _neighbours[_src] = []
    for _dst in TOPOLOGY:
        if _dst == _src:
            continue
        d = _dist(_src, _dst)
        if d <= MAX_RANGE_M:
            _neighbours[_src].append((_dst, _rssi(d)))

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

class BrokerState:
    def __init__(self):
        self.dead_nodes: set[int] = set()          # killed via WS control
        # Latest sensor reading per node (origin_node_id → dict)
        self.readings:   dict[int, dict] = {}
        # WS clients
        self.ws_clients: set = set()
        # Transport: set from asyncio loop
        self.transport = None

    def node_alive(self, nid: int) -> bool:
        return nid not in self.dead_nodes

STATE = BrokerState()

# ---------------------------------------------------------------------------
# WebSocket helpers
# ---------------------------------------------------------------------------

async def ws_broadcast(msg: dict) -> None:
    if not STATE.ws_clients:
        return
    data = json.dumps(msg)
    dead = set()
    for ws in STATE.ws_clients:
        try:
            await ws.send(data)
        except Exception:
            dead.add(ws)
    STATE.ws_clients -= dead

def _topology_msg() -> dict:
    """Full topology snapshot for new WebSocket connections."""
    nodes = []
    for nid, (x, y, g, loc) in TOPOLOGY.items():
        nodes.append({
            "id": nid, "gradient": g, "x": x, "y": y,
            "location": loc, "alive": STATE.node_alive(nid),
        })

    links = []
    for src_nid in TOPOLOGY:
        for dst_nid, rssi in _neighbours[src_nid]:
            if dst_nid > src_nid:   # report each link once
                links.append({"from": src_nid, "to": dst_nid, "rssi": rssi})

    return {"type": "topology", "nodes": nodes, "links": links}

# ---------------------------------------------------------------------------
# UDP protocol
# ---------------------------------------------------------------------------

class NodeUDPProtocol(asyncio.DatagramProtocol):
    def __init__(self):
        self._transport = None

    def connection_made(self, transport):
        self._transport = transport
        STATE.transport = transport
        LOG.info("UDP broker listening on port %d", BROKER_UDP_PORT)

    def datagram_received(self, data: bytes, addr):
        if len(data) < HDR_SIZE:
            return

        src_addr, dst_addr, opcode, rssi_in = struct.unpack_from(HDR_FMT, data)
        payload = data[HDR_SIZE:]

        src_nid = addr_to_nid(src_addr)
        if src_nid not in TOPOLOGY:
            return

        # Schedule async handling (can't await from sync callback)
        asyncio.get_event_loop().create_task(
            _handle_packet(src_nid, dst_addr, opcode, payload)
        )

    def error_received(self, exc):
        LOG.warning("UDP error: %s", exc)


async def _handle_packet(src_nid: int, dst_addr: int, opcode: int, payload: bytes):
    """Deliver packet to all eligible receivers; emit WS events."""
    if not STATE.node_alive(src_nid):
        return

    # Resolve target node IDs
    if dst_addr == GROUP_ADDR:
        targets = list(TOPOLOGY.keys())
    else:
        targets = [addr_to_nid(dst_addr)]

    op_name = OPCODE_NAMES.get(opcode, f"0x{opcode:08X}")

    for dst_nid in targets:
        if dst_nid == src_nid:
            continue
        if dst_nid not in TOPOLOGY:
            continue
        if not STATE.node_alive(dst_nid):
            continue

        # Check radio range (skip random-loss check for group adverts to keep
        # gradient table stable; loss only applies to data/unicast)
        dist = _dist(src_nid, dst_nid)
        if opcode == OP_GRADIENT_ADV:
            if dist > MAX_RANGE_M:
                continue
            rssi_out = _rssi(dist)
        else:
            if not _can_deliver(dist):
                continue
            rssi_out = _rssi(dist)

        # Deliver: rebuild datagram with broker-stamped RSSI
        src_addr = nid_to_addr(src_nid)
        out_hdr  = struct.pack(HDR_FMT, src_addr, nid_to_addr(dst_nid),
                                opcode, rssi_out)
        datagram = out_hdr + payload

        recv_port = NODE_RECV_BASE + dst_nid
        try:
            STATE.transport.sendto(datagram, ("127.0.0.1", recv_port))
        except Exception as exc:
            LOG.debug("sendto node%d: %s", dst_nid, exc)

        # WS: packet event (hop animation)
        await ws_broadcast({
            "type":    "packet",
            "from_id": src_nid,
            "to_id":   dst_nid,
            "opcode":  op_name,
            "rssi":    rssi_out,
        })

        # WS: decode sensor data so the viewer has readings without waiting
        # for the hub to print JSON to stdout
        if opcode == OP_SENSOR_DATA and len(payload) >= SENSOR_SIZE:
            nid_o, grad_o, hops, ts, temp, hum, soil = struct.unpack_from(
                SENSOR_FMT, payload)
            STATE.readings[nid_o] = {
                "id": nid_o, "t": round(temp, 2),
                "h": round(hum, 2), "s": round(soil, 2),
                "hops": hops,
            }
            await ws_broadcast({
                "type": "node_update",
                "id": nid_o, "t": round(temp, 2),
                "h": round(hum, 2), "s": round(soil, 2),
                "hops": hops,
            })

# ---------------------------------------------------------------------------
# WebSocket handler
# ---------------------------------------------------------------------------

async def ws_handler(websocket):
    STATE.ws_clients.add(websocket)
    LOG.info("WS client connected (%d total)", len(STATE.ws_clients))

    try:
        # Send topology on connect
        await websocket.send(json.dumps(_topology_msg()))

        # Send any readings we already have
        for nid, r in STATE.readings.items():
            await websocket.send(json.dumps({"type": "node_update", **r}))

        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            action = msg.get("type")
            nid    = int(msg.get("id", -1))

            if action == "kill" and nid in TOPOLOGY:
                STATE.dead_nodes.add(nid)
                LOG.info("Node %d killed", nid)
                await ws_broadcast({"type": "alive", "id": nid, "alive": False})

            elif action == "revive" and nid in TOPOLOGY:
                STATE.dead_nodes.discard(nid)
                LOG.info("Node %d revived", nid)
                await ws_broadcast({"type": "alive", "id": nid, "alive": True})

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        STATE.ws_clients.discard(websocket)
        LOG.info("WS client disconnected (%d remaining)", len(STATE.ws_clients))

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    loop = asyncio.get_event_loop()

    # UDP server
    udp_transport, _ = await loop.create_datagram_endpoint(
        NodeUDPProtocol,
        local_addr=("0.0.0.0", BROKER_UDP_PORT),
    )

    # WebSocket server
    ws_server = await websockets.serve(ws_handler, "0.0.0.0", WS_PORT)
    LOG.info("WebSocket server on ws://localhost:%d", WS_PORT)
    LOG.info("Open sim/viewer.html in a browser to see the live mesh")

    try:
        await asyncio.Future()   # run forever
    finally:
        udp_transport.close()
        ws_server.close()


if __name__ == "__main__":
    asyncio.run(main())
