#!/usr/bin/env python3
"""
PhytoSense Hub Gateway

Reads newline-delimited JSON records from the hub ESP32 over USB serial and
writes them to InfluxDB.  The hub ESP32 (NODE_ID=0, GRADIENT_LEVEL=0) is the
BLE Mesh member that receives every sensor_data_msg_t forwarded to gradient 0
and prints it as JSON via UART.

Expected JSON line format (one per sensor reading received):
  {"node":N,"t":T,"h":H,"s":S,"hops":N,"ts":N}

Run on Raspberry Pi:
  pip install -r requirements.txt
  python3 gateway.py
"""

import json
import logging
import time
from datetime import datetime, timezone

import serial
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

LOG = logging.getLogger("gateway")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# ---- Site configuration ----
SERIAL_PORT   = "/dev/ttyUSB0"
SERIAL_BAUD   = 115200

INFLUX_URL    = "http://localhost:8086"
INFLUX_TOKEN  = "your-influxdb-token"     # replace with actual token
INFLUX_ORG    = "phytosense"
INFLUX_BUCKET = "greenhouse"

# Node → greenhouse mapping (mirrors topology.h)
GREENHOUSE = {
    **{i: "romeo" for i in range(1, 13)},   # nodes  1-12 → Romeo
    **{i: "julia" for i in range(13, 21)},  # nodes 13-20 → Julia
}

# Node → gradient level (mirrors topology.h)
GRADIENT = {
     0: 0,
     1: 1,  2: 1,
     3: 2,  4: 2,  5: 2,  6: 2,
     7: 3,  8: 3,  9: 3, 10: 3,
    11: 4, 12: 4,
    13: 1, 14: 1,
    15: 2, 16: 2, 17: 2,
    18: 3, 19: 3, 20: 3,
}

# Sensor alert thresholds (greenhouse staff can adjust these)
THRESHOLDS = {
    "temperature_c":    {"min": 10.0, "max": 35.0},
    "humidity_pct":     {"min": 40.0, "max": 95.0},
    "soil_moisture_pct": {"min": 20.0, "max": 100.0},
}


def check_alerts(node_id: int, reading: dict) -> None:
    for field, bounds in THRESHOLDS.items():
        val = reading.get(field)
        if val is None:
            continue
        if val < bounds["min"] or val > bounds["max"]:
            LOG.warning("ALERT node %d  %s=%.1f  (bounds %.1f–%.1f)",
                        node_id, field, val, bounds["min"], bounds["max"])


def write_to_influx(write_api, record: dict) -> None:
    node_id    = record["node"]
    greenhouse = GREENHOUSE.get(node_id, "unknown")
    gradient   = GRADIENT.get(node_id, -1)

    point = (
        Point("sensor_reading")
        .tag("node_id",    str(node_id))
        .tag("greenhouse", greenhouse)
        .tag("gradient",   str(gradient))
        .field("temperature_c",     record["t"])
        .field("humidity_pct",      record["h"])
        .field("soil_moisture_pct", record["s"])
        .field("hop_count",         record.get("hops", 0))
        .time(datetime.now(timezone.utc), WritePrecision.SECONDS)
    )

    write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)

    LOG.info("Node %2d (%s g%d) | T=%5.1f°C  H=%5.1f%%  S=%5.1f%%  hops=%d",
             node_id, greenhouse, gradient,
             record["t"], record["h"], record["s"],
             record.get("hops", 0))

    check_alerts(node_id, {
        "temperature_c":     record["t"],
        "humidity_pct":      record["h"],
        "soil_moisture_pct": record["s"],
    })


def open_serial() -> serial.Serial:
    while True:
        try:
            ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=2)
            LOG.info("Serial open: %s @ %d", SERIAL_PORT, SERIAL_BAUD)
            return ser
        except serial.SerialException as e:
            LOG.error("Cannot open serial port: %s – retry in 5 s", e)
            time.sleep(5)


def run() -> None:
    client    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)
    ser       = open_serial()

    LOG.info("Gateway running – waiting for mesh data")

    while True:
        try:
            raw = ser.readline().decode("utf-8", errors="ignore").strip()
            if not raw or not raw.startswith("{"):
                continue

            record = json.loads(raw)
            required = {"node", "t", "h", "s"}
            if not required.issubset(record):
                LOG.debug("Incomplete record: %r", record)
                continue

            write_to_influx(write_api, record)

        except json.JSONDecodeError:
            LOG.debug("Bad JSON: %r", raw)

        except serial.SerialException as e:
            LOG.error("Serial error: %s – reconnecting", e)
            try:
                ser.close()
            except Exception:
                pass
            ser = open_serial()

        except KeyboardInterrupt:
            LOG.info("Shutting down")
            break

        except Exception:
            LOG.exception("Unhandled error")

    ser.close()
    client.close()


if __name__ == "__main__":
    run()
