# Greenhouse-Sensor-Mesh-Network-for-Data-Collection-and-Localization

# PhytoSense

Wireless environmental monitoring and BLE indoor visitor positioning for the University of Oulu Botanical Garden.

---

## What it is

PhytoSense is a self-contained sensor network deployed across two pyramid greenhouses on the Linnanmaa campus. It does two things:

1. Continuously monitors temperature, humidity, and soil moisture across 20 nodes, alerting staff when conditions cross defined thresholds.
2. Uses the same nodes as BLE beacons to approximate where a visitor is standing, then surfaces contextual plant information to their phone through a web app.

No cloud. No app install. No WiFi dependency on the nodes.

---

## The site

Two pyramid-shaped greenhouses on the Linnanmaa campus, connected by a covered walkway:

| Greenhouse | Nodes | Contents |
|---|---|---|
| Romeo | 12 | Tropical and subtropical: orchids, carnivorous plants, aquatic plants, lianas, tropical fruits |
| Julia | 8 | Mediterranean, desert, and temperate: olives, geraniums, vines, araucaria |

The garden covers 16 hectares in total. This deployment covers the indoor phase only. Outdoor expansion is planned but out of scope here.

---

## How it works

Each node is an ESP32 with a temperature/humidity sensor (SHT31-D), a capacitive soil moisture sensor, and a battery. The nodes form a Bluetooth Mesh network, relaying data hop-by-hop to a Raspberry Pi hub sitting in the walkway between the two buildings.

The Pi runs Home Assistant, stores sensor history in InfluxDB, and serves both the staff dashboard and the visitor web app over the garden's local network.

The same BLE radio that handles mesh data transmission also broadcasts a beacon advertisement. A visitor opens the PhytoSense PWA on their phone, which reads signal strengths from nearby beacons and resolves their approximate zone. The content updates as they walk.

---

## Repo structure

```
/firmware          ESP32 node firmware (Arduino/ESP-IDF, ESP-BLE-MESH SDK)
/pwa               Visitor-facing Progressive Web App (Web Bluetooth API)
/ha-config         Home Assistant configuration, automations, and Lovelace dashboards
/docs              System design and handover documentation
```

---

## Hardware per node

- ESP32-WROOM-32
- SHT31-D temperature and humidity sensor (±0.3°C, ±2% RH)
- Capacitive soil moisture sensor
- 18650 Li-ion battery with charge module
- IP54 enclosure

Hub: Raspberry Pi 4 (2GB) with a USB BLE 5.0 adapter. Mains powered from a wall socket in the walkway.

Estimated full indoor deployment cost: ~€511 for 20 nodes plus hub.

---

## Visitor app

The PWA runs in the browser. No install required. It uses the Web Bluetooth API to scan for nearby node beacons and compute a weighted centroid position from the top three RSSI readings.

**Browser support note:** Web Bluetooth works on Android Chrome and desktop Chrome/Edge. It does not work on iOS Safari. iOS visitors get a QR code entry point that links to a static zone page.

---

## Staff dashboard

Internal access only. Colour-coded zone status (green / amber / red), real-time threshold alerts pushed to staff devices, and full sensor history. Thresholds are configured per zone in consultation with horticulture staff before the system goes live.

---

## Network

Pure Bluetooth Mesh across all 20 nodes. No WiFi on the node side. Romeo and Julia are treated as one continuous mesh. The Pi connects to the mesh via a USB BLE adapter and acts as the gateway node.

---

## Future scope

- Outdoor grounds: additional nodes with IP67 enclosures and solar power
- iOS native wrapper if budget allows
- PAR (light intensity) sensors for outdoor nodes
