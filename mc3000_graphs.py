"""
MC3000 Real-time Graphs

Real-time plotting widgets for monitoring battery charging data.
Uses pyqtgraph for fast, interactive plots.

The history of a slot covers the whole run of a program (up to 48 h at
1 Hz by default) and is shared between the "All Slots" view and the
per-slot tabs. It can be exported as CSV.
"""

import csv
import time
from datetime import datetime
from typing import Optional, Dict, List

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QComboBox,
    QLabel,
    QCheckBox,
    QPushButton,
    QFileDialog,
    QMessageBox,
)
from PySide6.QtCore import Qt

import numpy as np
import pyqtgraph as pg

from mc3000_protocol import SlotData

# Configure pyqtgraph
pg.setConfigOptions(antialias=True, background='w', foreground='k')

# Colors for each slot
SLOT_COLORS = [
    (31, 119, 180),   # Blue
    (255, 127, 14),   # Orange
    (44, 160, 44),    # Green
    (214, 39, 40),    # Red
]

# Statuses that mean "a program is running" (charging, discharging, resting)
ACTIVE_STATUSES = (1, 2, 3)
STATUS_FINISHED = 4

# 48 hours at one sample per second
DEFAULT_MAX_POINTS = 48 * 3600

# key, label, unit, color, default visible in slot view
METRICS = [
    ('voltage', 'Voltage', 'V', (31, 119, 180), True),
    ('current', 'Current', 'A', (255, 127, 14), True),
    ('capacity', 'Capacity', 'mAh', (44, 160, 44), True),
    ('energy', 'Energy', 'Wh', (23, 190, 207), False),
    ('power', 'Power', 'W', (140, 86, 75), False),
    ('temperature', 'Batt Temp', '°C', (214, 39, 40), False),
    ('internal_temp', 'Int Temp', '°C', (148, 103, 189), False),
    ('resistance', 'Resistance', 'mΩ', (127, 127, 127), False),
]
METRIC_KEYS = [m[0] for m in METRICS]

CSV_COLUMNS = [
    ('slot', 'slot'),
    ('timestamp', 'timestamp'),
    ('elapsed_s', 'time'),
    ('work_time_s', 'work_time'),
    ('status', 'status'),
    ('voltage_v', 'voltage'),
    ('current_a', 'current'),
    ('capacity_mah', 'capacity'),
    ('energy_wh', 'energy'),
    ('power_w', 'power'),
    ('battery_temp_c', 'temperature'),
    ('charger_temp_c', 'internal_temp'),
    ('resistance_mohm', 'resistance'),
    ('avg_voltage_v', 'avg_voltage'),
]


class TimeAxisItem(pg.AxisItem):
    """X axis showing elapsed seconds as H:MM:SS."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Values are always seconds - no "(x0.001)" / "ks" scaling
        self.enableAutoSIPrefix(False)

    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            v = int(round(v))
            sign = '-' if v < 0 else ''
            v = abs(v)
            h, rem = divmod(v, 3600)
            m, s = divmod(rem, 60)
            out.append(f"{sign}{h}:{m:02d}:{s:02d}")
        return out


class SlotDataHistory:
    """Stores the history of one slot in growable numpy arrays."""

    FIELDS = ['time', 'wall', 'work_time', 'status'] + METRIC_KEYS + ['avg_voltage']

    def __init__(self, max_points: int = DEFAULT_MAX_POINTS):
        self.max_points = max_points
        self._capacity = 0
        self._n = 0
        self._data: Dict[str, np.ndarray] = {}
        self.start_time: Optional[float] = None
        self._last_status: Optional[int] = None
        self._alloc(1024)

    def _alloc(self, capacity: int) -> None:
        new = {k: np.full(capacity, np.nan) for k in self.FIELDS}
        for k, arr in self._data.items():
            new[k][:self._n] = arr[:self._n]
        self._data = new
        self._capacity = capacity

    def _append(self, values: Dict[str, float]) -> None:
        if self._n >= self.max_points:
            # Drop the oldest 10 % to keep memory bounded
            drop = max(1, self.max_points // 10)
            for arr in self._data.values():
                arr[:self._n - drop] = arr[drop:self._n]
            self._n -= drop
        if self._n >= self._capacity:
            self._alloc(min(self._capacity * 2, self.max_points))
        for k in self.FIELDS:
            self._data[k][self._n] = values.get(k, np.nan)
        self._n += 1

    def add_data(self, data: SlotData) -> bool:
        """
        Add a data point.

        Rules:
        - nothing is recorded in standby / empty slot
        - a new start (inactive -> active) begins a fresh history
        - while finished, only the first finished sample is kept

        Returns:
            True if a point was added (or the history was reset)
        """
        status = data.status
        prev = self._last_status
        self._last_status = status

        active = status in ACTIVE_STATUSES
        if active and prev is not None and prev not in ACTIVE_STATUSES and self._n > 0:
            self.clear()
            self._last_status = status

        if status == 0:
            return False
        if status == STATUS_FINISHED and prev == STATUS_FINISHED and self._n > 0:
            return False
        if not active and status != STATUS_FINISHED and not data.is_error:
            return False

        now = time.time()
        if self.start_time is None:
            self.start_time = now

        def opt(v, scale=1.0):
            return np.nan if v is None else v / scale

        self._append({
            'time': now - self.start_time,
            'wall': now,
            'work_time': data.work_time_seconds,
            'status': status,
            'voltage': data.voltage_v,
            'current': data.current_a,
            'capacity': data.capacity_mah,
            'energy': opt(data.energy_mwh, 1000.0),
            'power': data.power_w,
            'temperature': data.temperature_c,
            'internal_temp': data.internal_temp_c,
            'resistance': np.nan if not data.internal_resistance_mohm
            else data.internal_resistance_mohm,
            'avg_voltage': opt(data.average_voltage_mv, 1000.0),
        })
        return True

    def clear(self) -> None:
        """Clear all stored data."""
        self._n = 0
        self._data = {}
        self._alloc(1024)
        self.start_time = None
        self._last_status = None

    def get_arrays(self) -> Dict[str, np.ndarray]:
        """Get data as numpy arrays (views, do not modify)."""
        return {k: arr[:self._n] for k, arr in self._data.items()}

    def __len__(self) -> int:
        return self._n


def _make_curve(plot_widget: pg.PlotWidget, name: str, color) -> pg.PlotDataItem:
    curve = plot_widget.plot([], [], name=name, pen=pg.mkPen(color=color, width=2))
    # Long runs (many hours) stay fast with peak downsampling
    curve.setDownsampling(auto=True, method='peak')
    curve.setClipToView(True)
    return curve


def _new_plot_widget() -> pg.PlotWidget:
    pw = pg.PlotWidget(axisItems={'bottom': TimeAxisItem(orientation='bottom')})
    pw.showGrid(x=True, y=True, alpha=0.3)
    pw.setLabel('bottom', 'Time (h:mm:ss)')
    # Units are in the axis label already - no "(x0.001)" scaling
    pw.getAxis('left').enableAutoSIPrefix(False)
    pw.addLegend(offset=(10, 10))
    return pw


class SlotGraphWidget(QWidget):
    """Graph widget for a single slot with selectable metrics."""

    def __init__(self, slot_number: int, history: SlotDataHistory,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.slot_number = slot_number
        self.history = history
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("Show:"))
        self.metric_checkboxes: Dict[str, QCheckBox] = {}
        for key, name, unit, color, default in METRICS:
            cb = QCheckBox(name)
            cb.setChecked(default)
            cb.setStyleSheet(f"color: rgb({color[0]}, {color[1]}, {color[2]})")
            cb.stateChanged.connect(self.refresh)
            controls_layout.addWidget(cb)
            self.metric_checkboxes[key] = cb
        controls_layout.addStretch()

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setFixedWidth(60)
        controls_layout.addWidget(self.clear_btn)
        layout.addLayout(controls_layout)

        self.plot_widget = _new_plot_widget()
        self.curves: Dict[str, pg.PlotDataItem] = {}
        for key, name, unit, color, default in METRICS:
            curve = _make_curve(self.plot_widget, f'{name} ({unit})', color)
            curve.hide()
            self.curves[key] = curve
        layout.addWidget(self.plot_widget)

    def refresh(self) -> None:
        """Redraw from the shared history."""
        arrays = self.history.get_arrays()
        t = arrays['time']
        for key in METRIC_KEYS:
            curve = self.curves[key]
            if self.metric_checkboxes[key].isChecked() and len(t) > 0:
                y = arrays[key]
                if key == 'current':
                    y = np.abs(y)
                curve.setData(t, y, connect='finite')
                curve.show()
            else:
                curve.setData([], [])
                curve.hide()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()


class MultiSlotGraphWidget(QWidget):
    """Combined graph showing one metric for all slots."""

    def __init__(self, histories: List[SlotDataHistory], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.histories = histories
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("Show:"))
        self.metric_combo = QComboBox()
        self.metric_combo.addItems([f"{name} ({unit})" for _, name, unit, _, _ in METRICS])
        self.metric_combo.currentIndexChanged.connect(self.refresh)
        controls_layout.addWidget(self.metric_combo)
        controls_layout.addSpacing(20)

        self.slot_checkboxes: List[QCheckBox] = []
        for i in range(4):
            cb = QCheckBox(f"Slot {i + 1}")
            cb.setChecked(True)
            cb.stateChanged.connect(self.refresh)
            color = SLOT_COLORS[i]
            cb.setStyleSheet(f"color: rgb({color[0]}, {color[1]}, {color[2]})")
            controls_layout.addWidget(cb)
            self.slot_checkboxes.append(cb)
        controls_layout.addStretch()

        self.clear_btn = QPushButton("Clear All")
        controls_layout.addWidget(self.clear_btn)
        layout.addLayout(controls_layout)

        self.plot_widget = _new_plot_widget()
        self.curves: List[pg.PlotDataItem] = [
            _make_curve(self.plot_widget, f'Slot {i + 1}', SLOT_COLORS[i]) for i in range(4)
        ]
        layout.addWidget(self.plot_widget)

    def refresh(self) -> None:
        idx = self.metric_combo.currentIndex()
        key, name, unit, _, _ = METRICS[idx]
        self.plot_widget.setLabel('left', f"{name} ({unit})")
        for history, curve, cb in zip(self.histories, self.curves, self.slot_checkboxes):
            if cb.isChecked() and len(history) > 0:
                arrays = history.get_arrays()
                y = arrays[key]
                if key == 'current':
                    y = np.abs(y)
                curve.setData(arrays['time'], y, connect='finite')
                curve.show()
            else:
                curve.setData([], [])
                curve.hide()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()


class GraphTabWidget(QTabWidget):
    """Tabbed widget containing the combined view and one tab per slot."""

    def __init__(self, parent: Optional[QWidget] = None, max_points: int = DEFAULT_MAX_POINTS):
        super().__init__(parent)
        self.histories: List[SlotDataHistory] = [SlotDataHistory(max_points) for _ in range(4)]

        self.multi_graph = MultiSlotGraphWidget(self.histories)
        self.multi_graph.clear_btn.clicked.connect(self.clear_all_data)
        self.addTab(self.multi_graph, "All Slots")

        self.slot_graphs: List[SlotGraphWidget] = []
        for i in range(4):
            graph = SlotGraphWidget(i, self.histories[i])
            graph.clear_btn.clicked.connect(lambda _=False, s=i: self.clear_slot(s))
            self.slot_graphs.append(graph)
            self.addTab(graph, f"Slot {i + 1}")

        self.export_btn = QPushButton("Export CSV...")
        self.export_btn.clicked.connect(self.export_csv_dialog)
        self.setCornerWidget(self.export_btn, Qt.TopRightCorner)

    def _refresh_visible(self, slot: Optional[int] = None) -> None:
        current = self.currentWidget()
        if current is self.multi_graph:
            self.multi_graph.refresh()
        elif slot is None or current is self.slot_graphs[slot]:
            if hasattr(current, 'refresh'):
                current.refresh()

    def update_data(self, slot: int, data: Optional[SlotData]) -> None:
        """Record a sample and redraw the visible graph if needed."""
        if data is None or not 0 <= slot < 4:
            return
        if self.histories[slot].add_data(data) and self.isVisible():
            self._refresh_visible(slot)

    def clear_slot(self, slot: int) -> None:
        self.histories[slot].clear()
        self._refresh_visible()

    def clear_all_data(self) -> None:
        for h in self.histories:
            h.clear()
        self._refresh_visible()

    # --- CSV export -------------------------------------------------

    def export_csv(self, path: str) -> int:
        """Write all slot histories to one CSV file. Returns row count."""
        rows = 0
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([c for c, _ in CSV_COLUMNS])
            for slot, history in enumerate(self.histories):
                arrays = history.get_arrays()
                for i in range(len(history)):
                    row = []
                    for col, key in CSV_COLUMNS:
                        if key == 'slot':
                            row.append(slot + 1)
                        elif key == 'timestamp':
                            row.append(datetime.fromtimestamp(arrays['wall'][i])
                                       .isoformat(timespec='seconds'))
                        else:
                            v = arrays[key][i]
                            if np.isnan(v):
                                row.append('')
                            elif key in ('time', 'work_time', 'status', 'capacity', 'resistance'):
                                row.append(int(v))
                            else:
                                row.append(f"{v:.4f}")
                    writer.writerow(row)
                    rows += 1
        return rows

    def export_csv_dialog(self) -> None:
        if not any(len(h) for h in self.histories):
            QMessageBox.information(self, "Export CSV", "No data recorded yet.")
            return
        default = f"mc3000_{datetime.now():%Y-%m-%d_%H%M}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", default, "CSV files (*.csv)")
        if not path:
            return
        try:
            rows = self.export_csv(path)
        except OSError as e:
            QMessageBox.critical(self, "Export CSV", f"Could not write file:\n{e}")
            return
        QMessageBox.information(self, "Export CSV", f"{rows} rows written to\n{path}")
