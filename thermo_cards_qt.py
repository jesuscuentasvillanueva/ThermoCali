import sys
import os
import json
import time
import uuid
import csv
from datetime import datetime, timedelta
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QFrame, QScrollArea, QFileDialog, QMessageBox, QCheckBox, QGridLayout, QGroupBox, QDialog, QTabWidget, QToolBar, QAction, QStyle, QSizePolicy, QStyleFactory, QGraphicsDropShadowEffect, QDateTimeEdit, QListWidget, QListWidgetItem
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QDateTime
from PyQt5.QtGui import QPalette, QColor
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
        "variables": [],
        "logging": {
            "enabled": False,
            "folder": os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"),
            "mode": "per_variable",
            "separator": ","
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
        }
        self.close()


class VariableCard(QFrame):
    def __init__(self, var):
        super().__init__()
        self.var = var
        self.setFrameShape(QFrame.Panel)
        self.setFrameShadow(QFrame.Raised)
        self.setStyleSheet("QFrame{border:1px solid #e5e7eb;border-radius:12px;background:#ffffff;} QPushButton{padding:8px 12px;border:1px solid #e5e7eb;border-radius:8px;background:#f8fafc;} QPushButton:hover{background:#f1f5f9;}")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 40))
        self.setGraphicsEffect(shadow)
        v = QVBoxLayout(self)
        h = QHBoxLayout()
        self.title = QLabel(self.var.get("name", "Temperatura"))
        self.title.setStyleSheet("font-weight:700;font-size:18px;color:#0f172a;")
        self.status = QLabel("●")
        self.status.setStyleSheet("color:gray;font-size:14px;")
        h.addWidget(self.title)
        h.addStretch(1)
        h.addWidget(self.status)
        v.addLayout(h)
        c = QHBoxLayout()
        self.value_label = QLabel("--")
        self.value_label.setStyleSheet("font-size:34px;font-weight:700;color:#0f172a;")
        self.unit_label = QLabel(self.var.get("unit", "°C"))
        self.unit_label.setStyleSheet("font-size:14px;color:#475569;background:#eef2ff;border-radius:10px;padding:2px 8px;")
        c.addWidget(self.value_label)
        c.addWidget(self.unit_label)
        c.addStretch(1)
        v.addLayout(c)
        chips = QHBoxLayout()
        self.chip_slave = QLabel("")
        self.chip_type = QLabel("")
        self.chip_addr = QLabel("")
        self.chip_shift = QLabel("")
        self.chip_scale = QLabel("")
        for ch in [self.chip_slave, self.chip_type, self.chip_addr, self.chip_shift, self.chip_scale]:
            ch.setStyleSheet("color:#334155;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:12px;padding:2px 8px;font-size:12px;")
            chips.addWidget(ch)
        chips.addStretch(1)
        v.addLayout(chips)
        self._update_chips()
        b = QHBoxLayout()
        self.config_btn = QPushButton("Configurar")
        b.addStretch(1)
        b.addWidget(self.config_btn)
        v.addLayout(b)

    def _update_chips(self):
        self.chip_slave.setText(f"S{self.var.get('slave', 1)}")
        self.chip_type.setText(self.var.get('type', 'holding'))
        self.chip_addr.setText(f"R{self.var.get('address', 0)}")
        shift = int(self.var.get('decimal_shift', 0))
        self.chip_shift.setVisible(shift != 0)
        if shift != 0:
            self.chip_shift.setText(f"÷10^{shift}" if shift > 0 else f"×10^{abs(shift)}")
        sc = float(self.var.get('scale', 1.0))
        self.chip_scale.setVisible(sc != 1.0)
        if sc != 1.0:
            self.chip_scale.setText(f"×{sc}")

    def set_value(self, value, raw):
        dec = int(self.var.get("decimals", 1))
        try:
            text = f"{float(value):.{dec}f}"
        except Exception:
            text = str(value)
        self.value_label.setText(text)
        self.status.setStyleSheet("color:#2ecc71;")

    def set_error(self):
        self.status.setStyleSheet("color:#e74c3c;")

    def update_meta(self, var):
        self.var = var
        self.title.setText(self.var.get("name", "Temperatura"))
        self.unit_label.setText(self.var.get("unit", "°C"))
        self._update_chips()


class PollingWorker(QThread):
    value_updated = pyqtSignal(str, float, int)
    error = pyqtSignal(str, str)
    status = pyqtSignal(str)

    def __init__(self, serial_cfg, variables, logging_cfg=None):
        super().__init__()
        self.serial_cfg = serial_cfg
        self.variables = list(variables)
        self.running = False
        self.client = None
        self.next_due = {}
        self.logging_cfg = logging_cfg or {}
        self.logger = CSVLogger(self.logging_cfg)

    def set_variables(self, variables):
        self.variables = list(variables)
        try:
            self.logger.set_variables_snapshot(self.variables)
        except Exception:
            pass

    def set_logging(self, logging_cfg):
        self.logging_cfg = logging_cfg or {}
        self.logger.update_config(self.logging_cfg)

    def run(self):
        self.client = ModbusSerialClient(
            port=self.serial_cfg.get("port"),
            baudrate=int(self.serial_cfg.get("baudrate", 9600)),
            parity=self.serial_cfg.get("parity", "N"),
            stopbits=int(self.serial_cfg.get("stopbits", 1)),
            bytesize=int(self.serial_cfg.get("bytesize", 8)),
            timeout=float(self.serial_cfg.get("timeout", 1.0)),
        )
        try:
            if not self.client.connect():
                self.status.emit(f"No se pudo conectar a {self.serial_cfg.get('port')}")
                return
        except Exception as e:
            self.status.emit(str(e))
            return
        self.running = True
        while self.running:
            now = time.monotonic()
            vars_snapshot = list(self.variables)
            idle = True
            for var in vars_snapshot:
                if not var.get("enabled", True):
                    continue
                vid = var.get("id")
                interval = int(var.get("poll_interval_ms", 1000)) / 1000.0
                due = self.next_due.get(vid, 0)
                if now < due:
                    continue
                idle = False
                try:
                    raw, value = self.read_var(var)
                    self.value_updated.emit(vid, value, raw)
                    try:
                        self.logger.log(var, raw, value)
                    except Exception:
                        pass
                    self.next_due[vid] = time.monotonic() + interval
                except Exception as e:
                    self.error.emit(vid, str(e))
                    self.next_due[vid] = time.monotonic() + interval
            if idle:
                time.sleep(0.05)
        try:
            self.client.close()
        except Exception:
            pass

    def stop(self):
        self.running = False

    def read_var(self, var):
        addr = int(var.get("address", 0))
        slave = int(var.get("slave", 1))
        typ = var.get("type", "holding")
        dtype = var.get("data_type", "uint16")
        if typ == "holding":
            resp = self.client.read_holding_registers(address=addr, count=1, slave=slave)
        else:
            resp = self.client.read_input_registers(address=addr, count=1, slave=slave)
        if hasattr(resp, "isError") and resp.isError():
            raise RuntimeError(str(resp))
        reg = int(resp.registers[0])
        if dtype == "int16":
            if reg > 32767:
                reg = reg - 65536
        scale = float(var.get("scale", 1.0))
        offset = float(var.get("offset", 0.0))
        shift = int(var.get("decimal_shift", 0))
        factor = (10.0 ** (-shift)) if shift != 0 else 1.0
        value = reg * factor * scale + offset
        return int(resp.registers[0]), value


class CSVLogger:
    def __init__(self, cfg):
        self.update_config(cfg)
        self._vars = []

    def update_config(self, cfg):
        self.cfg = cfg or {}
        self.enabled = bool(self.cfg.get("enabled", False))
        self.folder = self.cfg.get("folder") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        self.mode = self.cfg.get("mode", "per_variable")  # daily | single | per_variable
        self.sep = self.cfg.get("separator", ",")
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
            return os.path.join(self.folder, f"{name}_{date_str}.csv")
        return os.path.join(self.folder, f"termo_{date_str}.csv")

    def log(self, var, raw, value):
        if not self.enabled:
            return
        ts = datetime.now()
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

    def __init__(self, var):
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
        self.slave_spin = QSpinBox(); self.slave_spin.setRange(0,247); self.slave_spin.setValue(int(self.var.get("slave",1)))
        self.type_combo = QComboBox(); self.type_combo.addItems(["holding","input"]); self.type_combo.setCurrentText(self.var.get("type","holding"))
        self.addr_spin = QSpinBox(); self.addr_spin.setRange(0,65535); self.addr_spin.setValue(int(self.var.get("address",0)))
        self.dtype_combo = QComboBox(); self.dtype_combo.addItems(["uint16","int16"]); self.dtype_combo.setCurrentText(self.var.get("data_type","uint16"))
        self.scale_spin = QDoubleSpinBox(); self.scale_spin.setDecimals(6); self.scale_spin.setRange(-1e6,1e6); self.scale_spin.setSingleStep(0.1); self.scale_spin.setValue(float(self.var.get("scale",1.0)))
        self.dec_shift_spin = QSpinBox(); self.dec_shift_spin.setRange(-9,9); self.dec_shift_spin.setSingleStep(1); self.dec_shift_spin.setValue(int(self.var.get("decimal_shift",0)))
        self.offset_spin = QDoubleSpinBox(); self.offset_spin.setDecimals(6); self.offset_spin.setRange(-1e6,1e6); self.offset_spin.setSingleStep(0.1); self.offset_spin.setValue(float(self.var.get("offset",0.0)))
        self.decimals_spin = QSpinBox(); self.decimals_spin.setRange(0,6); self.decimals_spin.setValue(int(self.var.get("decimals",1)))
        self.interval_spin = QSpinBox(); self.interval_spin.setRange(100,60000); self.interval_spin.setSingleStep(100); self.interval_spin.setValue(int(self.var.get("poll_interval_ms",1000)))
        self.enabled_check = QCheckBox("Activo"); self.enabled_check.setChecked(bool(self.var.get("enabled",True)))
        fields = [
            ("Esclavo", self.slave_spin),
            ("Tipo", self.type_combo),
            ("Dirección", self.addr_spin),
            ("Formato", self.dtype_combo),
            ("Desplazar coma", self.dec_shift_spin),
            ("Escala", self.scale_spin),
            ("Offset", self.offset_spin),
            ("Decimales", self.decimals_spin),
            ("Intervalo ms", self.interval_spin),
        ]
        for i,(lbl,w) in enumerate(fields):
            g.addWidget(QLabel(lbl), i//2, (i%2)*2)
            g.addWidget(w, i//2, (i%2)*2+1)
        g.addWidget(self.enabled_check, 4, 0, 1, 2)
        v.addLayout(g)
        self.del_btn.clicked.connect(lambda: self.delete_requested.emit(self.var.get("id")))

    def data(self):
        return {
            "id": self.var.get("id"),
            "name": self.name_edit.text().strip() or "Temperatura",
            "unit": self.unit_edit.text().strip() or "°C",
            "slave": int(self.slave_spin.value()),
            "type": self.type_combo.currentText(),
            "address": int(self.addr_spin.value()),
            "data_type": self.dtype_combo.currentText(),
            "scale": float(self.scale_spin.value()),
            "decimal_shift": int(self.dec_shift_spin.value()),
            "offset": float(self.offset_spin.value()),
            "decimals": int(self.decimals_spin.value()),
            "poll_interval_ms": int(self.interval_spin.value()),
            "enabled": bool(self.enabled_check.isChecked()),
        }


class SettingsDialog(QDialog):
    def __init__(self, parent, cfg, selected_id=None):
        super().__init__(parent)
        self.setWindowTitle("Configuración")
        self.resize(900, 650)
        self._selected_id = selected_id
        self._cfg = json.loads(json.dumps(cfg))
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs)
        self._build_comm_tab()
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
        self.timeout_spin = QDoubleSpinBox(); self.timeout_spin.setRange(0.1,10.0); self.timeout_spin.setSingleStep(0.1)
        self.global_poll_spin = QSpinBox(); self.global_poll_spin.setRange(100,60000); self.global_poll_spin.setSingleStep(100)
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
        if self._selected_id:
            self._focus_selected()

    def _build_log_tab(self):
        w = QWidget(); g = QGridLayout(w)
        log = self._cfg.get("logging", {})
        self.log_enabled = QCheckBox("Habilitar guardado CSV")
        self.log_enabled.setChecked(bool(log.get("enabled", False)))
        self.log_folder = QLineEdit(log.get("folder", os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")))
        self.log_browse = QPushButton("Examinar…")
        self.log_mode = QComboBox(); self.log_mode.addItems(["per_variable","daily","single"]); self.log_mode.setCurrentText(log.get("mode","per_variable"))
        self.log_sep = QComboBox(); self.log_sep.addItems([",",";","\t"]); self.log_sep.setCurrentText(log.get("separator", ","))
        g.addWidget(self.log_enabled, 0, 0, 1, 2)
        g.addWidget(QLabel("Carpeta"), 1, 0); g.addWidget(self.log_folder, 1, 1); g.addWidget(self.log_browse, 1, 2)
        g.addWidget(QLabel("Modo"), 2, 0); g.addWidget(self.log_mode, 2, 1)
        g.addWidget(QLabel("Separador"), 3, 0); g.addWidget(self.log_sep, 3, 1)
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
        if var is None:
            var = {
                "id": str(uuid.uuid4()),
                "name": f"Temperatura {self.vars_layout.count()+1}",
                "unit": "°C",
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
        form = VariableForm(var)
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
            "variables": [],
            "logging": {
                "enabled": bool(self.log_enabled.isChecked()),
                "folder": self.log_folder.text().strip() or os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"),
                "mode": self.log_mode.currentText(),
                "separator": self.log_sep.currentText(),
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
        btn_row = QHBoxLayout()
        self.plot_btn = QPushButton("Graficar")
        btn_row.addStretch(1)
        btn_row.addWidget(self.plot_btn)
        controls.addLayout(btn_row)
        top.addLayout(controls, 0)
        layout.addLayout(top)
        self._pg = None
        self.plot = None
        self.plot_area = QWidget()
        self._plot_area_layout = QVBoxLayout(self.plot_area)
        layout.addWidget(self.plot_area, 1)
        self.plot_btn.clicked.connect(self.on_plot)

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
            for d in self._iter_dates(start_dt, end_dt):
                date_str = d.toString("yyyy-MM-dd")
                name = self._safe(var.get("name", var.get("id", "var")))
                path = os.path.join(self.log_folder, f"{name}_{date_str}.csv")
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
        if self._pg is None or self.plot is None:
            try:
                import pyqtgraph as pg  # type: ignore
                self._pg = pg
                try:
                    axis = pg.graphicsItems.DateAxisItem.DateAxisItem(orientation='bottom')
                    self.plot = pg.PlotWidget(axisItems={'bottom': axis})
                except Exception:
                    self.plot = pg.PlotWidget()
                self.plot.addLegend()
                self.plot.showGrid(x=True, y=True, alpha=0.3)
                self.plot.setLabel('bottom', 'Tiempo')
                self.plot.setLabel('left', 'Valor')
                self._plot_area_layout.addWidget(self.plot)
            except Exception:
                QMessageBox.warning(self, "Gráficos", "pyqtgraph no está disponible")
                return
        self.plot.clear()
        for var in selected:
            rows = self._read_rows_for_var(var, since, until)
            if not rows:
                continue
            xs = [r[0].timestamp() for r in rows]
            ys = [r[1] for r in rows]
            pen = self._pg.mkPen(width=2)
            self.plot.plot(xs, ys, pen=pen, name=var.get("name"))
        self.plot.enableAutoRange(axis='xy', enable=True)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TermoCali")
        self.resize(1100, 700)
        self.cfg = load_config()
        self.worker = None
        cw = QWidget()
        self.setCentralWidget(cw)
        root = QVBoxLayout(cw)
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
            #Header QLabel#Title { color:#ffffff; font-size:22px; font-weight:700; }
            #Header QPushButton { color:#0f172a; background:#ffffff; border:1px solid #e2e8f0; border-radius:10px; padding:8px 14px; }
            #Header QPushButton:hover { background:#f8fafc; }
        """)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(16, 10, 16, 10)
        self.title_label = QLabel("TermoCali")
        self.title_label.setObjectName("Title")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        self.h_connect_btn = QPushButton("Conectar")
        self.h_disconnect_btn = QPushButton("Desconectar")
        self.h_settings_btn = QPushButton("Configurar")
        self.h_graphs_btn = QPushButton("Gráficos")
        self.h_add_btn = QPushButton("Añadir variable")
        self.h_save_btn = QPushButton("Guardar JSON")
        self.h_load_btn = QPushButton("Cargar JSON")
        for b in [self.h_connect_btn, self.h_disconnect_btn, self.h_settings_btn, self.h_graphs_btn, self.h_add_btn, self.h_save_btn, self.h_load_btn]:
            header_layout.addWidget(b)
        self.h_disconnect_btn.setEnabled(False)
        root.addWidget(self.header)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.cards_container = QWidget()
        self.cards_layout = QGridLayout(self.cards_container)
        self.cards_layout.setSpacing(12)
        self.scroll.setWidget(self.cards_container)
        root.addWidget(self.scroll, 1)
        self.status_label = QLabel("Listo")
        root.addWidget(self.status_label)
        self.cards = {}
        self._rebuild_cards()
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

    def _rebuild_cards(self):
        for i in reversed(range(self.cards_layout.count())):
            w = self.cards_layout.itemAt(i).widget()
            if w:
                w.setParent(None)
        self.cards.clear()
        vars_list = self.cfg.get("variables", [])
        if not vars_list:
            sample = {
                "id": str(uuid.uuid4()),
                "name": "Temperatura 1",
                "unit": "°C",
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
            save_config(self.cfg)
            vars_list = self.cfg.get("variables", [])
        cols = 3
        for idx, var in enumerate(vars_list):
            card = VariableCard(var)
            r = idx // cols
            c = idx % cols
            self.cards_layout.addWidget(card, r, c)
            self.cards[var["id"]] = card
            card.config_btn.clicked.connect(lambda _, vid=var["id"]: self.on_open_settings(vid))

    def on_connect(self):
        save_config(self.cfg)
        if self.worker and self.worker.isRunning():
            return
        self.worker = PollingWorker(
            self.cfg.get("serial", {}),
            self.cfg.get("variables", []),
            self.cfg.get("logging", {})
        )
        self.worker.value_updated.connect(self.on_value_update)
        self.worker.error.connect(self.on_var_error)
        self.worker.status.connect(self.on_status)
        self.worker.start()
        self.status_label.setText("Conectado")
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(True)
        self.h_connect_btn.setEnabled(False)
        self.h_disconnect_btn.setEnabled(True)

    def on_disconnect(self):
        if self.worker:
            try:
                self.worker.stop()
                self.worker.wait(2000)
            except Exception:
                pass
            self.worker = None
        self.status_label.setText("Desconectado")
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.h_connect_btn.setEnabled(True)
        self.h_disconnect_btn.setEnabled(False)

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
            save_config(self.cfg)
            self._rebuild_cards()
            if self.worker:
                self.worker.set_variables(self.cfg.get("variables", []))
                self.worker.set_logging(self.cfg.get("logging", {}))
            self.status_label.setText(f"Cargado: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def on_value_update(self, vid, value, raw):
        card = self.cards.get(vid)
        if card:
            card.set_value(value, raw)

    def on_var_error(self, vid, message):
        card = self.cards.get(vid)
        if card:
            card.set_error()
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
