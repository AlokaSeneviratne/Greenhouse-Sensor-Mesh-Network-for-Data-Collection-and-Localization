#!/usr/bin/env python3
"""
PhytoSense Hub Gateway – Qt live dashboard

Reads newline-delimited JSON from the hub ESP32 over USB serial and displays
a real-time staff dashboard.  No cloud, no InfluxDB required.

Run on Raspberry Pi:
    pip install -r requirements.txt
    python3 gateway.py
"""

import json
import os
import sys
import time
from datetime import datetime

# pyserial is imported lazily inside the serial reader so that stdin mode
# (SERIAL_PORT = "-") runs on a dev machine without pyserial installed.
from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QPalette
from PySide6.QtWidgets import (
    QApplication, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QMainWindow, QSizePolicy,
    QStatusBar, QVBoxLayout, QWidget,
)

# ---- Site configuration ----
# Source of newline-delimited JSON. "-" reads stdin, which lets the simulation
# drive the dashboard directly:
#   tail -f sim/build/hub_stdout.log | python3 hub/gateway.py -
# A command-line argument or the PHYTOSENSE_PORT env var overrides the default.
SERIAL_PORT = os.environ.get("PHYTOSENSE_PORT", "/dev/ttyUSB0")
if len(sys.argv) > 1:
    SERIAL_PORT = sys.argv[1]
SERIAL_BAUD = 115200

THRESHOLDS = {
    "t": {"min": 10.0, "max": 35.0,  "label": "Temp °C"},
    "h": {"min": 40.0, "max": 95.0,  "label": "Humidity %"},
    "s": {"min": 20.0, "max": 100.0, "label": "Soil %"},
}

# Romeo nodes 1–12, Julia 13–20  (mirrors topology.h)
GREENHOUSE = {**{i: "Romeo" for i in range(1, 13)},
              **{i: "Julia" for i in range(13, 21)}}
GRADIENT   = {
     1: 1,  2: 1,
     3: 2,  4: 2,  5: 2,  6: 2,
     7: 3,  8: 3,  9: 3, 10: 3,
    11: 4, 12: 4,
    13: 1, 14: 1,
    15: 2, 16: 2, 17: 2,
    18: 3, 19: 3, 20: 3,
}

# Gradient rings per greenhouse (for column layout)
ROMEO_RINGS = {1: [1, 2], 2: [3, 4, 5, 6], 3: [7, 8, 9, 10], 4: [11, 12]}
JULIA_RINGS = {1: [13, 14], 2: [15, 16, 17], 3: [18, 19, 20]}

CARD_GREEN  = "#1e4620"
CARD_AMBER  = "#7a4a00"
CARD_RED    = "#7a1a1a"
CARD_IDLE   = "#2a2a2a"
TEXT_COLOUR = "#e8e8e8"
BG_COLOUR   = "#121212"


# ---------------------------------------------------------------------------
# Serial reader thread
# ---------------------------------------------------------------------------

class SerialReader(QThread):
    record_received = Signal(dict)   # emitted for each valid JSON line
    status_changed  = Signal(str)    # emitted on connect / disconnect

    def __init__(self, port: str, baud: int, parent=None):
        super().__init__(parent)
        self._port = port
        self._baud = baud
        self._running = True

    def run(self):
        if self._port == "-":
            self._run_stdin()
        elif os.path.isfile(self._port):
            self._run_file(self._port)
        else:
            self._run_serial()

    def _run_file(self, path):
        self.status_changed.emit(f"Following {path}")
        # Poll the hub log for new lines, the way `tail -f` does. This keeps the
        # dashboard off any shell pipe, since PowerShell's `Get-Content -Wait`
        # does not reliably stream into a child process stdin in real time.
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            while self._running:
                line = f.readline()
                if line:
                    self._emit_line(line)
                else:
                    time.sleep(0.2)

    def _emit_line(self, raw: str) -> None:
        raw = raw.strip()
        if not raw or not raw.startswith("{"):
            return
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            return
        if {"node", "t", "h", "s"}.issubset(record):
            self.record_received.emit(record)

    def _run_stdin(self):
        self.status_changed.emit("Reading JSON from stdin")
        # Iterating sys.stdin blocks until each line arrives, which is the
        # behaviour wanted behind a `tail -f | gateway.py -` pipe.
        for raw in sys.stdin:
            if not self._running:
                break
            self._emit_line(raw)
        self.status_changed.emit("stdin closed")

    def _run_serial(self):
        import serial   # only needed when talking to a real device
        ser = None
        while self._running:
            try:
                if ser is None:
                    ser = serial.Serial(self._port, self._baud, timeout=2)
                    self.status_changed.emit(f"Connected  {self._port} @ {self._baud}")

                raw = ser.readline().decode("utf-8", errors="ignore")
                self._emit_line(raw)

            except serial.SerialException as exc:
                self.status_changed.emit(f"Serial error: {exc}  reconnecting...")
                if ser:
                    try:
                        ser.close()
                    except Exception:
                        pass
                    ser = None
                time.sleep(5)

    def stop(self):
        self._running = False
        self.wait()


# ---------------------------------------------------------------------------
# Single node card widget
# ---------------------------------------------------------------------------

class NodeCard(QFrame):
    def __init__(self, node_id: int, parent=None):
        super().__init__(parent)
        self._node_id  = node_id
        self._gradient = GRADIENT.get(node_id, 0)

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(130)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._set_bg(CARD_IDLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        header = QHBoxLayout()
        self._lbl_id = QLabel(f"Node {node_id}")
        self._lbl_id.setFont(QFont("monospace", 9, QFont.Weight.Bold))
        self._lbl_id.setStyleSheet(f"color: {TEXT_COLOUR};")
        self._lbl_g  = QLabel(f"g{self._gradient}")
        self._lbl_g.setStyleSheet("color: #888888; font-size: 8px;")
        header.addWidget(self._lbl_id)
        header.addStretch()
        header.addWidget(self._lbl_g)
        layout.addLayout(header)

        self._lbl_t = self._make_row("—°C")
        self._lbl_h = self._make_row("—%  hum")
        self._lbl_s = self._make_row("—%  soil")
        layout.addWidget(self._lbl_t)
        layout.addWidget(self._lbl_h)
        layout.addWidget(self._lbl_s)

        self._lbl_ts = QLabel("never")
        self._lbl_ts.setStyleSheet("color: #555555; font-size: 7px;")
        layout.addWidget(self._lbl_ts)

    def _make_row(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("monospace", 9))
        lbl.setStyleSheet(f"color: {TEXT_COLOUR};")
        return lbl

    def _set_bg(self, colour: str):
        self.setStyleSheet(
            f"NodeCard {{ background-color: {colour}; border-radius: 6px; }}"
        )

    def update_reading(self, record: dict):
        t = record["t"]
        h = record["h"]
        s = record["s"]

        self._lbl_t.setText(f"{t:+.1f} °C")
        self._lbl_h.setText(f"{h:.1f} %  hum")
        self._lbl_s.setText(f"{s:.1f} %  soil")
        self._lbl_ts.setText(datetime.now().strftime("%H:%M:%S"))

        # Determine alert state (worst of the three sensors)
        def state(val, key):
            lo, hi = THRESHOLDS[key]["min"], THRESHOLDS[key]["max"]
            margin = (hi - lo) * 0.1
            if val < lo or val > hi:
                return 2                        # red
            if val < lo + margin or val > hi - margin:
                return 1                        # amber
            return 0                            # green

        worst = max(state(t, "t"), state(h, "h"), state(s, "s"))
        self._set_bg([CARD_GREEN, CARD_AMBER, CARD_RED][worst])


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PhytoSense – Sensor Dashboard")
        self.setStyleSheet(f"background-color: {BG_COLOUR};")

        self._cards: dict[int, NodeCard] = {}

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        # Title
        title = QLabel("PhytoSense")
        title.setFont(QFont("sans-serif", 18, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_COLOUR};")
        root.addWidget(title)

        subtitle = QLabel("University of Oulu Botanical Garden  ·  20-node gradient mesh")
        subtitle.setStyleSheet("color: #888888; font-size: 10px;")
        root.addWidget(subtitle)

        # Two-column layout: Romeo | Julia
        cols = QHBoxLayout()
        cols.setSpacing(24)
        root.addLayout(cols)
        cols.addWidget(self._build_greenhouse("Romeo", ROMEO_RINGS))
        cols.addWidget(self._build_greenhouse("Julia",  JULIA_RINGS))

        # Status bar
        self._status = QStatusBar()
        self._status.setStyleSheet("color: #888888; font-size: 9px;")
        self.setStatusBar(self._status)
        self._status.showMessage("Waiting for serial connection…")

        # Serial reader
        self._reader = SerialReader(SERIAL_PORT, SERIAL_BAUD)
        self._reader.record_received.connect(self._on_record)
        self._reader.status_changed.connect(self._status.showMessage)
        self._reader.start()

        # Heartbeat: grey out cards not seen for >120 s
        self._last_seen: dict[int, float] = {}
        timer = QTimer(self)
        timer.timeout.connect(self._check_stale)
        timer.start(10_000)

    def _build_greenhouse(self, name: str, rings: dict) -> QGroupBox:
        box = QGroupBox(name)
        box.setStyleSheet(
            f"QGroupBox {{ color: {TEXT_COLOUR}; border: 1px solid #333333;"
            " border-radius: 8px; margin-top: 8px; padding: 4px; }}"
            " QGroupBox::title { subcontrol-origin: margin; left: 10px; }"
        )
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        for g in sorted(rings):
            ring_label = QLabel(f"gradient {g}")
            ring_label.setStyleSheet("color: #555555; font-size: 8px;")
            layout.addWidget(ring_label)

            row = QHBoxLayout()
            row.setSpacing(6)
            for nid in rings[g]:
                card = NodeCard(nid)
                self._cards[nid] = card
                row.addWidget(card)
            row.addStretch()
            layout.addLayout(row)

        return box

    def _on_record(self, record: dict):
        nid = record.get("node")
        if nid not in self._cards:
            return
        self._cards[nid].update_reading(record)
        self._last_seen[nid] = time.monotonic()

        hops = record.get("hops", 0)
        self._status.showMessage(
            f"{datetime.now().strftime('%H:%M:%S')}  "
            f"node {nid} ({GREENHOUSE.get(nid,'?')}, g{GRADIENT.get(nid,'?')})  "
            f"T={record['t']:.1f}°C  H={record['h']:.1f}%  S={record['s']:.1f}%  "
            f"hops={hops}"
        )

    def _check_stale(self):
        now = time.monotonic()
        for nid, card in self._cards.items():
            last = self._last_seen.get(nid, 0)
            if now - last > 120:
                card._set_bg(CARD_IDLE)

    def closeEvent(self, event):
        self._reader.stop()
        super().closeEvent(event)


# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dark palette
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(18, 18, 18))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(232, 232, 232))
    palette.setColor(QPalette.ColorRole.Base,            QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(42, 42, 42))
    palette.setColor(QPalette.ColorRole.Text,            QColor(232, 232, 232))
    palette.setColor(QPalette.ColorRole.Button,          QColor(42, 42, 42))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(232, 232, 232))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
    app.setPalette(palette)

    win = MainWindow()
    win.resize(1100, 600)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()