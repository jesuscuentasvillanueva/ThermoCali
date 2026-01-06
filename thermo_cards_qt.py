# -*- coding: utf-8 -*-
import sys
import os
import json
import time
import uuid
import csv
import glob
from datetime import datetime, timedelta
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QFrame, QScrollArea, QFileDialog, QMessageBox, QCheckBox, QGridLayout, QGroupBox, QDialog, QTabWidget, QToolBar, QAction, QStyle, QSizePolicy, QStyleFactory, QGraphicsDropShadowEffect, QDateTimeEdit, QListWidget, QListWidgetItem, QToolButton, QAbstractItemView
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QDateTime, QTimer
from PyQt5.QtGui import QPalette, QColor, QPainter, QPen, QFont, QPainterPath, QPixmap, QLinearGradient, QBrush
from pymodbus.client import ModbusSerialClient
from serial.tools import list_ports

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "thermo_config.json")


def default_config():
    return {
        "serial": {
            "port": "COM3",
            "baudrate": 9600,
            "parity": "N",
            "stopbits": 1,
            "bytesize": 8,
            "timeout": 1.0
        },
        "poll_interval_ms": 1000,
        "zones": [
            {
                "id": str(uuid.uuid4()),
                "name": "General",
                "collapsed": False,
                "monitor": True,
                "alarm_enabled": False,
                "alarm_min": None,
                "alarm_max": None,
            }
        ],
        "ui": {
            "density": "normal"
        },
        "variables": [],
        "logging": {
            "enabled": False,
            "folder": os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"),
            "mode": "per_variable",
            "separator": ",",
            "interval_sec": 10.0
        }
    }


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    cfg = default_config()
    save_config(cfg)
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def ensure_zones(cfg):
    changed = False
    if not isinstance(cfg, dict):
        return False
    zones = cfg.get("zones")
    if not isinstance(zones, list) or not zones:
        zones = [{
            "id": str(uuid.uuid4()),
            "name": "General",
            "collapsed": False,
            "monitor": True,
            "alarm_enabled": False,
            "alarm_min": None,
            "alarm_max": None,
        }]
        cfg["zones"] = zones
        changed = True
    for zone in zones:
        if not zone.get("id"):
            zone["id"] = str(uuid.uuid4())
            changed = True
        if not zone.get("name"):
            zone["name"] = "Zona"
            changed = True
        if "collapsed" not in zone:
            zone["collapsed"] = False
            changed = True
        if "monitor" not in zone:
            zone["monitor"] = False
            changed = True
        if "alarm_enabled" not in zone:
            zone["alarm_enabled"] = False
            changed = True
        if "alarm_min" not in zone:
            zone["alarm_min"] = None
            changed = True
        if "alarm_max" not in zone:
            zone["alarm_max"] = None
            changed = True
    ui_cfg = cfg.get("ui")
    if not isinstance(ui_cfg, dict):
        cfg["ui"] = {"density": "normal"}
        changed = True
    else:
        if "density" not in ui_cfg:
            ui_cfg["density"] = "normal"
            changed = True
    zone_ids = {z.get("id") for z in zones}
    default_zone_id = zones[0].get("id")
    for var in cfg.get("variables", []):
        if var.get("zone_id") not in zone_ids:
            var["zone_id"] = default_zone_id
            changed = True
        if "alarm_enabled" not in var:
            var["alarm_enabled"] = False
            changed = True
        if "alarm_min" not in var:
            var["alarm_min"] = None
            changed = True
        if "alarm_max" not in var:
            var["alarm_max"] = None
            changed = True
    return changed


class VariableDialog(QWidget):
    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowTitle("Configurar variable")
        self.data = data or {}
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        layout.addLayout(grid)
        self.name_edit = QLineEdit(self.data.get("name", "Temperatura"))
        self.unit_edit = QLineEdit(self.data.get("unit", "°C"))
        self.slave_spin = QSpinBox()
        self.slave_spin.setRange(0, 247)
        self.slave_spin.setValue(int(self.data.get("slave", 1)))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["holding", "input"])
        self.type_combo.setCurrentText(self.data.get("type", "holding"))
        self.addr_spin = QSpinBox()
        self.addr_spin.setRange(0, 65535)
        self.addr_spin.setValue(int(self.data.get("address", 0)))
        self.dtype_combo = QComboBox()
        self.dtype_combo.addItems(["uint16", "int16"])
        self.dtype_combo.setCurrentText(self.data.get("data_type", "uint16"))
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setDecimals(6)
        self.scale_spin.setRange(-1e6, 1e6)
        self.scale_spin.setSingleStep(0.1)
        self.scale_spin.setValue(float(self.data.get("scale", 0.1)))
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setDecimals(6)
        self.offset_spin.setRange(-1e6, 1e6)
        self.offset_spin.setSingleStep(0.1)
        self.offset_spin.setValue(float(self.data.get("offset", 0.0)))
        self.decimals_spin = QSpinBox()
        self.decimals_spin.setRange(0, 6)
        self.decimals_spin.setValue(int(self.data.get("decimals", 1)))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(100, 60000)
        self.interval_spin.setSingleStep(100)
        self.interval_spin.setValue(int(self.data.get("poll_interval_ms", 1000)))
        self.enabled_check = QCheckBox("Activo")
        self.enabled_check.setChecked(bool(self.data.get("enabled", True)))
        labels = [
            ("Nombre", self.name_edit),
            ("Unidad", self.unit_edit),
            ("Esclavo", self.slave_spin),
            ("Tipo", self.type_combo),
            ("Dirección", self.addr_spin),
            ("Formato", self.dtype_combo),
            ("Escala", self.scale_spin),
            ("Offset", self.offset_spin),
            ("Decimales", self.decimals_spin),
            ("Intervalo ms", self.interval_spin),
        ]
        for i, (t, w) in enumerate(labels):
            grid.addWidget(QLabel(t), i, 0)
            grid.addWidget(w, i, 1)
        layout.addWidget(self.enabled_check)
        btns = QHBoxLayout()
        self.ok_btn = QPushButton("Guardar")
        self.cancel_btn = QPushButton("Cancelar")
        btns.addWidget(self.ok_btn)
        btns.addWidget(self.cancel_btn)
        layout.addLayout(btns)
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.close)

    def accept(self):
        self.data = {
            "id": self.data.get("id") or str(uuid.uuid4()),
            "name": self.name_edit.text().strip() or "Temperatura",
            "unit": self.unit_edit.text().strip() or "°C",
            "slave": int(self.slave_spin.value()),
            "type": self.type_combo.currentText(),
            "address": int(self.addr_spin.value()),
            "data_type": self.dtype_combo.currentText(),
            "scale": float(self.scale_spin.value()),
            "offset": float(self.offset_spin.value()),
            "decimals": int(self.decimals_spin.value()),
            "poll_interval_ms": int(self.interval_spin.value()),
            "enabled": bool(self.enabled_check.isChecked()),
            "zone_id": self.data.get("zone_id"),
            "alarm_enabled": bool(self.data.get("alarm_enabled", False)),
            "alarm_min": self.data.get("alarm_min"),
            "alarm_max": self.data.get("alarm_max"),
        }
        self.close()


class VariableCard(QFrame):
    def __init__(self, var):
        super().__init__()
        self.var = var
        self.setFrameShape(QFrame.Panel)
        self.setFrameShadow(QFrame.Raised)
        self.setStyleSheet(
            "QFrame{border:1px solid #e5e7eb;border-radius:12px;background:#ffffff;}"
            "QPushButton{padding:10px 14px;border:1px solid #e5e7eb;border-radius:10px;background:#f8fafc;font-weight:600;}"
            "QPushButton:hover{background:#f1f5f9;}"
        )
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 40))
        self.setGraphicsEffect(shadow)
        self._density = "normal"
        self._monitor = False
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setSpacing(8)
        h = QHBoxLayout()
        self.title = QLabel(self.var.get("name", "Temperatura"))
        self.title.setStyleSheet("font-weight:700;font-size:20px;color:#0f172a;")
        status_wrap = QWidget()
        status_layout = QHBoxLayout(status_wrap)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(6)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(10, 10)
        self.status_dot.setStyleSheet("background:#94a3b8;border-radius:5px;")
        self.status_text = QLabel("Sin datos")
        self.status_text.setStyleSheet("color:#64748b;font-size:12px;")
        status_layout.addWidget(self.status_dot)
        status_layout.addWidget(self.status_text)
        h.addWidget(self.title)
        h.addStretch(1)
        h.addWidget(status_wrap)
        self._main_layout.addLayout(h)
        c = QHBoxLayout()
        self.value_label = QLabel("--")
        self.value_label.setStyleSheet("font-size:40px;font-weight:700;color:#0f172a;")
        self.unit_label = QLabel(self.var.get("unit", "°C"))
        self.unit_label.setStyleSheet("font-size:16px;color:#334155;background:#e2efff;border-radius:12px;padding:4px 10px;")
        c.addWidget(self.value_label)
        c.addWidget(self.unit_label)
        c.addStretch(1)
        self._main_layout.addLayout(c)
        chips = QHBoxLayout()
        self.chip_slave = QLabel("")
        self.chip_type = QLabel("")
        self.chip_addr = QLabel("")
        self.chip_shift = QLabel("")
        self.chip_scale = QLabel("")
        self.chip_offset = QLabel("")
        self.chip_cal = QLabel("")
        self._chip_base = "color:#334155;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:12px;padding:3px 10px;font-size:13px;"
        for ch in [self.chip_slave, self.chip_type, self.chip_addr, self.chip_shift, self.chip_scale, self.chip_offset, self.chip_cal]:
            ch.setStyleSheet(self._chip_base)
            chips.addWidget(ch)
        chips.addStretch(1)
        self._main_layout.addLayout(chips)
        self.last_update_label = QLabel("Sin lecturas")
        self.last_update_label.setStyleSheet("color:#94a3b8;font-size:12px;")
        self._main_layout.addWidget(self.last_update_label)
        self._update_chips()
        b = QHBoxLayout()
        self.config_btn = QPushButton("Configurar")
        b.addStretch(1)
        b.addWidget(self.config_btn)
        self._main_layout.addLayout(b)
        self.set_density("normal", monitor=False)

    def _update_chips(self):
        self.chip_slave.setText(f"S{self.var.get('slave', 1)}")
        self.chip_type.setText(self.var.get('type', 'holding'))
        self.chip_addr.setText(f"R{self.var.get('address', 0)}")
        shift = int(self.var.get('decimal_shift', 0))
        self.chip_shift.setVisible(shift != 0)
        if shift != 0:
            self.chip_shift.setText(f"/10^{shift}" if shift > 0 else f"x10^{abs(shift)}")
        sc = float(self.var.get('scale', 1.0))
        self.chip_scale.setVisible(sc != 1.0)
        if sc != 1.0:
            self.chip_scale.setText(f"x{sc}")
        off = float(self.var.get('offset', 0.0))
        self.chip_offset.setVisible(abs(off) > 1e-9)
        if abs(off) > 1e-9:
            self.chip_offset.setText(f"off {off:+g}")
            self.chip_offset.setStyleSheet(self._chip_base + "background:#fee2e2;border-color:#fecaca;color:#991b1b;")
        else:
            self.chip_offset.setStyleSheet(self._chip_base)
        cal = float(self.var.get('calibration', 0.0))
        self.chip_cal.setVisible(abs(cal) > 1e-9)
        if abs(cal) > 1e-9:
            self.chip_cal.setText(f"cal {cal:+g}")
            self.chip_cal.setStyleSheet(self._chip_base + "background:#fef3c7;border-color:#fde68a;color:#92400e;")
        else:
            self.chip_cal.setStyleSheet(self._chip_base)

    def set_value(self, value, raw):
        dec = int(self.var.get("decimals", 1))
        try:
            text = f"{float(value):.{dec}f}"
        except Exception:
            text = str(value)
        self.value_label.setText(text)
        self.status_dot.setStyleSheet("background:#22c55e;border-radius:5px;")
        self.status_text.setStyleSheet("color:#16a34a;font-size:12px;")
        self.status_text.setText("OK")

    def set_error(self):
        self.status_dot.setStyleSheet("background:#ef4444;border-radius:5px;")
        self.status_text.setStyleSheet("color:#dc2626;font-size:12px;")
        self.status_text.setText("Error")

    def update_meta(self, var):
        self.var = var
        self.title.setText(self.var.get("name", "Temperatura"))
        self.unit_label.setText(self.var.get("unit", "°C"))
        self._update_chips()

    def set_last_update(self, text):
        self.last_update_label.setText(text)

    def set_state(self, stale=False, in_alarm=False, acked=False):
        if stale:
            self.status_dot.setStyleSheet("background:#94a3b8;border-radius:5px;")
            self.status_text.setStyleSheet("color:#64748b;font-size:12px;")
            self.status_text.setText("SIN DATOS")
            self.setStyleSheet(
                "QFrame{border:1px solid #e2e8f0;border-radius:12px;background:#f8fafc;}"
                "QPushButton{padding:10px 14px;border:1px solid #e2e8f0;border-radius:10px;background:#f1f5f9;font-weight:600;}"
                "QPushButton:hover{background:#e2e8f0;}"
            )
        elif in_alarm and not acked:
            self.status_dot.setStyleSheet("background:#ef4444;border-radius:5px;")
            self.status_text.setStyleSheet("color:#dc2626;font-size:12px;")
            self.status_text.setText("ALARMA")
            self.setStyleSheet(
                "QFrame{border:1px solid #fca5a5;border-radius:12px;background:#fef2f2;}"
                "QPushButton{padding:10px 14px;border:1px solid #fecaca;border-radius:10px;background:#fff5f5;font-weight:600;}"
                "QPushButton:hover{background:#fee2e2;}"
            )
        elif in_alarm and acked:
            self.status_dot.setStyleSheet("background:#f59e0b;border-radius:5px;")
            self.status_text.setStyleSheet("color:#b45309;font-size:12px;")
            self.status_text.setText("ALARMA ACK")
            self.setStyleSheet(
                "QFrame{border:1px solid #fcd34d;border-radius:12px;background:#fffbeb;}"
                "QPushButton{padding:10px 14px;border:1px solid #fde68a;border-radius:10px;background:#fff7db;font-weight:600;}"
                "QPushButton:hover{background:#fde68a;}"
            )
        else:
            self.status_dot.setStyleSheet("background:#22c55e;border-radius:5px;")
            self.status_text.setStyleSheet("color:#16a34a;font-size:12px;")
            self.status_text.setText("OK")
            self.setStyleSheet(
                "QFrame{border:1px solid #e5e7eb;border-radius:12px;background:#ffffff;}"
                "QPushButton{padding:10px 14px;border:1px solid #e5e7eb;border-radius:10px;background:#f8fafc;font-weight:600;}"
                "QPushButton:hover{background:#f1f5f9;}"
            )

    def set_density(self, mode="normal", monitor=False):
        self._density = mode
        self._monitor = monitor
        if monitor:
            title_size = 26
            value_size = 56
            unit_size = 18
            status_size = 14
            last_size = 14
            spacing = 10
        elif mode == "compact":
            title_size = 16
            value_size = 32
            unit_size = 14
            status_size = 11
            last_size = 11
            spacing = 6
        else:
            title_size = 20
            value_size = 40
            unit_size = 16
            status_size = 12
            last_size = 12
            spacing = 8
        self._main_layout.setSpacing(spacing)
        self.title.setStyleSheet(f"font-weight:700;font-size:{title_size}px;color:#0f172a;")
        self.value_label.setStyleSheet(f"font-size:{value_size}px;font-weight:700;color:#0f172a;")
        self.unit_label.setStyleSheet(f"font-size:{unit_size}px;color:#334155;background:#e2efff;border-radius:12px;padding:4px 10px;")
        self.status_text.setStyleSheet(f"color:#64748b;font-size:{status_size}px;")
        self.last_update_label.setStyleSheet(f"color:#94a3b8;font-size:{last_size}px;")

class CollapsibleSection(QFrame):
    toggled = pyqtSignal(str, bool)

    def __init__(self, zone_id, title, collapsed=False):
        super().__init__()
        self.zone_id = zone_id
        self.setObjectName("ZoneSection")
        self.setStyleSheet("QFrame#ZoneSection{border:1px solid #e2e8f0;border-radius:12px;background:#ffffff;}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        self.toggle_btn = QToolButton()
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(not collapsed)
        self.toggle_btn.setArrowType(Qt.DownArrow if not collapsed else Qt.RightArrow)
        self.toggle_btn.setText(title)
        self.toggle_btn.setStyleSheet(
            "QToolButton{border:0;font-weight:700;font-size:16px;color:#0f172a;}"
            "QToolButton:hover{color:#0369a1;}"
        )
        self.toggle_btn.toggled.connect(self._on_toggled)
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color:#64748b;font-size:12px;")
        self.alarm_label = QLabel("")
        self.alarm_label.setStyleSheet("color:#991b1b;background:#fee2e2;border-radius:10px;padding:2px 8px;font-size:12px;")
        self.alarm_label.setVisible(False)
        header_layout.addWidget(self.toggle_btn)
        header_layout.addStretch(1)
        header_layout.addWidget(self.summary_label)
        header_layout.addWidget(self.alarm_label)
        layout.addWidget(header)
        self.content = QWidget()
        self.content_layout = QGridLayout(self.content)
        self.content_layout.setSpacing(12)
        self.content_layout.setContentsMargins(6, 6, 6, 6)
        self.content.setVisible(not collapsed)
        layout.addWidget(self.content)

    def _on_toggled(self, checked):
        self.content.setVisible(checked)
        self.toggle_btn.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.toggled.emit(self.zone_id, not checked)

    def set_title(self, title):
        self.toggle_btn.setText(title)

    def set_summary(self, text, alarm_count=0, zone_alarm=False):
        self.summary_label.setText(text)
        if alarm_count > 0 or zone_alarm:
            label = f"Alarmas {alarm_count}" if alarm_count > 0 else "Alarma zona"
            self.alarm_label.setText(label)
            self.alarm_label.setVisible(True)
        else:
            self.alarm_label.setVisible(False)


class AlarmRow(QWidget):
    ack_clicked = pyqtSignal(str)

    def __init__(self, alarm_id, title, detail, acked=False):
        super().__init__()
        self.alarm_id = alarm_id
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)
        text_box = QVBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-weight:600;color:#0f172a;")
        self.detail_label = QLabel(detail)
        self.detail_label.setStyleSheet("color:#64748b;font-size:12px;")
        text_box.addWidget(self.title_label)
        text_box.addWidget(self.detail_label)
        layout.addLayout(text_box, 1)
        self.ack_btn = QPushButton("ACK")
        self.ack_btn.clicked.connect(self._on_ack)
        layout.addWidget(self.ack_btn)
        self.set_acked(acked)

    def _on_ack(self):
        self.ack_clicked.emit(self.alarm_id)

    def set_acked(self, acked):
        if acked:
            self.ack_btn.setEnabled(False)
            self.ack_btn.setText("ACK")
            self.setStyleSheet("background:#fff7ed;border:1px solid #fed7aa;border-radius:10px;")
        else:
            self.ack_btn.setEnabled(True)
            self.ack_btn.setText("ACK")
            self.setStyleSheet("")


class PollingWorker(QThread):
    value_updated = pyqtSignal(str, float, int)
    error = pyqtSignal(str, str)
    status = pyqtSignal(str)
    connected = pyqtSignal(bool, str)
    BLOCK_START = 104
    BLOCK_COUNT = 8

    def __init__(self, serial_cfg, variables, logging_cfg=None):
        super().__init__()
        self.serial_cfg = serial_cfg
        self.variables = list(variables)
        self.running = False
        self.client = None
        self.next_due = {}
        self.logging_cfg = logging_cfg or {}
        self.logger = CSVLogger(self.logging_cfg)
        self.block_offsets = {}
        self.block_retry = {}
        self.block_cache = {}

    def set_variables(self, variables):
        self.variables = list(variables)
        try:
            self.logger.set_variables_snapshot(self.variables)
        except Exception:
            pass
        self.block_offsets = {}
        self.block_retry = {}
        self.block_cache = {}

    def set_logging(self, logging_cfg):
        self.logging_cfg = logging_cfg or {}
        self.logger.update_config(self.logging_cfg)

    def run(self):
        cfg_timeout = float(self.serial_cfg.get("timeout", 1.0))
        timeout = min(cfg_timeout, 0.1)
        client_kwargs = {
            "port": self.serial_cfg.get("port"),
            "baudrate": int(self.serial_cfg.get("baudrate", 9600)),
            "parity": self.serial_cfg.get("parity", "N"),
            "stopbits": int(self.serial_cfg.get("stopbits", 1)),
            "bytesize": int(self.serial_cfg.get("bytesize", 8)),
            "timeout": timeout,
        }
        try:
            self.client = ModbusSerialClient(**client_kwargs, retries=0, retry_on_empty=False)
        except TypeError:
            self.client = ModbusSerialClient(**client_kwargs)
            try:
                if hasattr(self.client, "retries"):
                    self.client.retries = 0
                if hasattr(self.client, "retry_on_empty"):
                    self.client.retry_on_empty = False
            except Exception:
                pass
        try:
            if not self.client.connect():
                message = f"No se pudo conectar a {self.serial_cfg.get('port')}"
                self.connected.emit(False, message)
                return
        except Exception as e:
            self.connected.emit(False, str(e))
            return
        self.connected.emit(True, "")
        self._build_block_map(self.variables)
        self.running = True
        while self.running:
            now = time.monotonic()
            vars_snapshot = list(self.variables)
            idle = True
            next_wake = None
            block_groups = {}
            block_start = self.BLOCK_START
            block_end = self.BLOCK_START + self.BLOCK_COUNT - 1
            for var in vars_snapshot:
                if not var.get("enabled", True):
                    continue
                vid = var.get("id")
                interval = int(var.get("poll_interval_ms", 1000)) / 1000.0
                due = self.next_due.get(vid, 0)
                if now < due:
                    if next_wake is None or due < next_wake:
                        next_wake = due
                    continue
                slave = int(var.get("slave", 1))
                typ = var.get("type", "holding")
                addr = int(var.get("address", 0))
                if block_start <= addr <= block_end:
                    idle = False
                    key = (slave, typ)
                    lst = block_groups.get(key)
                    if lst is None:
                        lst = []
                        block_groups[key] = lst
                    lst.append(var)
                else:
                    self.next_due[vid] = time.monotonic() + interval
            for key, vlist in block_groups.items():
                slave, typ = key
                try:
                    regs = self._read_block_for_slave(slave, typ)
                    for var in vlist:
                        vid = var.get("id")
                        interval = int(var.get("poll_interval_ms", 1000)) / 1000.0
                        addr = int(var.get("address", 0))
                        idx = addr - block_start
                        if idx < 0 or idx >= len(regs):
                            self.error.emit(vid, "Direccion fuera de bloque")
                            self.next_due[vid] = time.monotonic() + interval
                            continue
                        reg = regs[idx]
                        value = self.convert_value(var, reg)
                        self.value_updated.emit(vid, value, reg)
                        try:
                            self.logger.log(var, reg, value)
                        except Exception:
                            pass
                        self.next_due[vid] = time.monotonic() + interval
                except Exception as e:
                    for var in vlist:
                        vid = var.get("id")
                        interval = int(var.get("poll_interval_ms", 1000)) / 1000.0
                        self.error.emit(vid, str(e))
                        self.next_due[vid] = time.monotonic() + interval
            if idle:
                sleep_for = 0.005
                if next_wake is not None:
                    remaining = next_wake - time.monotonic()
                    if remaining > 0:
                        sleep_for = min(0.01, remaining)
                time.sleep(sleep_for)
        try:
            self.client.close()
        except Exception:
            pass

    def stop(self):
        self.running = False

    def _build_block_map(self, vars_list):
        self.block_offsets = {}
        self.block_retry = {}
        self.block_cache = {}
        block_start = self.BLOCK_START
        block_end = block_start + self.BLOCK_COUNT - 1
        pairs = set()
        for var in vars_list or []:
            if not var.get("enabled", True):
                continue
            addr = int(var.get("address", 0))
            if addr < block_start or addr > block_end:
                continue
            slave = int(var.get("slave", 1))
            typ = var.get("type", "holding")
            pairs.add((slave, typ))
        for key in sorted(pairs):
            slave, typ = key
            offset, regs = self._detect_block_offset(slave, typ)
            if offset is None:
                self.block_retry[key] = time.monotonic() + 5.0
                continue
            self.block_offsets[key] = offset
            if regs:
                self.block_cache[key] = regs

    def _detect_block_offset(self, slave, typ):
        for offset in (0, 1):
            start = self.BLOCK_START - offset
            if start < 0:
                continue
            try:
                regs = self.read_block(slave, typ, start, self.BLOCK_COUNT)
                return offset, regs
            except Exception:
                continue
        return None, None

    def _read_block_for_slave(self, slave, typ):
        key = (slave, typ)
        cached = self.block_cache.pop(key, None)
        if cached is not None:
            return cached
        offset = self.block_offsets.get(key)
        now = time.monotonic()
        if offset is None:
            retry_at = self.block_retry.get(key, 0)
            if now < retry_at:
                raise RuntimeError("Sin mapa")
            offset, regs = self._detect_block_offset(slave, typ)
            if offset is None:
                self.block_retry[key] = now + 5.0
                raise RuntimeError("Sin respuesta")
            self.block_offsets[key] = offset
            return regs
        start = self.BLOCK_START - offset
        try:
            return self.read_block(slave, typ, start, self.BLOCK_COUNT)
        except Exception:
            alt = 1 - offset
            try:
                regs = self.read_block(slave, typ, self.BLOCK_START - alt, self.BLOCK_COUNT)
                self.block_offsets[key] = alt
                return regs
            except Exception as e:
                raise e

    def read_var(self, var):
        addr = int(var.get("address", 0))
        slave = int(var.get("slave", 1))
        typ = var.get("type", "holding")
        reg = self.read_raw(slave, typ, addr)
        value = self.convert_value(var, reg)
        return reg, value

    def read_raw(self, slave, typ, addr):
        if typ == "holding":
            resp = self.client.read_holding_registers(address=addr, count=1, slave=slave)
        else:
            resp = self.client.read_input_registers(address=addr, count=1, slave=slave)
        if hasattr(resp, "isError") and resp.isError():
            raise RuntimeError(str(resp))
        return int(resp.registers[0])

    def read_block(self, slave, typ, addr, count):
        if typ == "holding":
            resp = self.client.read_holding_registers(address=addr, count=count, slave=slave)
        else:
            resp = self.client.read_input_registers(address=addr, count=count, slave=slave)
        if hasattr(resp, "isError") and resp.isError():
            raise RuntimeError(str(resp))
        regs = getattr(resp, "registers", None)
        if not regs or len(regs) < count:
            raise RuntimeError("Respuesta incompleta")
        return [int(r) for r in regs]

    def convert_value(self, var, reg):
        dtype = var.get("data_type", "uint16")
        r = int(reg)
        if dtype == "int16" and r > 32767:
            r = r - 65536
        scale = float(var.get("scale", 1.0))
        offset = float(var.get("offset", 0.0))
        calibration = float(var.get("calibration", 0.0))
        shift = int(var.get("decimal_shift", 0))
        factor = (10.0 ** (-shift)) if shift != 0 else 1.0
        return r * factor * scale + offset + calibration


class CSVLogger:
    def __init__(self, cfg):
        self.update_config(cfg)
        self._vars = []
        self._last_ts = {}

    def update_config(self, cfg):
        self.cfg = cfg or {}
        self.enabled = bool(self.cfg.get("enabled", False))
        self.folder = self.cfg.get("folder") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        self.mode = self.cfg.get("mode", "per_variable")  # daily | single | per_variable
        self.sep = self.cfg.get("separator", ",")
        try:
            self.interval_sec = float(self.cfg.get("interval_sec", 10.0))
        except Exception:
            self.interval_sec = 10.0
        try:
            os.makedirs(self.folder, exist_ok=True)
        except Exception:
            pass

    def set_variables_snapshot(self, vars_list):
        self._vars = list(vars_list or [])

    def _safe(self, s):
        s = str(s)
        return "".join(ch if ch.isalnum() or ch in ("-","_"," ") else "_" for ch in s).strip()

    def _file_for(self, var, ts):
        date_str = ts.strftime("%Y-%m-%d")
        if self.mode == "single":
            return os.path.join(self.folder, "termo_log.csv")
        if self.mode == "per_variable":
            name = self._safe(var.get("name", var.get("id","var")))
            vid = var.get("id")
            if vid:
                return os.path.join(self.folder, f"{name}_{vid}_{date_str}.csv")
            return os.path.join(self.folder, f"{name}_{date_str}.csv")
        return os.path.join(self.folder, f"termo_{date_str}.csv")

    def log(self, var, raw, value):
        if not self.enabled:
            return
        ts = datetime.now()
        # Throttle by interval per variable id
        try:
            vid = var.get("id")
            if vid:
                last = self._last_ts.get(vid)
                if self.interval_sec and self.interval_sec > 0 and last is not None:
                    if (ts - last).total_seconds() < self.interval_sec:
                        return
                self._last_ts[vid] = ts
        except Exception:
            pass
        path = self._file_for(var, ts)
        try:
            is_new = not os.path.exists(path) or os.path.getsize(path) == 0
        except Exception:
            is_new = True
        try:
            with open(path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, delimiter=self.sep)
                if is_new:
                    writer.writerow(["timestamp","variable_id","variable_name","raw","value","unit"]) 
                writer.writerow([
                    ts.isoformat(timespec="seconds"),
                    var.get("id"),
                    var.get("name"),
                    int(raw),
                    float(value),
                    var.get("unit",""),
                ])
        except Exception:
            pass


class VariableForm(QFrame):
    delete_requested = pyqtSignal(str)

    def __init__(self, var, zones=None):
        super().__init__()
        self.var = dict(var)
        if not self.var.get("id"):
            self.var["id"] = str(uuid.uuid4())
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("QFrame{border:1px solid #e0e0e0;border-radius:8px;background:#ffffff;}")
        v = QVBoxLayout(self)
        t = QHBoxLayout()
        self.name_edit = QLineEdit(self.var.get("name", "Temperatura"))
        self.name_edit.setStyleSheet("font-weight:600;")
        self.unit_edit = QLineEdit(self.var.get("unit", "°C"))
        self.unit_edit.setFixedWidth(80)
        t.addWidget(QLabel("Nombre"))
        t.addWidget(self.name_edit)
        t.addWidget(QLabel("Unidad"))
        t.addWidget(self.unit_edit)
        t.addStretch(1)
        self.del_btn = QPushButton("Eliminar")
        t.addWidget(self.del_btn)
        v.addLayout(t)
        g = QGridLayout()
        self.zone_combo = QComboBox()
        self.set_zones(zones or [])
        self.alarm_enable = QCheckBox("Alarma")
        self.alarm_enable.setChecked(bool(self.var.get("alarm_enabled", False)))
        self.alarm_min_spin = QDoubleSpinBox(); self.alarm_min_spin.setDecimals(2); self.alarm_min_spin.setRange(-1e6, 1e6)
        self.alarm_max_spin = QDoubleSpinBox(); self.alarm_max_spin.setDecimals(2); self.alarm_max_spin.setRange(-1e6, 1e6)
        if self.var.get("alarm_min") is not None:
            self.alarm_min_spin.setValue(float(self.var.get("alarm_min")))
        if self.var.get("alarm_max") is not None:
            self.alarm_max_spin.setValue(float(self.var.get("alarm_max")))
        self.alarm_enable.toggled.connect(self._toggle_alarm_fields)
        self._toggle_alarm_fields(self.alarm_enable.isChecked())
        self.slave_spin = QSpinBox(); self.slave_spin.setRange(0,247); self.slave_spin.setValue(int(self.var.get("slave",1)))
        self.type_combo = QComboBox(); self.type_combo.addItems(["holding","input"]); self.type_combo.setCurrentText(self.var.get("type","holding"))
        self.addr_spin = QSpinBox(); self.addr_spin.setRange(0,65535); self.addr_spin.setValue(int(self.var.get("address",0)))
        self.dtype_combo = QComboBox(); self.dtype_combo.addItems(["uint16","int16"]); self.dtype_combo.setCurrentText(self.var.get("data_type","uint16"))
        self.scale_spin = QDoubleSpinBox(); self.scale_spin.setDecimals(6); self.scale_spin.setRange(-1e6,1e6); self.scale_spin.setSingleStep(0.1); self.scale_spin.setValue(float(self.var.get("scale",1.0)))
        self.dec_shift_spin = QSpinBox(); self.dec_shift_spin.setRange(-9,9); self.dec_shift_spin.setSingleStep(1); self.dec_shift_spin.setValue(int(self.var.get("decimal_shift",0)))
        self.offset_spin = QDoubleSpinBox(); self.offset_spin.setDecimals(6); self.offset_spin.setRange(-1e6,1e6); self.offset_spin.setSingleStep(0.1); self.offset_spin.setValue(float(self.var.get("offset",0.0)))
        self.calib_spin = QDoubleSpinBox(); self.calib_spin.setDecimals(6); self.calib_spin.setRange(-1e6,1e6); self.calib_spin.setSingleStep(0.1); self.calib_spin.setValue(float(self.var.get("calibration",0.0)))
        self.decimals_spin = QSpinBox(); self.decimals_spin.setRange(0,6); self.decimals_spin.setValue(int(self.var.get("decimals",1)))
        self.interval_spin = QSpinBox(); self.interval_spin.setRange(50,60000); self.interval_spin.setSingleStep(50); self.interval_spin.setValue(int(self.var.get("poll_interval_ms",1000)))
        self.enabled_check = QCheckBox("Activo"); self.enabled_check.setChecked(bool(self.var.get("enabled",True)))
        fields = [
            ("Zona", self.zone_combo),
            ("Alarmas", self.alarm_enable),
            ("Alarma min", self.alarm_min_spin),
            ("Alarma max", self.alarm_max_spin),
            ("Esclavo", self.slave_spin),
            ("Tipo", self.type_combo),
            ("Dirección", self.addr_spin),
            ("Formato", self.dtype_combo),
            ("Desplazar coma", self.dec_shift_spin),
            ("Escala", self.scale_spin),
            ("Offset", self.offset_spin),
            ("Calibración", self.calib_spin),
            ("Decimales", self.decimals_spin),
            ("Intervalo ms", self.interval_spin),
        ]
        for i,(lbl,w) in enumerate(fields):
            g.addWidget(QLabel(lbl), i//2, (i%2)*2)
            g.addWidget(w, i//2, (i%2)*2+1)
        rows = (len(fields) + 1) // 2
        g.addWidget(self.enabled_check, rows, 0, 1, 2)
        v.addLayout(g)
        self.del_btn.clicked.connect(lambda: self.delete_requested.emit(self.var.get("id")))

    def _toggle_alarm_fields(self, enabled):
        self.alarm_min_spin.setEnabled(enabled)
        self.alarm_max_spin.setEnabled(enabled)

    def set_zones(self, zones, default_zone_id=None):
        current_id = self.zone_combo.currentData()
        zone_ids = [z.get("id") for z in zones if z.get("id")]
        self.zone_combo.clear()
        for zone in zones:
            self.zone_combo.addItem(zone.get("name", "Zona"), zone.get("id"))
        desired_id = current_id or self.var.get("zone_id")
        if desired_id not in zone_ids:
            desired_id = default_zone_id or (zone_ids[0] if zone_ids else None)
        if desired_id in zone_ids:
            self.zone_combo.setCurrentIndex(zone_ids.index(desired_id))
            self.var["zone_id"] = desired_id

    def data(self):
        return {
            "id": self.var.get("id"),
            "name": self.name_edit.text().strip() or "Temperatura",
            "unit": self.unit_edit.text().strip() or "°C",
            "zone_id": self.zone_combo.currentData() or self.var.get("zone_id"),
            "alarm_enabled": bool(self.alarm_enable.isChecked()),
            "alarm_min": float(self.alarm_min_spin.value()) if self.alarm_enable.isChecked() else None,
            "alarm_max": float(self.alarm_max_spin.value()) if self.alarm_enable.isChecked() else None,
            "slave": int(self.slave_spin.value()),
            "type": self.type_combo.currentText(),
            "address": int(self.addr_spin.value()),
            "data_type": self.dtype_combo.currentText(),
            "scale": float(self.scale_spin.value()),
            "decimal_shift": int(self.dec_shift_spin.value()),
            "offset": float(self.offset_spin.value()),
            "calibration": float(self.calib_spin.value()),
            "decimals": int(self.decimals_spin.value()),
            "poll_interval_ms": int(self.interval_spin.value()),
            "enabled": bool(self.enabled_check.isChecked()),
        }


class SettingsDialog(QDialog):
    def __init__(self, parent, cfg, selected_id=None):
        super().__init__(parent)
        self.setWindowTitle("Configuración")
        self.resize(900, 650)
        self.setStyleSheet(
            "QDialog{background:#ffffff;}"
            "QTabWidget::pane{border:1px solid #e5e7eb; border-radius:10px; margin-top:6px;}"
            "QTabBar::tab{padding:8px 14px; border:1px solid #e5e7eb; border-bottom:0; background:#f8fafc; margin-right:4px; border-top-left-radius:8px; border-top-right-radius:8px;}"
            "QTabBar::tab:selected{background:#ffffff; color:#0f172a; font-weight:600;}"
            "QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox{padding:6px 8px; border:1px solid #e2e8f0; border-radius:8px;}"
            "QGroupBox{border:1px solid #e5e7eb; border-radius:8px; margin-top:10px; padding:6px 8px; font-weight:600;}"
            "QPushButton{padding:8px 12px; border:1px solid #e2e8f0; border-radius:10px; background:#f8fafc;}"
            "QPushButton:hover{background:#f1f5f9;}"
        )
        self._selected_id = selected_id
        self._cfg = json.loads(json.dumps(cfg))
        ensure_zones(self._cfg)
        self._zone_meta = {}
        for zone in self._cfg.get("zones", []):
            zid = zone.get("id")
            self._zone_meta[zid] = {
                "collapsed": bool(zone.get("collapsed", False)),
                "monitor": bool(zone.get("monitor", False)),
                "alarm_enabled": bool(zone.get("alarm_enabled", False)),
                "alarm_min": zone.get("alarm_min"),
                "alarm_max": zone.get("alarm_max"),
            }
        self._loading_zone_meta = False
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs)
        self._build_comm_tab()
        self._build_zones_tab()
        self._build_vars_tab()
        self._build_log_tab()
        btns = QHBoxLayout()
        self.apply_btn = QPushButton("Guardar y Aplicar")
        self.cancel_btn = QPushButton("Cancelar")
        btns.addStretch(1)
        btns.addWidget(self.apply_btn)
        btns.addWidget(self.cancel_btn)
        v.addLayout(btns)
        self.apply_btn.clicked.connect(self._accept)
        self.cancel_btn.clicked.connect(self.reject)

    def _build_comm_tab(self):
        w = QWidget(); g = QGridLayout(w)
        self.port_combo = QComboBox(); self._refresh_ports()
        self.baud_combo = QComboBox(); self.baud_combo.addItems(["1200","2400","4800","9600","19200","38400","57600","115200"]) 
        self.parity_combo = QComboBox(); self.parity_combo.addItems(["N","E","O"]) 
        self.stop_combo = QComboBox(); self.stop_combo.addItems(["1","2"]) 
        self.byte_combo = QComboBox(); self.byte_combo.addItems(["7","8"]) 
        self.timeout_spin = QDoubleSpinBox(); self.timeout_spin.setRange(0.02,10.0); self.timeout_spin.setSingleStep(0.02)
        self.global_poll_spin = QSpinBox(); self.global_poll_spin.setRange(50,60000); self.global_poll_spin.setSingleStep(50)
        ser = self._cfg.get("serial", {})
        self.port_combo.setCurrentText(ser.get("port", "COM3"))
        self.baud_combo.setCurrentText(str(ser.get("baudrate", 9600)))
        self.parity_combo.setCurrentText(ser.get("parity", "N"))
        self.stop_combo.setCurrentText(str(ser.get("stopbits", 1)))
        self.byte_combo.setCurrentText(str(ser.get("bytesize", 8)))
        self.timeout_spin.setValue(float(ser.get("timeout", 1.0)))
        self.global_poll_spin.setValue(int(self._cfg.get("poll_interval_ms", 1000)))
        refresh_btn = QPushButton("Buscar puertos")
        refresh_btn.clicked.connect(self._refresh_ports)
        g.addWidget(QLabel("Puerto"),0,0); g.addWidget(self.port_combo,0,1)
        g.addWidget(QLabel("Baudios"),0,2); g.addWidget(self.baud_combo,0,3)
        g.addWidget(QLabel("Paridad"),1,0); g.addWidget(self.parity_combo,1,1)
        g.addWidget(QLabel("Stop bits"),1,2); g.addWidget(self.stop_combo,1,3)
        g.addWidget(QLabel("Data bits"),2,0); g.addWidget(self.byte_combo,2,1)
        g.addWidget(QLabel("Timeout (s)"),2,2); g.addWidget(self.timeout_spin,2,3)
        g.addWidget(QLabel("Intervalo global (ms)"),3,0); g.addWidget(self.global_poll_spin,3,1)
        g.addWidget(refresh_btn,0,4)
        self.tabs.addTab(w, "Comunicación")

    def _build_zones_tab(self):
        w = QWidget(); v = QVBoxLayout(w)
        self.zones_list = QListWidget()
        self.zones_list.setSelectionMode(QListWidget.SingleSelection)
        self.zones_list.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        for zone in self._cfg.get("zones", []):
            item = QListWidgetItem(zone.get("name", "Zona"))
            item.setData(Qt.UserRole, zone.get("id"))
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            self.zones_list.addItem(item)
        v.addWidget(self.zones_list, 1)
        props = QGroupBox("Propiedades de zona")
        g = QGridLayout(props)
        self.zone_monitor_check = QCheckBox("Mostrar en modo monitor")
        self.zone_alarm_enable = QCheckBox("Alarma de zona")
        self.zone_alarm_min = QDoubleSpinBox(); self.zone_alarm_min.setDecimals(2); self.zone_alarm_min.setRange(-1e6, 1e6)
        self.zone_alarm_max = QDoubleSpinBox(); self.zone_alarm_max.setDecimals(2); self.zone_alarm_max.setRange(-1e6, 1e6)
        g.addWidget(self.zone_monitor_check, 0, 0, 1, 2)
        g.addWidget(self.zone_alarm_enable, 1, 0, 1, 2)
        g.addWidget(QLabel("Alarma min"), 2, 0); g.addWidget(self.zone_alarm_min, 2, 1)
        g.addWidget(QLabel("Alarma max"), 3, 0); g.addWidget(self.zone_alarm_max, 3, 1)
        v.addWidget(props)
        btns = QHBoxLayout()
        self.zone_add_btn = QPushButton("Añadir zona")
        self.zone_del_btn = QPushButton("Eliminar zona")
        self.zone_up_btn = QPushButton("Subir")
        self.zone_down_btn = QPushButton("Bajar")
        for b in [self.zone_add_btn, self.zone_del_btn, self.zone_up_btn, self.zone_down_btn]:
            btns.addWidget(b)
        btns.addStretch(1)
        v.addLayout(btns)
        self.tabs.addTab(w, "Zonas")
        self.zone_add_btn.clicked.connect(self._add_zone)
        self.zone_del_btn.clicked.connect(self._remove_zone)
        self.zone_up_btn.clicked.connect(lambda: self._move_zone(-1))
        self.zone_down_btn.clicked.connect(lambda: self._move_zone(1))
        self.zones_list.itemChanged.connect(self._on_zones_changed)
        self.zones_list.currentItemChanged.connect(self._load_zone_meta)
        self.zone_monitor_check.toggled.connect(self._on_zone_meta_changed)
        self.zone_alarm_enable.toggled.connect(self._on_zone_alarm_toggle)
        self.zone_alarm_min.valueChanged.connect(self._on_zone_meta_changed)
        self.zone_alarm_max.valueChanged.connect(self._on_zone_meta_changed)
        if self.zones_list.count() > 0:
            self.zones_list.setCurrentRow(0)

    def _build_vars_tab(self):
        w = QWidget(); v = QVBoxLayout(w)
        self.vars_scroll = QScrollArea(); self.vars_scroll.setWidgetResizable(True)
        self.vars_container = QWidget(); self.vars_layout = QVBoxLayout(self.vars_container)
        self.vars_scroll.setWidget(self.vars_container)
        v.addWidget(self.vars_scroll, 1)
        add_btn = QPushButton("Añadir variable")
        v.addWidget(add_btn)
        self.tabs.addTab(w, "Variables")
        add_btn.clicked.connect(self._add_var_form)
        for var in self._cfg.get("variables", []):
            self._add_var_form(var)
        self._refresh_var_zone_options()
        if self._selected_id:
            self._focus_selected()

    def _current_zone_id(self):
        item = self.zones_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _load_zone_meta(self, current, previous=None):
        self._loading_zone_meta = True
        zone_id = current.data(Qt.UserRole) if current else None
        if zone_id and zone_id not in self._zone_meta:
            self._zone_meta[zone_id] = {
                "collapsed": False,
                "monitor": False,
                "alarm_enabled": False,
                "alarm_min": None,
                "alarm_max": None,
            }
        meta = self._zone_meta.get(zone_id, {})
        self.zone_monitor_check.setChecked(bool(meta.get("monitor", False)))
        self.zone_alarm_enable.setChecked(bool(meta.get("alarm_enabled", False)))
        self.zone_alarm_min.setValue(float(meta.get("alarm_min") or 0.0))
        self.zone_alarm_max.setValue(float(meta.get("alarm_max") or 0.0))
        self._on_zone_alarm_toggle(self.zone_alarm_enable.isChecked())
        self._loading_zone_meta = False

    def _on_zone_alarm_toggle(self, enabled):
        self.zone_alarm_min.setEnabled(enabled)
        self.zone_alarm_max.setEnabled(enabled)
        self._on_zone_meta_changed()

    def _on_zone_meta_changed(self):
        if self._loading_zone_meta:
            return
        zone_id = self._current_zone_id()
        if not zone_id:
            return
        meta = self._zone_meta.setdefault(zone_id, {
            "collapsed": False,
            "monitor": False,
            "alarm_enabled": False,
            "alarm_min": None,
            "alarm_max": None,
        })
        meta["monitor"] = bool(self.zone_monitor_check.isChecked())
        meta["alarm_enabled"] = bool(self.zone_alarm_enable.isChecked())
        meta["alarm_min"] = float(self.zone_alarm_min.value()) if meta["alarm_enabled"] else None
        meta["alarm_max"] = float(self.zone_alarm_max.value()) if meta["alarm_enabled"] else None

    def _current_zones(self):
        zones = []
        for i in range(self.zones_list.count()):
            item = self.zones_list.item(i)
            zone_id = item.data(Qt.UserRole)
            if not zone_id:
                zone_id = str(uuid.uuid4())
                item.setData(Qt.UserRole, zone_id)
            name = item.text().strip() or f"Zona {i + 1}"
            if item.text().strip() != name:
                item.setText(name)
            meta = self._zone_meta.get(zone_id, {})
            zones.append({
                "id": zone_id,
                "name": name,
                "collapsed": bool(meta.get("collapsed", False)),
                "monitor": bool(meta.get("monitor", False)),
                "alarm_enabled": bool(meta.get("alarm_enabled", False)),
                "alarm_min": meta.get("alarm_min"),
                "alarm_max": meta.get("alarm_max"),
            })
        return zones

    def _refresh_var_zone_options(self):
        zones = self._current_zones()
        default_id = zones[0]["id"] if zones else None
        for i in range(self.vars_layout.count()):
            w = self.vars_layout.itemAt(i).widget()
            if isinstance(w, VariableForm):
                w.set_zones(zones, default_zone_id=default_id)

    def _add_zone(self):
        zone_id = str(uuid.uuid4())
        name = f"Zona {self.zones_list.count() + 1}"
        item = QListWidgetItem(name)
        item.setData(Qt.UserRole, zone_id)
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        self.zones_list.addItem(item)
        self._zone_meta[zone_id] = {
            "collapsed": False,
            "monitor": False,
            "alarm_enabled": False,
            "alarm_min": None,
            "alarm_max": None,
        }
        self.zones_list.setCurrentItem(item)
        self.zones_list.editItem(item)
        self._refresh_var_zone_options()

    def _remove_zone(self):
        if self.zones_list.count() <= 1:
            QMessageBox.warning(self, "Zonas", "Debe existir al menos una zona.")
            return
        row = self.zones_list.currentRow()
        if row < 0:
            return
        item = self.zones_list.item(row)
        zone_id = item.data(Qt.UserRole)
        if QMessageBox.question(
            self,
            "Zonas",
            "¿Eliminar la zona? Las variables se moverán a la zona principal.",
        ) != QMessageBox.Yes:
            return
        self.zones_list.takeItem(row)
        self._zone_meta.pop(zone_id, None)
        self._refresh_var_zone_options()

    def _move_zone(self, delta):
        row = self.zones_list.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if new_row < 0 or new_row >= self.zones_list.count():
            return
        item = self.zones_list.takeItem(row)
        self.zones_list.insertItem(new_row, item)
        self.zones_list.setCurrentRow(new_row)
        self._refresh_var_zone_options()

    def _on_zones_changed(self, item):
        if not item.text().strip():
            item.setText(f"Zona {self.zones_list.row(item) + 1}")
        self._refresh_var_zone_options()

    def _build_log_tab(self):
        w = QWidget(); g = QGridLayout(w)
        log = self._cfg.get("logging", {})
        self.log_enabled = QCheckBox("Habilitar guardado CSV")
        self.log_enabled.setChecked(bool(log.get("enabled", False)))
        self.log_folder = QLineEdit(log.get("folder", os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")))
        self.log_browse = QPushButton("Examinar…")
        self.log_mode = QComboBox(); self.log_mode.addItems(["per_variable","daily","single"]); self.log_mode.setCurrentText(log.get("mode","per_variable"))
        self.log_sep = QComboBox(); self.log_sep.addItems([",",";","\t"]); self.log_sep.setCurrentText(log.get("separator", ","))
        self.log_interval = QDoubleSpinBox(); self.log_interval.setDecimals(1); self.log_interval.setRange(0.0, 3600.0); self.log_interval.setSingleStep(0.5); self.log_interval.setValue(float(log.get("interval_sec", 10.0)))
        g.addWidget(self.log_enabled, 0, 0, 1, 2)
        g.addWidget(QLabel("Carpeta"), 1, 0); g.addWidget(self.log_folder, 1, 1); g.addWidget(self.log_browse, 1, 2)
        g.addWidget(QLabel("Modo"), 2, 0); g.addWidget(self.log_mode, 2, 1)
        g.addWidget(QLabel("Separador"), 3, 0); g.addWidget(self.log_sep, 3, 1)
        g.addWidget(QLabel("Intervalo de guardado (s)"), 4, 0); g.addWidget(self.log_interval, 4, 1)
        self.log_browse.clicked.connect(self._browse_logs)
        self.tabs.addTab(w, "Histórico")

    def _browse_logs(self):
        path = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de logs", self.log_folder.text())
        if path:
            self.log_folder.setText(path)

    def _focus_selected(self):
        for i in range(self.vars_layout.count()):
            w = self.vars_layout.itemAt(i).widget()
            if isinstance(w, VariableForm) and w.data().get("id") == self._selected_id:
                w.name_edit.setFocus()
                self.vars_scroll.ensureWidgetVisible(w)
                break

    def _add_var_form(self, var=None):
        zones = self._current_zones()
        default_zone_id = zones[0]["id"] if zones else None
        if not isinstance(var, dict):
            var = {
                "id": str(uuid.uuid4()),
                "name": f"Temperatura {self.vars_layout.count()+1}",
                "unit": "°C",
                "zone_id": default_zone_id,
                "alarm_enabled": False,
                "alarm_min": None,
                "alarm_max": None,
                "slave": 1,
                "type": "holding",
                "address": 0,
                "data_type": "uint16",
                "scale": 1.0,
                "decimal_shift": 0,
                "offset": 0.0,
                "decimals": 1,
                "poll_interval_ms": int(self.global_poll_spin.value()) if hasattr(self, 'global_poll_spin') else int(self._cfg.get("poll_interval_ms", 1000)),
                "enabled": True,
            }
        form = VariableForm(var, zones=zones)
        form.delete_requested.connect(self._remove_var_form)
        self.vars_layout.addWidget(form)

    def _remove_var_form(self, vid):
        for i in range(self.vars_layout.count()):
            w = self.vars_layout.itemAt(i).widget()
            if isinstance(w, VariableForm) and w.data().get("id") == vid:
                w.setParent(None)
                w.deleteLater()
                break

    def _refresh_ports(self):
        try:
            ports = [p.device for p in list_ports.comports()]
        except Exception:
            ports = []
        if hasattr(self, 'port_combo'):
            self.port_combo.clear(); self.port_combo.addItems(ports or ["COM1","COM2","COM3","COM4"])

    def _accept(self):
        new_cfg = {
            "serial": {
                "port": self.port_combo.currentText(),
                "baudrate": int(self.baud_combo.currentText()),
                "parity": self.parity_combo.currentText(),
                "stopbits": int(self.stop_combo.currentText()),
                "bytesize": int(self.byte_combo.currentText()),
                "timeout": float(self.timeout_spin.value()),
            },
            "poll_interval_ms": int(self.global_poll_spin.value()),
            "zones": self._current_zones(),
            "ui": self._cfg.get("ui", {"density": "normal"}),
            "variables": [],
            "logging": {
                "enabled": bool(self.log_enabled.isChecked()),
                "folder": self.log_folder.text().strip() or os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"),
                "mode": self.log_mode.currentText(),
                "separator": self.log_sep.currentText(),
                "interval_sec": float(self.log_interval.value()),
            }
        }
        for i in range(self.vars_layout.count()):
            w = self.vars_layout.itemAt(i).widget()
            if isinstance(w, VariableForm):
                new_cfg["variables"].append(w.data())
        self._cfg = new_cfg
        self.accept()

    def result_config(self):
        return self._cfg


class BasicPlot(QWidget):
    def __init__(self):
        super().__init__()
        self._series = []
        self._x_min = 0.0
        self._x_max = 1.0
        self._y_min = 0.0
        self._y_max = 1.0
        self._colors = [QColor('#1f77b4'), QColor('#ff7f0e'), QColor('#2ca02c'), QColor('#d62728'), QColor('#9467bd'), QColor('#8c564b')]

    def set_data(self, series):
        self._series = series or []
        xs = []
        ys = []
        for s in self._series:
            if not s.get('visible', True):
                continue
            for x, y in s.get('points', []):
                xs.append(float(x))
                ys.append(float(y))
            for th in [s.get('alarm_min'), s.get('alarm_max')]:
                if th is not None:
                    ys.append(float(th))
        if xs and ys:
            self._x_min = min(xs); self._x_max = max(xs)
            self._y_min = min(ys); self._y_max = max(ys)
            if self._x_min == self._x_max:
                self._x_max = self._x_min + 1.0
            if self._y_min == self._y_max:
                self._y_max = self._y_min + 1.0
        self.update()

    def paintEvent(self, e):
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            rect = self.rect()
            left = 60; right = 20; top = 20; bottom = 40
            plot_w = max(10, rect.width() - left - right)
            plot_h = max(10, rect.height() - top - bottom)
            p.fillRect(rect, QColor('#ffffff'))
            axis_pen = QPen(QColor('#94a3b8'))
            p.setPen(axis_pen)
            p.drawRect(left, top, plot_w, plot_h)
            p.setFont(QFont('', 9))
            # Horizontal grid and Y labels
            denom_y = max(1e-9, (self._y_max - self._y_min))
            for i in range(6):
                yv = self._y_min + (self._y_max - self._y_min) * i / 5.0
                ypx = top + plot_h - int((yv - self._y_min) / denom_y * plot_h)
                p.drawLine(left - 4, ypx, left + plot_w, ypx)
                p.drawText(4, ypx + 4, f"{yv:.2f}")
            # Vertical grid and X labels
            denom_x = max(1e-9, (self._x_max - self._x_min))
            for i in range(6):
                xv = self._x_min + (self._x_max - self._x_min) * i / 5.0
                xpx = left + int((xv - self._x_min) / denom_x * plot_w)
                p.drawLine(xpx, top, xpx, top + plot_h + 4)
                if hasattr(QDateTime, 'fromSecsSinceEpoch'):
                    dt = QDateTime.fromSecsSinceEpoch(int(xv))
                else:
                    dt = QDateTime.fromMSecsSinceEpoch(int(xv * 1000))
                p.drawText(xpx - 30, top + plot_h + 18, dt.toString('HH:mm'))
            # Threshold lines
            for idx, s in enumerate(self._series):
                if not s.get('visible', True):
                    continue
                color = self._colors[idx % len(self._colors)]
                pen = QPen(color); pen.setWidth(1); pen.setStyle(Qt.DashLine)
                p.setPen(pen)
                for th in [s.get('alarm_min'), s.get('alarm_max')]:
                    if th is None:
                        continue
                    ypx = top + plot_h - int((float(th) - self._y_min) / denom_y * plot_h)
                    p.drawLine(left, ypx, left + plot_w, ypx)
            # Series lines
            for idx, s in enumerate(self._series):
                if not s.get('visible', True):
                    continue
                pts = s.get('points', [])
                if not pts:
                    continue
                color = self._colors[idx % len(self._colors)]
                pen = QPen(color); pen.setWidth(2)
                p.setPen(pen)
                path = QPainterPath()
                first = True
                for x, y in pts:
                    xpx = left + (float(x) - self._x_min) / denom_x * plot_w
                    ypx = top + plot_h - (float(y) - self._y_min) / denom_y * plot_h
                    if first:
                        path.moveTo(xpx, ypx); first = False
                    else:
                        path.lineTo(xpx, ypx)
                p.drawPath(path)
            p.end()
        except Exception:
            # Fail silently to avoid crashing the UI on paint
            try:
                p.end()
            except Exception:
                pass


class GraphsDialog(QDialog):
    def __init__(self, parent, cfg):
        super().__init__(parent)
        self.setWindowTitle("Gráficos")
        self.resize(1000, 650)
        self.cfg = cfg
        self.log_cfg = self.cfg.get("logging", {})
        self.log_folder = self.log_cfg.get("folder") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.vars_list = QListWidget()
        self.vars_list.setSelectionMode(QListWidget.ExtendedSelection)
        for v in self.cfg.get("variables", []):
            item = QListWidgetItem(v.get("name", v.get("id", "var")))
            item.setData(Qt.UserRole, v)
            self.vars_list.addItem(item)
        top.addWidget(self.vars_list, 1)
        controls = QVBoxLayout()
        range_row = QHBoxLayout()
        self.since_edit = QDateTimeEdit()
        self.until_edit = QDateTimeEdit()
        self.since_edit.setCalendarPopup(True)
        self.until_edit.setCalendarPopup(True)
        now = QDateTime.currentDateTime()
        self.until_edit.setDateTime(now)
        self.since_edit.setDateTime(now.addSecs(-24*3600))
        range_row.addWidget(QLabel("Desde"))
        range_row.addWidget(self.since_edit)
        range_row.addWidget(QLabel("Hasta"))
        range_row.addWidget(self.until_edit)
        controls.addLayout(range_row)
        quick_row = QHBoxLayout()
        self.btn_1h = QPushButton("1h")
        self.btn_6h = QPushButton("6h")
        self.btn_24h = QPushButton("24h")
        self.btn_hoy = QPushButton("Hoy")
        self.btn_semana = QPushButton("Semana")
        self.btn_todo = QPushButton("30d")
        for b in [self.btn_1h, self.btn_6h, self.btn_24h, self.btn_hoy, self.btn_semana, self.btn_todo]:
            quick_row.addWidget(b)
        controls.addLayout(quick_row)
        btn_row = QHBoxLayout()
        self.plot_btn = QPushButton("Graficar")
        self.export_btn = QPushButton("Exportar PNG")
        btn_row.addStretch(1)
        btn_row.addWidget(self.plot_btn)
        btn_row.addWidget(self.export_btn)
        controls.addLayout(btn_row)
        top.addLayout(controls, 0)
        layout.addLayout(top)
        self._chart = None
        self._chart_view = None
        self._pg = None
        self._pg_plot = None
        self._img_label = None
        self._basic_plot = None
        self._series = []
        self.plot_area = QWidget()
        self._plot_area_layout = QVBoxLayout(self.plot_area)
        layout.addWidget(self.plot_area, 1)
        self.legend_bar = QHBoxLayout()
        layout.addLayout(self.legend_bar)
        self.plot_btn.clicked.connect(self.on_plot)
        self.export_btn.clicked.connect(self.on_export_png)
        self.btn_1h.clicked.connect(lambda: self._quick_range(hours=1))
        self.btn_6h.clicked.connect(lambda: self._quick_range(hours=6))
        self.btn_24h.clicked.connect(lambda: self._quick_range(hours=24))
        self.btn_hoy.clicked.connect(lambda: self._quick_today())
        self.btn_semana.clicked.connect(lambda: self._quick_range(days=7))
        self.btn_todo.clicked.connect(lambda: self._quick_range(days=30))

        self.setStyleSheet("QDialog{background:#ffffff;} QPushButton{padding:8px 12px;border:1px solid #e2e8f0;border-radius:10px;background:#f8fafc;} QPushButton:hover{background:#f1f5f9;}")

    def _safe(self, s):
        s = str(s)
        return "".join(ch if ch.isalnum() or ch in ("-","_"," ") else "_" for ch in s).strip()

    def _iter_dates(self, start_dt, end_dt):
        cur = start_dt.date()
        end_date = end_dt.date()
        while cur.daysTo(end_date) >= 0:
            yield cur
            cur = cur.addDays(1)

    def _read_rows_for_var(self, var, start_dt, end_dt):
        rows = []
        if self.log_cfg.get("mode") == "per_variable":
            vid = var.get("id")
            for d in self._iter_dates(start_dt, end_dt):
                date_str = d.toString("yyyy-MM-dd")
                name = self._safe(var.get("name", var.get("id", "var")))
                paths = set()
                if vid:
                    pattern = os.path.join(self.log_folder, f"*_{vid}_{date_str}.csv")
                    paths.update(glob.glob(pattern))
                paths.add(os.path.join(self.log_folder, f"{name}_{date_str}.csv"))
                for path in sorted(paths):
                    rows.extend(self._read_csv(path, var))
        else:
            for d in self._iter_dates(start_dt, end_dt):
                date_str = d.toString("yyyy-MM-dd")
                daily = os.path.join(self.log_folder, f"termo_{date_str}.csv")
                rows.extend(self._read_csv(daily, var))
            single = os.path.join(self.log_folder, "termo_log.csv")
            rows.extend(self._read_csv(single, var))
        start_py = start_dt.toPyDateTime()
        end_py = end_dt.toPyDateTime()
        rows = [r for r in rows if r[0] >= start_py and r[0] <= end_py]
        rows.sort(key=lambda x: x[0])
        return rows

    def _read_csv(self, path, var):
        data = []
        if not os.path.exists(path):
            return data
        try:
            with open(path, "r", encoding="utf-8") as f:
                sep = (self.log_cfg.get("separator") or ",")
                reader = csv.reader(f, delimiter=sep)
                header = None
                for row in reader:
                    if not header:
                        header = row
                        continue
                    try:
                        ts = QDateTime.fromString(row[0], Qt.ISODate)
                        vid = row[1]
                        name = row[2]
                        val = float(row[4])
                    except Exception:
                        continue
                    if not ts.isValid():
                        continue
                    if vid == var.get("id"):
                        data.append((ts.toPyDateTime(), val))
        except Exception:
            pass
        return data

    def on_plot(self):
        selected = [i.data(Qt.UserRole) for i in self.vars_list.selectedItems()]
        if not selected:
            QMessageBox.information(self, "Gráficos", "Seleccione al menos una variable")
            return
        since = self.since_edit.dateTime()
        until = self.until_edit.dateTime()
        if since > until:
            QMessageBox.warning(self, "Gráficos", "El rango de tiempo es inválido")
            return
        for i in reversed(range(self._plot_area_layout.count())):
            w = self._plot_area_layout.itemAt(i).widget()
            if w:
                w.setParent(None)
        series = []
        for var in selected:
            rows = self._read_rows_for_var(var, since, until)
            if not rows:
                continue
            points = [(r[0].timestamp(), r[1]) for r in rows]
            values = [r[1] for r in rows]
            if not values:
                continue
            avg = sum(values) / max(1, len(values))
            alarm_min = var.get("alarm_min") if var.get("alarm_enabled") else None
            alarm_max = var.get("alarm_max") if var.get("alarm_enabled") else None
            series.append({
                "name": var.get("name"),
                "points": points,
                "min": min(values),
                "max": max(values),
                "avg": avg,
                "visible": True,
                "alarm_min": alarm_min,
                "alarm_max": alarm_max,
            })
        if not series:
            QMessageBox.information(self, "Gráficos", "No hay datos en el rango seleccionado")
            return
        self._series = series
        self._basic_plot = BasicPlot()
        self._basic_plot.set_data(self._series)
        self._plot_area_layout.addWidget(self._basic_plot)
        for i in reversed(range(self.legend_bar.count())):
            it = self.legend_bar.itemAt(i)
            w = it.widget() if it else None
            if w:
                w.setParent(None)
        colors = ['#1f77b4','#ff7f0e','#2ca02c','#d62728','#9467bd','#8c564b']
        for idx, s in enumerate(self._series):
            swatch = QLabel()
            pm = QPixmap(10,10); pm.fill(QColor(colors[idx % len(colors)])); swatch.setPixmap(pm)
            stats = f"min {s['min']:.2f} | avg {s['avg']:.2f} | max {s['max']:.2f}"
            check = QCheckBox(f"{s.get('name','')} ({stats})")
            check.setChecked(True)
            check.toggled.connect(lambda checked, idx=idx: self._toggle_series(idx, checked))
            box = QHBoxLayout(); cont = QWidget(); cont.setLayout(box)
            box.addWidget(swatch); box.addWidget(check)
            box.setContentsMargins(0,0,12,0)
            self.legend_bar.addWidget(cont)

    def _toggle_series(self, idx, checked):
        if not hasattr(self, '_series') or not self._series:
            return
        if idx < 0 or idx >= len(self._series):
            return
        self._series[idx]["visible"] = bool(checked)
        if self._basic_plot:
            self._basic_plot.set_data(self._series)

    def _quick_range(self, hours=0, days=0):
        end = QDateTime.currentDateTime()
        start = end.addSecs(-(hours*3600 + days*24*3600))
        self.since_edit.setDateTime(start)
        self.until_edit.setDateTime(end)
        self.on_plot()

    def _quick_today(self):
        end = QDateTime.currentDateTime()
        start = QDateTime(end.date(), QDateTime().time())
        self.since_edit.setDateTime(start)
        self.until_edit.setDateTime(end)
        self.on_plot()

    def on_export_png(self):
        if not self._basic_plot:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Guardar PNG", os.path.join(self.log_folder, "grafico.png"), "PNG (*.png)")
        if not path:
            return
        pm = self._basic_plot.grab()
        try:
            pm.save(path, "PNG")
            QMessageBox.information(self, "Gráficos", "Imagen exportada")
        except Exception as e:
            QMessageBox.warning(self, "Gráficos", str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TermoCali")
        self.resize(1100, 700)
        self.cfg = load_config()
        if ensure_zones(self.cfg):
            save_config(self.cfg)
        self.worker = None
        self.last_values = {}
        self.last_raw = {}
        self.last_update = {}
        self.alarm_state = {}
        self.alarm_ack = set()
        self.zone_alarm_state = {}
        self.zone_alarm_ack = set()
        self.zone_sections = {}
        self.zone_vars_map = {}
        self.var_map = {}
        self.zone_stats = {}
        self.global_last_update = None
        self.monitor_mode = False
        self.density_mode = self.cfg.get("ui", {}).get("density", "normal")
        cw = QWidget()
        self.setCentralWidget(cw)
        root = QVBoxLayout(cw)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.top_box = QGroupBox("Comunicación")
        top_layout = QGridLayout(self.top_box)
        self.port_combo = QComboBox()
        self._refresh_ports()
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["1200","2400","4800","9600","19200","38400","57600","115200"])
        self.parity_combo = QComboBox()
        self.parity_combo.addItems(["N","E","O"]) 
        self.stop_combo = QComboBox()
        self.stop_combo.addItems(["1","2"]) 
        self.byte_combo = QComboBox()
        self.byte_combo.addItems(["7","8"]) 
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(0.1, 10.0)
        self.timeout_spin.setSingleStep(0.1)
        self.timeout_spin.setValue(float(self.cfg.get("serial", {}).get("timeout", 1.0)))
        self.port_combo.setCurrentText(self.cfg.get("serial", {}).get("port", "COM3"))
        self.baud_combo.setCurrentText(str(self.cfg.get("serial", {}).get("baudrate", 9600)))
        self.parity_combo.setCurrentText(self.cfg.get("serial", {}).get("parity", "N"))
        self.stop_combo.setCurrentText(str(self.cfg.get("serial", {}).get("stopbits", 1)))
        self.byte_combo.setCurrentText(str(self.cfg.get("serial", {}).get("bytesize", 8)))
        top_layout.addWidget(QLabel("Puerto"), 0, 0)
        top_layout.addWidget(self.port_combo, 0, 1)
        top_layout.addWidget(QLabel("Baudios"), 0, 2)
        top_layout.addWidget(self.baud_combo, 0, 3)
        top_layout.addWidget(QLabel("Paridad"), 1, 0)
        top_layout.addWidget(self.parity_combo, 1, 1)
        top_layout.addWidget(QLabel("Stop bits"), 1, 2)
        top_layout.addWidget(self.stop_combo, 1, 3)
        top_layout.addWidget(QLabel("Data bits"), 2, 0)
        top_layout.addWidget(self.byte_combo, 2, 1)
        top_layout.addWidget(QLabel("Timeout (s)"), 2, 2)
        top_layout.addWidget(self.timeout_spin, 2, 3)
        self.connect_btn = QPushButton("Conectar")
        self.disconnect_btn = QPushButton("Desconectar")
        self.disconnect_btn.setEnabled(False)
        top_layout.addWidget(self.connect_btn, 0, 4)
        top_layout.addWidget(self.disconnect_btn, 0, 5)
        self.add_btn = QPushButton("Añadir variable")
        self.save_btn = QPushButton("Guardar JSON")
        self.load_btn = QPushButton("Cargar JSON")
        top_layout.addWidget(self.add_btn, 1, 4)
        top_layout.addWidget(self.save_btn, 1, 5)
        top_layout.addWidget(self.load_btn, 2, 4)
        self.header = QFrame()
        self.header.setObjectName("Header")
        self.header.setStyleSheet("""
            #Header { background:#0ea5e9; border:0; border-radius:0; }
            #Header QLabel#Title { color:#ffffff; font-size:24px; font-weight:800; letter-spacing:0.3px; }
            #Header QPushButton { color:#0f172a; background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:10px 16px; font-weight:600; }
            #Header QPushButton:hover { background:#f8fafc; }
        """)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(16, 10, 16, 10)
        logo_size = 28
        pm = QPixmap(logo_size, logo_size)
        pm.fill(Qt.transparent)
        try:
            qp = QPainter(pm)
            qp.setRenderHint(QPainter.Antialiasing)
            grad = QLinearGradient(0, 0, 0, logo_size)
            grad.setColorAt(0.0, QColor(14, 165, 233))
            grad.setColorAt(1.0, QColor(56, 189, 248))
            qp.setBrush(QBrush(grad))
            qp.setPen(Qt.NoPen)
            qp.drawEllipse(0, 0, logo_size, logo_size)
            qp.setPen(QColor(255,255,255))
            f = QFont(); f.setBold(True); f.setPointSize(14)
            qp.setFont(f)
            qp.drawText(pm.rect(), Qt.AlignCenter, "T")
            qp.end()
        except Exception:
            pass
        self.logo_label = QLabel()
        self.logo_label.setPixmap(pm)
        header_layout.addWidget(self.logo_label)
        self.title_label = QLabel("TermoCali")
        self.title_label.setObjectName("Title")
        header_layout.addWidget(self.title_label)
        conn_box = QWidget()
        conn_layout = QVBoxLayout(conn_box)
        conn_layout.setContentsMargins(8, 0, 8, 0)
        conn_layout.setSpacing(2)
        conn_row = QHBoxLayout()
        conn_row.setContentsMargins(0, 0, 0, 0)
        conn_row.setSpacing(6)
        self.conn_dot = QLabel()
        self.conn_dot.setFixedSize(10, 10)
        self.conn_dot.setStyleSheet("background:#94a3b8;border-radius:5px;")
        self.conn_label = QLabel("Desconectado")
        self.conn_label.setStyleSheet("color:#e2e8f0;font-weight:600;")
        self.conn_meta = QLabel("")
        self.conn_meta.setStyleSheet("color:#e2e8f0;font-size:12px;")
        conn_row.addWidget(self.conn_dot)
        conn_row.addWidget(self.conn_label)
        conn_row.addWidget(self.conn_meta)
        conn_row.addStretch(1)
        self.last_read_label = QLabel("Última lectura: --")
        self.last_read_label.setStyleSheet("color:#e2e8f0;font-size:12px;")
        conn_layout.addLayout(conn_row)
        conn_layout.addWidget(self.last_read_label)
        header_layout.addWidget(conn_box)
        header_layout.addStretch(1)
        self.h_connect_btn = QPushButton("Conectar")
        self.h_disconnect_btn = QPushButton("Desconectar")
        self.h_settings_btn = QPushButton("Configurar")
        self.h_graphs_btn = QPushButton("Gráficos")
        self.h_add_btn = QPushButton("Añadir variable")
        self.h_save_btn = QPushButton("Guardar JSON")
        self.h_load_btn = QPushButton("Cargar JSON")
        self.monitor_btn = QPushButton("Modo monitor")
        self.monitor_btn.setCheckable(True)
        for b in [self.h_connect_btn, self.h_disconnect_btn, self.h_settings_btn, self.h_graphs_btn, self.h_add_btn, self.h_save_btn, self.h_load_btn, self.monitor_btn]:
            header_layout.addWidget(b)
        self.h_disconnect_btn.setEnabled(False)
        self.h_disconnect_btn.setEnabled(False)
        root.addWidget(self.header)
        self.filter_bar = QFrame()
        self.filter_bar.setStyleSheet("QFrame{background:#f8fafc;border-bottom:1px solid #e2e8f0;}")
        filter_layout = QHBoxLayout(self.filter_bar)
        filter_layout.setContentsMargins(12, 6, 12, 6)
        filter_layout.setSpacing(10)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Buscar...")
        self.zone_filter = QComboBox()
        self.type_filter = QComboBox(); self.type_filter.addItems(["Todos", "holding", "input"])
        self.alarm_filter = QComboBox(); self.alarm_filter.addItems(["Todos", "En alarma", "Sin alarma", "ACK"])
        self.stale_filter = QComboBox(); self.stale_filter.addItems(["Todos", "Sin datos", "Actualizados"])
        self.density_combo = QComboBox(); self.density_combo.addItems(["Normal", "Compacto"])
        self.density_combo.setCurrentText("Compacto" if self.density_mode == "compact" else "Normal")
        filter_layout.addWidget(QLabel("Buscar"))
        filter_layout.addWidget(self.search_edit, 1)
        filter_layout.addWidget(QLabel("Zona"))
        filter_layout.addWidget(self.zone_filter)
        filter_layout.addWidget(QLabel("Tipo"))
        filter_layout.addWidget(self.type_filter)
        filter_layout.addWidget(QLabel("Alarmas"))
        filter_layout.addWidget(self.alarm_filter)
        filter_layout.addWidget(QLabel("Estado"))
        filter_layout.addWidget(self.stale_filter)
        filter_layout.addWidget(QLabel("Densidad"))
        filter_layout.addWidget(self.density_combo)
        root.addWidget(self.filter_bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(12, 12, 12, 12)
        self.cards_layout.setSpacing(12)
        self.cards_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.cards_container)
        self.alarm_panel = QFrame()
        self.alarm_panel.setStyleSheet("QFrame{background:#ffffff;border-left:1px solid #e2e8f0;}")
        self.alarm_panel.setMinimumWidth(260)
        alarm_layout = QVBoxLayout(self.alarm_panel)
        alarm_layout.setContentsMargins(10, 10, 10, 10)
        alarm_layout.setSpacing(8)
        self.alarms_title = QLabel("Alarmas (0)")
        self.alarms_title.setStyleSheet("font-weight:700;color:#0f172a;")
        self.alarms_list = QListWidget()
        self.alarms_list.setSpacing(4)
        alarm_layout.addWidget(self.alarms_title)
        alarm_layout.addWidget(self.alarms_list, 1)
        content_wrap = QWidget()
        content_layout = QHBoxLayout(content_wrap)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self.scroll, 1)
        content_layout.addWidget(self.alarm_panel)
        root.addWidget(content_wrap, 1)
        self.status_label = QLabel("Listo")
        root.addWidget(self.status_label)
        self.cards = {}
        self._refresh_zone_filter()
        self._rebuild_cards()
        self.search_edit.textChanged.connect(self.on_filters_changed)
        self.zone_filter.currentIndexChanged.connect(self.on_filters_changed)
        self.type_filter.currentIndexChanged.connect(self.on_filters_changed)
        self.alarm_filter.currentIndexChanged.connect(self.on_filters_changed)
        self.stale_filter.currentIndexChanged.connect(self.on_filters_changed)
        self.density_combo.currentTextChanged.connect(self.on_density_changed)
        self.monitor_btn.toggled.connect(self.set_monitor_mode)
        self.connect_btn.clicked.connect(self.on_connect)
        self.disconnect_btn.clicked.connect(self.on_disconnect)
        self.add_btn.clicked.connect(self.on_add_variable)
        self.save_btn.clicked.connect(self.on_save_config)
        self.load_btn.clicked.connect(self.on_load_config)
        self.h_connect_btn.clicked.connect(self.on_connect)
        self.h_disconnect_btn.clicked.connect(self.on_disconnect)
        self.h_settings_btn.clicked.connect(self.on_open_settings)
        self.h_graphs_btn.clicked.connect(self.on_open_graphs)
        self.h_add_btn.clicked.connect(self.on_add_variable)
        self.h_save_btn.clicked.connect(self.on_save_config)
        self.h_load_btn.clicked.connect(self.on_load_config)
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start(1000)
        self._update_connection_indicator("disconnected")

    def _refresh_ports(self):
        try:
            ports = [p.device for p in list_ports.comports()]
        except Exception:
            ports = []
        self.port_combo.clear()
        self.port_combo.addItems(ports or ["COM1","COM2","COM3","COM4"])

    def serial_cfg(self):
        return {
            "port": self.port_combo.currentText(),
            "baudrate": int(self.baud_combo.currentText()),
            "parity": self.parity_combo.currentText(),
            "stopbits": int(self.stop_combo.currentText()),
            "bytesize": int(self.byte_combo.currentText()),
            "timeout": float(self.timeout_spin.value()),
        }

    def _refresh_zone_filter(self):
        if not hasattr(self, "zone_filter"):
            return
        self.zone_filter.blockSignals(True)
        self.zone_filter.clear()
        self.zone_filter.addItem("Todas", None)
        for zone in self.cfg.get("zones", []):
            self.zone_filter.addItem(zone.get("name", "Zona"), zone.get("id"))
        self.zone_filter.blockSignals(False)

    def on_zone_toggled(self, zone_id, collapsed):
        updated = False
        for zone in self.cfg.get("zones", []):
            if zone.get("id") == zone_id:
                if zone.get("collapsed") != bool(collapsed):
                    zone["collapsed"] = bool(collapsed)
                    updated = True
                break
        if updated:
            save_config(self.cfg)

    def on_filters_changed(self):
        self._rebuild_cards()

    def on_density_changed(self, text):
        self.density_mode = "compact" if text == "Compacto" else "normal"
        self.cfg.setdefault("ui", {})["density"] = self.density_mode
        save_config(self.cfg)
        self._rebuild_cards()

    def set_monitor_mode(self, enabled):
        self.monitor_mode = bool(enabled)
        self.monitor_btn.setText("Salir monitor" if self.monitor_mode else "Modo monitor")
        for b in [self.h_settings_btn, self.h_graphs_btn, self.h_add_btn, self.h_save_btn, self.h_load_btn]:
            b.setVisible(not self.monitor_mode)
        self.filter_bar.setVisible(not self.monitor_mode)
        self._rebuild_cards()

    def _filters_active(self):
        if not hasattr(self, "search_edit"):
            return False
        if self.search_edit.text().strip():
            return True
        if self.zone_filter.currentData():
            return True
        if self.type_filter.currentText() != "Todos":
            return True
        if self.alarm_filter.currentText() != "Todos":
            return True
        if self.stale_filter.currentText() != "Todos":
            return True
        return False

    def _matches_filters(self, var):
        if not hasattr(self, "search_edit"):
            return True
        text = self.search_edit.text().strip().lower()
        if text and text not in str(var.get("name", "")).lower():
            return False
        zone_id = self.zone_filter.currentData()
        if zone_id and var.get("zone_id") != zone_id:
            return False
        typ = self.type_filter.currentText()
        if typ != "Todos" and var.get("type") != typ:
            return False
        alarm_filter = self.alarm_filter.currentText()
        vid = var.get("id")
        in_alarm = self.alarm_state.get(vid, False)
        if alarm_filter == "En alarma" and not in_alarm:
            return False
        if alarm_filter == "Sin alarma" and in_alarm:
            return False
        if alarm_filter == "ACK" and not (in_alarm and vid in self.alarm_ack):
            return False
        stale_filter = self.stale_filter.currentText()
        if stale_filter != "Todos":
            stale = self._is_stale(var, datetime.now())
            if stale_filter == "Sin datos" and not stale:
                return False
            if stale_filter == "Actualizados" and stale:
                return False
        return True

    def _stale_threshold(self, var):
        interval = int(var.get("poll_interval_ms", self.cfg.get("poll_interval_ms", 1000))) / 1000.0
        return max(5.0, interval * 3.0)

    def _is_stale(self, var, now):
        last = self.last_update.get(var.get("id"))
        if not last:
            return True
        return (now - last).total_seconds() > self._stale_threshold(var)

    def _format_last_update(self, last_dt, now):
        if not last_dt:
            return "Sin lecturas"
        delta = int((now - last_dt).total_seconds())
        return f"Actualizado: {last_dt.strftime('%H:%M:%S')} (hace {delta}s)"

    def _evaluate_var_alarm(self, var, value):
        if not var.get("alarm_enabled"):
            return False
        min_v = var.get("alarm_min")
        max_v = var.get("alarm_max")
        if min_v is not None and value < min_v:
            return True
        if max_v is not None and value > max_v:
            return True
        return False

    def _evaluate_zone_alarm(self, zone, avg_value):
        if not zone.get("alarm_enabled") or avg_value is None:
            return False
        min_v = zone.get("alarm_min")
        max_v = zone.get("alarm_max")
        if min_v is not None and avg_value < min_v:
            return True
        if max_v is not None and avg_value > max_v:
            return True
        return False

    def _update_zone_summaries(self, now):
        self.zone_stats = {}
        for zone in self.cfg.get("zones", []):
            zone_id = zone.get("id")
            var_ids = self.zone_vars_map.get(zone_id, [])
            values = []
            active = 0
            units = set()
            for vid in var_ids:
                var = self.var_map.get(vid)
                if not var:
                    continue
                unit = var.get("unit")
                if unit:
                    units.add(unit)
                last_dt = self.last_update.get(vid)
                if last_dt and not self._is_stale(var, now):
                    active += 1
                    if vid in self.last_values:
                        values.append(float(self.last_values.get(vid)))
            total = len(var_ids)
            avg = None
            mn = None
            mx = None
            unit_label = ""
            if len(units) == 1:
                unit_label = units.pop()
            if values:
                avg = sum(values) / max(1, len(values))
                mn = min(values)
                mx = max(values)
                summary = f"Activos {active}/{total} | Prom {avg:.2f}{unit_label} | Min {mn:.2f}{unit_label} | Max {mx:.2f}{unit_label}"
            else:
                summary = f"Activos {active}/{total} | Sin datos"
            self.zone_stats[zone_id] = {
                "avg": avg,
                "min": mn,
                "max": mx,
                "active": active,
                "total": total,
                "unit": unit_label,
            }
            zone_alarm = self._evaluate_zone_alarm(zone, avg)
            self.zone_alarm_state[zone_id] = zone_alarm
            if not zone_alarm:
                self.zone_alarm_ack.discard(zone_id)
            alarm_count = sum(1 for vid in var_ids if self.alarm_state.get(vid))
            section = self.zone_sections.get(zone_id)
            if section:
                section.set_summary(summary, alarm_count=alarm_count, zone_alarm=zone_alarm)

    def _update_alarm_list(self):
        alarms = []
        for vid, var in self.var_map.items():
            if not self.alarm_state.get(vid):
                continue
            value = self.last_values.get(vid)
            unit = var.get("unit", "")
            min_v = var.get("alarm_min")
            max_v = var.get("alarm_max")
            detail = ""
            if value is None:
                detail = "Sin valor"
            elif min_v is not None and value < min_v:
                detail = f"{value:.2f}{unit} < {min_v:.2f}{unit}"
            elif max_v is not None and value > max_v:
                detail = f"{value:.2f}{unit} > {max_v:.2f}{unit}"
            else:
                detail = f"{value:.2f}{unit}"
            alarms.append((vid, var.get("name", "Variable"), detail, vid in self.alarm_ack))
        for zone in self.cfg.get("zones", []):
            zid = zone.get("id")
            if not self.zone_alarm_state.get(zid):
                continue
            stats = self.zone_stats.get(zid, {})
            avg = stats.get("avg")
            unit = stats.get("unit", "")
            min_v = zone.get("alarm_min")
            max_v = zone.get("alarm_max")
            detail = "Sin datos"
            if avg is not None:
                detail = f"Prom {avg:.2f}{unit}"
                if min_v is not None and avg < min_v:
                    detail = f"{avg:.2f}{unit} < {min_v:.2f}{unit}"
                elif max_v is not None and avg > max_v:
                    detail = f"{avg:.2f}{unit} > {max_v:.2f}{unit}"
            alarms.append((f"zone:{zid}", f"Zona: {zone.get('name','Zona')}", detail, zid in self.zone_alarm_ack))
        self.alarms_list.clear()
        for alarm_id, title, detail, acked in alarms:
            item = QListWidgetItem()
            row = AlarmRow(alarm_id, title, detail, acked=acked)
            row.ack_clicked.connect(self.on_alarm_ack)
            item.setSizeHint(row.sizeHint())
            self.alarms_list.addItem(item)
            self.alarms_list.setItemWidget(item, row)
        self.alarms_title.setText(f"Alarmas ({len(alarms)})")

    def _cleanup_state(self):
        valid_ids = {v.get("id") for v in self.cfg.get("variables", [])}
        self.last_values = {k: v for k, v in self.last_values.items() if k in valid_ids}
        self.last_raw = {k: v for k, v in self.last_raw.items() if k in valid_ids}
        self.last_update = {k: v for k, v in self.last_update.items() if k in valid_ids}
        self.alarm_state = {k: v for k, v in self.alarm_state.items() if k in valid_ids}
        self.alarm_ack = {k for k in self.alarm_ack if k in valid_ids}
        valid_zones = {z.get("id") for z in self.cfg.get("zones", [])}
        self.zone_alarm_state = {k: v for k, v in self.zone_alarm_state.items() if k in valid_zones}
        self.zone_alarm_ack = {k for k in self.zone_alarm_ack if k in valid_zones}

    def on_alarm_ack(self, alarm_id):
        if alarm_id.startswith("zone:"):
            zid = alarm_id.split(":", 1)[1]
            self.zone_alarm_ack.add(zid)
        else:
            self.alarm_ack.add(alarm_id)
        self._update_alarm_list()
        self.refresh_status()

    def refresh_status(self):
        now = datetime.now()
        for vid, card in self.cards.items():
            var = self.var_map.get(vid)
            if not var:
                continue
            stale = self._is_stale(var, now)
            in_alarm = self.alarm_state.get(vid, False)
            acked = vid in self.alarm_ack
            card.set_state(stale=stale, in_alarm=in_alarm, acked=acked)
            card.set_last_update(self._format_last_update(self.last_update.get(vid), now))
        self._update_zone_summaries(now)
        self._update_alarm_list()
        if self.global_last_update:
            delta = int((now - self.global_last_update).total_seconds())
            self.last_read_label.setText(f"Última lectura: hace {delta}s")
        else:
            self.last_read_label.setText("Última lectura: --")

    def _update_connection_indicator(self, state, message=None):
        if state == "connecting":
            self.conn_dot.setStyleSheet("background:#f59e0b;border-radius:5px;")
            self.conn_label.setText("Conectando")
        elif state == "connected":
            self.conn_dot.setStyleSheet("background:#22c55e;border-radius:5px;")
            self.conn_label.setText("Conectado")
        elif state == "error":
            self.conn_dot.setStyleSheet("background:#ef4444;border-radius:5px;")
            self.conn_label.setText("Error")
        else:
            self.conn_dot.setStyleSheet("background:#94a3b8;border-radius:5px;")
            self.conn_label.setText("Desconectado")
        ser = self.cfg.get("serial", {})
        port = ser.get("port", "")
        baud = ser.get("baudrate", "")
        self.conn_meta.setText(f"{port} @ {baud}" if port else "")
        if message:
            self.status_label.setText(message)

    def _rebuild_cards(self):
        for i in reversed(range(self.cards_layout.count())):
            w = self.cards_layout.itemAt(i).widget()
            if w:
                w.setParent(None)
        self.cards.clear()
        self.zone_sections.clear()
        self.zone_vars_map.clear()
        dirty = ensure_zones(self.cfg)
        vars_list = self.cfg.get("variables", [])
        if not vars_list:
            default_zone_id = self.cfg.get("zones", [{}])[0].get("id")
            sample = {
                "id": str(uuid.uuid4()),
                "name": "Temperatura 1",
                "unit": "°C",
                "zone_id": default_zone_id,
                "alarm_enabled": False,
                "alarm_min": None,
                "alarm_max": None,
                "slave": 1,
                "type": "holding",
                "address": 0,
                "data_type": "uint16",
                "scale": 1.0,
                "decimal_shift": 0,
                "offset": 0.0,
                "decimals": 1,
                "poll_interval_ms": int(self.cfg.get("poll_interval_ms", 1000)),
                "enabled": True,
            }
            self.cfg["variables"] = [sample]
            dirty = True
            vars_list = self.cfg.get("variables", [])
        zones = self.cfg.get("zones", [])
        monitor_zones = [z for z in zones if z.get("monitor")]
        self.var_map = {}
        vars_by_zone = {z.get("id"): [] for z in zones}
        for var in vars_list:
            vid = var.get("id")
            if not vid:
                vid = str(uuid.uuid4())
                var["id"] = vid
                dirty = True
            self.var_map[vid] = var
            zone_id = var.get("zone_id")
            if zone_id not in vars_by_zone:
                zone_id = zones[0].get("id") if zones else None
                var["zone_id"] = zone_id
                dirty = True
            vars_by_zone.setdefault(zone_id, []).append(var)
        self.zone_vars_map = {zid: [v.get("id") for v in vlist] for zid, vlist in vars_by_zone.items()}
        zone_filter_id = self.zone_filter.currentData() if hasattr(self, "zone_filter") else None
        filters_active = self._filters_active()
        cols = 2 if self.monitor_mode else 3
        for zone in zones:
            zone_id = zone.get("id")
            if self.monitor_mode and monitor_zones and not zone.get("monitor"):
                continue
            if zone_filter_id and zone_id != zone_filter_id:
                continue
            zone_vars_all = vars_by_zone.get(zone_id, [])
            zone_vars = [v for v in zone_vars_all if self._matches_filters(v)]
            if not zone_vars and (filters_active or self.monitor_mode or zone_filter_id):
                continue
            zone_title = zone.get("name", "Zona")
            section = CollapsibleSection(zone_id, zone_title, collapsed=bool(zone.get("collapsed", False)))
            section.toggled.connect(self.on_zone_toggled)
            self.zone_sections[zone_id] = section
            if not zone_vars:
                empty = QLabel("Sin variables")
                empty.setStyleSheet("color:#94a3b8;padding:4px 8px;")
                section.content_layout.addWidget(empty, 0, 0)
            for idx, var in enumerate(zone_vars):
                vid = var.get("id")
                card = VariableCard(var)
                card.set_density(self.density_mode, monitor=self.monitor_mode)
                card.config_btn.setVisible(not self.monitor_mode)
                if vid in self.last_values:
                    card.set_value(self.last_values.get(vid), self.last_raw.get(vid))
                r = idx // cols
                c = idx % cols
                section.content_layout.addWidget(card, r, c)
                self.cards[vid] = card
                card.config_btn.clicked.connect(lambda _, vid=vid: self.on_open_settings(vid))
            self.cards_layout.addWidget(section)
        if dirty:
            save_config(self.cfg)
        self.refresh_status()

    def on_connect(self):
        save_config(self.cfg)
        if self.worker and self.worker.isRunning():
            return
        self.worker = PollingWorker(
            self.cfg.get("serial", {}),
            self.cfg.get("variables", []),
            self.cfg.get("logging", {})
        )
        self.worker.connected.connect(self.on_worker_connected)
        self.worker.value_updated.connect(self.on_value_update)
        self.worker.error.connect(self.on_var_error)
        self.worker.status.connect(self.on_status)
        self.global_last_update = None
        self.worker.start()
        self.status_label.setText("Conectando...")
        self._update_connection_indicator("connecting")
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(False)
        self.h_connect_btn.setEnabled(False)
        self.h_disconnect_btn.setEnabled(False)

    def on_disconnect(self):
        if self.worker:
            try:
                self.worker.stop()
                self.worker.wait(2000)
            except Exception:
                pass
            self.worker = None
        self.status_label.setText("Desconectado")
        self._update_connection_indicator("disconnected")
        self.last_read_label.setText("Última lectura: --")
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.h_connect_btn.setEnabled(True)
        self.h_disconnect_btn.setEnabled(False)

    def on_worker_connected(self, ok, message):
        if not ok:
            self.status_label.setText(message or "No se pudo conectar")
            self._update_connection_indicator("error", message)
            self.connect_btn.setEnabled(True)
            self.disconnect_btn.setEnabled(False)
            self.h_connect_btn.setEnabled(True)
            self.h_disconnect_btn.setEnabled(False)
            try:
                if self.worker:
                    self.worker.stop()
                    self.worker.wait(2000)
            except Exception:
                pass
            self.worker = None
            return
        self.status_label.setText("Conectado")
        self._update_connection_indicator("connected")
        self.disconnect_btn.setEnabled(True)
        self.h_disconnect_btn.setEnabled(True)

    def on_add_variable(self):
        self.on_open_settings()

    def on_edit_variable(self, vid):
        var = next((v for v in self.cfg.get("variables", []) if v.get("id") == vid), None)
        if not var:
            return
        dlg = VariableDialog(self, data=var)
        dlg.show()
        while dlg.isVisible():
            QApplication.processEvents()
            time.sleep(0.01)
        data = getattr(dlg, "data", None)
        if not data:
            return
        idx = next((i for i, v in enumerate(self.cfg.get("variables", [])) if v.get("id") == vid), -1)
        if idx >= 0:
            self.cfg["variables"][idx] = data
        save_config(self.cfg)
        card = self.cards.get(vid)
        if card:
            card.update_meta(data)
        if self.worker:
            self.worker.set_variables(self.cfg.get("variables", []))

    def on_delete_variable(self, vid):
        if QMessageBox.question(self, "Confirmar", "¿Eliminar variable?") != QMessageBox.Yes:
            return
        self.cfg["variables"] = [v for v in self.cfg.get("variables", []) if v.get("id") != vid]
        save_config(self.cfg)
        self._rebuild_cards()
        if self.worker:
            self.worker.set_variables(self.cfg.get("variables", []))

    def on_toggle_variable(self, vid, state):
        for v in self.cfg.get("variables", []):
            if v.get("id") == vid:
                v["enabled"] = state == Qt.Checked
                break
        save_config(self.cfg)
        if self.worker:
            self.worker.set_variables(self.cfg.get("variables", []))

    def on_open_settings(self, selected_id=None):
        dlg = SettingsDialog(self, self.cfg, selected_id)
        if dlg.exec_() == QDialog.Accepted:
            new_cfg = dlg.result_config()
            serial_changed = json.dumps(self.cfg.get("serial", {}), sort_keys=True) != json.dumps(new_cfg.get("serial", {}), sort_keys=True)
            logging_changed = json.dumps(self.cfg.get("logging", {}), sort_keys=True) != json.dumps(new_cfg.get("logging", {}), sort_keys=True)
            was_running = self.worker.isRunning() if self.worker else False
            self.cfg = new_cfg
            ensure_zones(self.cfg)
            self._cleanup_state()
            self._refresh_zone_filter()
            self.density_mode = self.cfg.get("ui", {}).get("density", self.density_mode)
            if hasattr(self, "density_combo"):
                self.density_combo.setCurrentText("Compacto" if self.density_mode == "compact" else "Normal")
            save_config(self.cfg)
            self._rebuild_cards()
            if self.worker:
                if serial_changed:
                    self.on_disconnect()
                    if was_running:
                        self.on_connect()
                else:
                    self.worker.set_variables(self.cfg.get("variables", []))
                    if logging_changed:
                        self.worker.set_logging(self.cfg.get("logging", {}))
            self._update_connection_indicator("connected" if (self.worker and self.worker.isRunning()) else "disconnected")
            self.status_label.setText("Configuración aplicada")

    def on_open_graphs(self):
        try:
            dlg = GraphsDialog(self, self.cfg)
            dlg.exec_()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def on_save_config(self):
        path, _ = QFileDialog.getSaveFileName(self, "Guardar JSON", CONFIG_FILE, "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w") as f:
                json.dump(self.cfg, f, indent=2)
            self.status_label.setText(f"Guardado: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def on_load_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "Cargar JSON", CONFIG_FILE, "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r") as f:
                self.cfg = json.load(f)
            ensure_zones(self.cfg)
            self._cleanup_state()
            self._refresh_zone_filter()
            self.density_mode = self.cfg.get("ui", {}).get("density", self.density_mode)
            if hasattr(self, "density_combo"):
                self.density_combo.setCurrentText("Compacto" if self.density_mode == "compact" else "Normal")
            save_config(self.cfg)
            self._rebuild_cards()
            if self.worker:
                self.worker.set_variables(self.cfg.get("variables", []))
                self.worker.set_logging(self.cfg.get("logging", {}))
            self.status_label.setText(f"Cargado: {os.path.basename(path)}")
            self._update_connection_indicator("connected" if (self.worker and self.worker.isRunning()) else "disconnected")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def on_value_update(self, vid, value, raw):
        now = datetime.now()
        self.last_values[vid] = float(value)
        self.last_raw[vid] = raw
        self.last_update[vid] = now
        self.global_last_update = now
        var = self.var_map.get(vid)
        if var:
            in_alarm = self._evaluate_var_alarm(var, float(value))
            self.alarm_state[vid] = in_alarm
            if not in_alarm:
                self.alarm_ack.discard(vid)
        card = self.cards.get(vid)
        if card:
            card.set_value(value, raw)
            if var:
                stale = self._is_stale(var, now)
                card.set_state(stale=stale, in_alarm=self.alarm_state.get(vid, False), acked=vid in self.alarm_ack)
                card.set_last_update(self._format_last_update(self.last_update.get(vid), now))

    def on_var_error(self, vid, message):
        card = self.cards.get(vid)
        if card:
            card.set_error()
        self.last_update.pop(vid, None)
        self.status_label.setText(message)

    def on_status(self, message):
        self.status_label.setText(message)

    def closeEvent(self, e):
        try:
            save_config(self.cfg)
        except Exception:
            pass
        try:
            if self.worker:
                self.worker.stop()
                self.worker.wait(2000)
        except Exception:
            pass
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    try:
        app.setStyle(QStyleFactory.create("Fusion"))
        pal = QPalette()
        pal.setColor(QPalette.Window, QColor(250, 250, 250))
        pal.setColor(QPalette.WindowText, Qt.black)
        pal.setColor(QPalette.Base, QColor(255, 255, 255))
        pal.setColor(QPalette.AlternateBase, QColor(245, 245, 245))
        pal.setColor(QPalette.ToolTipBase, Qt.white)
        pal.setColor(QPalette.ToolTipText, Qt.black)
        pal.setColor(QPalette.Text, Qt.black)
        pal.setColor(QPalette.Button, QColor(248, 248, 248))
        pal.setColor(QPalette.ButtonText, Qt.black)
        pal.setColor(QPalette.BrightText, Qt.red)
        pal.setColor(QPalette.Highlight, QColor(64, 158, 255))
        pal.setColor(QPalette.HighlightedText, Qt.white)
        app.setPalette(pal)
        app.setStyleSheet("""
            QToolBar { spacing: 6px; }
            QPushButton { border-radius: 6px; }
            QGroupBox { font-weight: 600; }
        """)
    except Exception:
        pass
    w = MainWindow()
    w.showMaximized()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
