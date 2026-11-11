"""
MC3000 GUI Components

PySide6-based graphical user interface for SKYRC MC3000 battery charger.
Provides real-time monitoring of all 4 charging slots.
Supports both USB and BLE (Bluetooth Low Energy) connections.
"""

try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("skyrc-mc3000-gui")
except Exception:  # running from a source checkout
    __version__ = "1.8.13"

import sys
import time
import logging
import asyncio
from typing import Optional, List, Union

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QGroupBox,
    QMessageBox,
    QProgressBar,
    QStatusBar,
    QSplitter,
    QCheckBox,
    QDialog,
    QFormLayout,
    QTabWidget,
    QListWidget,
    QListWidgetItem,
    QDialogButtonBox,
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, Slot
from PySide6.QtGui import QFont, QPalette, QColor

from mc3000_usb import MC3000USB, MC3000USBError, MC3000PermissionError
from mc3000_protocol import SlotData, STATUS_CODES
from mc3000_start import plan_start, ACTIVE, EMPTY_SLOT_MV

# Try to import BLE module (optional dependency)
try:
    from mc3000_ble import MC3000BLE, MC3000BLEError, BLEDeviceInfo, BLEConnectionManager
    BLE_AVAILABLE = MC3000BLE.check_ble_available()
except ImportError:
    MC3000BLE = None
    MC3000BLEError = Exception
    BLEDeviceInfo = None
    BLEConnectionManager = None
    BLE_AVAILABLE = False

# Try to import graph module (optional dependency)
try:
    from mc3000_graphs import GraphTabWidget
    GRAPHS_AVAILABLE = True
except ImportError:
    GRAPHS_AVAILABLE = False
    GraphTabWidget = None

# Try to import config module
try:
    from mc3000_config import SlotConfigDialog
    CONFIG_AVAILABLE = True
except ImportError:
    CONFIG_AVAILABLE = False
    SlotConfigDialog = None

logger = logging.getLogger(__name__)

# Color scheme for status
STATUS_COLORS = {
    0: "#808080",  # Standby - Gray
    1: "#00AA00",  # Charging - Green
    2: "#FF6600",  # Discharging - Orange
    3: "#0066FF",  # Resting - Blue
    4: "#00CCCC",  # Finished - Cyan
}
ERROR_COLOR = "#FF0000"  # Red for errors

# Transport type enum
TRANSPORT_USB = "USB"
TRANSPORT_BLE = "BLE"


class BLEScanWorker(QThread):
    """Worker thread for BLE device scanning."""

    devices_found = Signal(list)  # List of BLEDeviceInfo
    scan_error = Signal(str)
    scan_finished = Signal()

    def __init__(self, timeout: float = 5.0, parent=None):
        super().__init__(parent)
        self.timeout = timeout

    def run(self):
        """Run BLE scan in background thread."""
        if not BLE_AVAILABLE:
            self.scan_error.emit("BLE library not available")
            self.scan_finished.emit()
            return

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                devices = loop.run_until_complete(MC3000BLE.scan_devices(self.timeout))
                self.devices_found.emit(devices)
            finally:
                loop.close()
        except Exception as e:
            self.scan_error.emit(str(e))
        finally:
            self.scan_finished.emit()


class BLEPollWorker(QThread):
    """Worker thread for BLE connection and polling operations.

    Uses BLEConnectionManager to handle both connection and polling
    in the same event loop, avoiding cross-loop issues with bleak.
    """

    slot_data_received = Signal(int, object)  # slot_number, SlotData
    connection_established = Signal()  # emitted when connected
    connection_lost = Signal(str)  # error message
    poll_error = Signal(str)

    def __init__(self, device_address: str, parent=None):
        super().__init__(parent)
        self._device_address = device_address
        self._manager: Optional["BLEConnectionManager"] = None

    def stop(self):
        """Signal the worker to stop."""
        if self._manager:
            self._manager.stop()

    def _on_slot_data(self, slot: int, data: SlotData):
        """Callback for slot data received."""
        self.slot_data_received.emit(slot, data)

    def _on_error(self, error: str):
        """Callback for errors."""
        self.poll_error.emit(error)

    def _on_connected(self, connected: bool):
        """Callback for connection state changes."""
        if connected:
            self.connection_established.emit()
        else:
            self.connection_lost.emit("BLE connection closed")

    def run(self):
        """Run connection and polling in background thread."""
        if not BLE_AVAILABLE or BLEConnectionManager is None:
            self.connection_lost.emit("BLE not available")
            return

        self._manager = BLEConnectionManager()
        self._manager.set_callbacks(
            slot_data=self._on_slot_data,
            error=self._on_error,
            connected=self._on_connected,
        )

        try:
            # This blocks until stop() is called or connection is lost
            self._manager.start(self._device_address)
        except Exception as e:
            self.connection_lost.emit(str(e))


class USBPollWorker(QThread):
    """Worker thread polling the charger via USB.

    Keeps the GUI responsive: blocking HID reads never run on the Qt
    main thread. All USB access is serialised by the lock inside MC3000USB,
    so dialogs may still talk to the device while the worker is running.
    """

    slot_data_received = Signal(int, object)  # slot_number, SlotData
    no_response = Signal(int)                 # consecutive failed cycles
    response_restored = Signal()
    poll_error = Signal(str)

    # After this many cycles without any answer we assume the charger is
    # busy serving the SkyRC app via Bluetooth.
    NO_RESPONSE_CYCLES = 2

    def __init__(self, usb: MC3000USB, interval_s: float = 1.0, parent=None):
        super().__init__(parent)
        self._usb = usb
        self._interval = interval_s
        self._running = True
        self._failed_cycles = 0

    def stop(self):
        self._running = False

    def run(self):
        while self._running and self._usb.is_connected():
            cycle_start = time.monotonic()
            got_any = False
            for slot in range(4):
                if not self._running:
                    return
                try:
                    data = self._usb.get_slot_data(slot)
                except MC3000USBError as e:
                    self.poll_error.emit(str(e))
                    data = None
                except Exception as e:  # never let the thread die silently
                    self.poll_error.emit(f"Unexpected error: {e}")
                    data = None
                if data is not None:
                    got_any = True
                    self.slot_data_received.emit(slot, data)

            if got_any:
                if self._failed_cycles >= self.NO_RESPONSE_CYCLES:
                    self.response_restored.emit()
                self._failed_cycles = 0
            else:
                self._failed_cycles += 1
                if self._failed_cycles >= self.NO_RESPONSE_CYCLES:
                    self.no_response.emit(self._failed_cycles)

            # Sleep in small steps so stop() takes effect quickly
            while self._running:
                remaining = self._interval - (time.monotonic() - cycle_start)
                if remaining <= 0:
                    break
                time.sleep(min(remaining, 0.1))


class DeviceSelectionDialog(QDialog):
    """Dialog for selecting USB or BLE device connection."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_device = None
        self.selected_transport = None
        self._scan_worker = None
        self._setup_ui()
        self._refresh_usb_devices()

    def _setup_ui(self):
        self.setWindowTitle("Connect to MC3000")
        self.setMinimumWidth(450)
        self.setMinimumHeight(350)

        layout = QVBoxLayout(self)

        # Tab widget for USB/BLE selection
        self.tab_widget = QTabWidget()

        # USB Tab
        usb_widget = QWidget()
        usb_layout = QVBoxLayout(usb_widget)

        usb_label = QLabel("Available USB Devices:")
        usb_layout.addWidget(usb_label)

        self.usb_list = QListWidget()
        self.usb_list.itemDoubleClicked.connect(self._on_usb_double_click)
        usb_layout.addWidget(self.usb_list)

        usb_btn_layout = QHBoxLayout()
        self.usb_refresh_btn = QPushButton("Refresh")
        self.usb_refresh_btn.clicked.connect(self._refresh_usb_devices)
        usb_btn_layout.addWidget(self.usb_refresh_btn)
        usb_btn_layout.addStretch()
        usb_layout.addLayout(usb_btn_layout)

        self.tab_widget.addTab(usb_widget, "USB")

        # BLE Tab
        ble_widget = QWidget()
        ble_layout = QVBoxLayout(ble_widget)

        if BLE_AVAILABLE:
            ble_label = QLabel("Scan for Bluetooth devices:")
            ble_layout.addWidget(ble_label)

            self.ble_list = QListWidget()
            self.ble_list.itemDoubleClicked.connect(self._on_ble_double_click)
            ble_layout.addWidget(self.ble_list)

            ble_btn_layout = QHBoxLayout()
            self.ble_scan_btn = QPushButton("Scan")
            self.ble_scan_btn.clicked.connect(self._start_ble_scan)
            ble_btn_layout.addWidget(self.ble_scan_btn)

            self.ble_status_label = QLabel("")
            ble_btn_layout.addWidget(self.ble_status_label)
            ble_btn_layout.addStretch()
            ble_layout.addLayout(ble_btn_layout)
        else:
            no_ble_label = QLabel(
                "Bluetooth support not available.\n\n"
                "Install the 'bleak' library:\n"
                "pip install bleak"
            )
            no_ble_label.setAlignment(Qt.AlignCenter)
            no_ble_label.setStyleSheet("color: gray;")
            ble_layout.addWidget(no_ble_label)

        self.tab_widget.addTab(ble_widget, "Bluetooth")

        layout.addWidget(self.tab_widget)

        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        self.ok_button = button_box.button(QDialogButtonBox.Ok)
        self.ok_button.setText("Connect")
        self.ok_button.setEnabled(False)
        layout.addWidget(button_box)

        # Connect selection changes to enable/disable OK button
        self.usb_list.itemSelectionChanged.connect(self._update_ok_button)
        if BLE_AVAILABLE:
            self.ble_list.itemSelectionChanged.connect(self._update_ok_button)

    def _refresh_usb_devices(self):
        """Refresh the list of USB devices."""
        self.usb_list.clear()
        devices = MC3000USB.enumerate_devices()
        if devices:
            for dev in devices:
                item = QListWidgetItem(
                    f"{dev.get('product', 'MC3000')} - {dev.get('manufacturer', 'SKYRC')}"
                )
                item.setData(Qt.UserRole, dev)
                self.usb_list.addItem(item)
        else:
            item = QListWidgetItem("No USB devices found")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            item.setForeground(QColor("gray"))
            self.usb_list.addItem(item)
        self._update_ok_button()

    def _start_ble_scan(self):
        """Start BLE device scan."""
        if not BLE_AVAILABLE:
            return

        self.ble_list.clear()
        self.ble_scan_btn.setEnabled(False)
        self.ble_status_label.setText("Scanning...")

        self._scan_worker = BLEScanWorker(timeout=5.0)
        self._scan_worker.devices_found.connect(self._on_ble_devices_found)
        self._scan_worker.scan_error.connect(self._on_ble_scan_error)
        self._scan_worker.scan_finished.connect(self._on_ble_scan_finished)
        self._scan_worker.start()

    @Slot(list)
    def _on_ble_devices_found(self, devices: List):
        """Handle discovered BLE devices."""
        for dev in devices:
            item = QListWidgetItem(f"{dev.name} ({dev.address}) - RSSI: {dev.rssi} dBm")
            item.setData(Qt.UserRole, dev)
            self.ble_list.addItem(item)

    @Slot(str)
    def _on_ble_scan_error(self, error: str):
        """Handle BLE scan error."""
        self.ble_status_label.setText(f"Error: {error}")

    @Slot()
    def _on_ble_scan_finished(self):
        """Handle BLE scan completion."""
        self.ble_scan_btn.setEnabled(True)
        if self.ble_list.count() == 0:
            self.ble_status_label.setText("No devices found")
            item = QListWidgetItem("No BLE devices found - try scanning again")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            item.setForeground(QColor("gray"))
            self.ble_list.addItem(item)
        else:
            self.ble_status_label.setText(f"Found {self.ble_list.count()} device(s)")
        self._update_ok_button()

    def _update_ok_button(self):
        """Update OK button state based on selection."""
        current_tab = self.tab_widget.currentIndex()
        if current_tab == 0:  # USB tab
            selected = self.usb_list.currentItem()
            enabled = selected is not None and selected.data(Qt.UserRole) is not None
        else:  # BLE tab
            if BLE_AVAILABLE:
                selected = self.ble_list.currentItem()
                enabled = selected is not None and selected.data(Qt.UserRole) is not None
            else:
                enabled = False
        self.ok_button.setEnabled(enabled)

    def _on_usb_double_click(self, item: QListWidgetItem):
        """Handle double-click on USB device."""
        if item.data(Qt.UserRole) is not None:
            self._on_accept()

    def _on_ble_double_click(self, item: QListWidgetItem):
        """Handle double-click on BLE device."""
        if item.data(Qt.UserRole) is not None:
            self._on_accept()

    def _on_accept(self):
        """Handle dialog accept."""
        current_tab = self.tab_widget.currentIndex()
        if current_tab == 0:  # USB tab
            selected = self.usb_list.currentItem()
            if selected and selected.data(Qt.UserRole):
                self.selected_device = selected.data(Qt.UserRole)
                self.selected_transport = TRANSPORT_USB
                self.accept()
        else:  # BLE tab
            if BLE_AVAILABLE:
                selected = self.ble_list.currentItem()
                if selected and selected.data(Qt.UserRole):
                    self.selected_device = selected.data(Qt.UserRole)
                    self.selected_transport = TRANSPORT_BLE
                    self.accept()

    def closeEvent(self, event):
        """Handle dialog close."""
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.wait()
        event.accept()


class SlotWidget(QGroupBox):
    """Widget displaying data for a single charger slot."""

    def __init__(self, slot_number: int, parent: Optional[QWidget] = None):
        super().__init__(f"Slot {slot_number + 1}", parent)
        self.slot_number = slot_number
        self._setup_ui()
        self.clear_data()

    def _setup_ui(self):
        """Set up the widget UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # Status indicator
        self.status_frame = QFrame()
        self.status_frame.setFixedHeight(6)
        self.status_frame.setStyleSheet(f"background-color: {STATUS_COLORS[0]};")
        layout.addWidget(self.status_frame)

        # Battery type and mode
        info_layout = QHBoxLayout()
        self.battery_label = QLabel("---")
        self.battery_label.setAlignment(Qt.AlignLeft)
        self.mode_label = QLabel("---")
        self.mode_label.setAlignment(Qt.AlignRight)
        info_layout.addWidget(self.battery_label)
        info_layout.addWidget(self.mode_label)
        layout.addLayout(info_layout)

        # Status label
        self.status_label = QLabel("Standby")
        self.status_label.setAlignment(Qt.AlignCenter)
        status_font = QFont()
        status_font.setBold(True)
        status_font.setPointSize(11)
        self.status_label.setFont(status_font)
        layout.addWidget(self.status_label)

        # Hint label (shown when finished)
        self.hint_label = QLabel("Press slot button to restart")
        self.hint_label.setAlignment(Qt.AlignCenter)
        hint_font = QFont()
        hint_font.setPointSize(8)
        self.hint_label.setFont(hint_font)
        self.hint_label.setStyleSheet("color: gray;")
        self.hint_label.hide()
        layout.addWidget(self.hint_label)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        # Measurements grid
        measurements_layout = QGridLayout()
        measurements_layout.setSpacing(2)

        # Create measurement labels
        self.voltage_label = self._create_value_label()
        self.current_label = self._create_value_label()
        self.capacity_label = self._create_value_label()
        self.temperature_label = self._create_value_label()
        self.power_label = self._create_value_label()
        self.time_label = self._create_value_label()
        self.resistance_label = self._create_value_label()
        self.energy_label = self._create_value_label()
        self.avg_voltage_label = self._create_value_label()

        row = 0
        measurements_layout.addWidget(QLabel("Voltage:"), row, 0)
        measurements_layout.addWidget(self.voltage_label, row, 1)

        row += 1
        measurements_layout.addWidget(QLabel("Current:"), row, 0)
        measurements_layout.addWidget(self.current_label, row, 1)

        row += 1
        measurements_layout.addWidget(QLabel("Capacity:"), row, 0)
        measurements_layout.addWidget(self.capacity_label, row, 1)

        row += 1
        measurements_layout.addWidget(QLabel("Temp:"), row, 0)
        measurements_layout.addWidget(self.temperature_label, row, 1)

        row += 1
        measurements_layout.addWidget(QLabel("Power:"), row, 0)
        measurements_layout.addWidget(self.power_label, row, 1)

        row += 1
        measurements_layout.addWidget(QLabel("Energy:"), row, 0)
        measurements_layout.addWidget(self.energy_label, row, 1)

        row += 1
        measurements_layout.addWidget(QLabel("Avg. Volt:"), row, 0)
        measurements_layout.addWidget(self.avg_voltage_label, row, 1)

        row += 1
        measurements_layout.addWidget(QLabel("Resistance:"), row, 0)
        measurements_layout.addWidget(self.resistance_label, row, 1)

        row += 1
        measurements_layout.addWidget(QLabel("Time:"), row, 0)
        measurements_layout.addWidget(self.time_label, row, 1)

        layout.addLayout(measurements_layout)

        layout.addStretch()

        # Set minimum size
        self.setMinimumWidth(180)
        self.setMinimumHeight(330)

    def _create_value_label(self) -> QLabel:
        """Create a styled value label."""
        label = QLabel("---")
        label.setAlignment(Qt.AlignRight)
        font = QFont("Monospace")
        font.setStyleHint(QFont.Monospace)
        label.setFont(font)
        return label

    def update_data(self, data: Optional[SlotData]):
        """Update the widget with new slot data."""
        if data is None:
            self.clear_data()
            return

        # Update battery type and mode
        self.battery_label.setText(data.battery_type_name)
        self.mode_label.setText(data.operation_mode_name)

        # Update status
        self.status_label.setText(data.status_name)

        # Show hint when finished
        if data.status == 4:  # Finished
            self.hint_label.show()
        else:
            self.hint_label.hide()

        # Update status color
        if data.is_error:
            color = ERROR_COLOR
        else:
            color = STATUS_COLORS.get(data.status, STATUS_COLORS[0])
        self.status_frame.setStyleSheet(f"background-color: {color};")
        self.status_label.setStyleSheet(f"color: {color};")

        # Update measurements
        self.voltage_label.setText(f"{data.voltage_v:.3f} V")
        self.current_label.setText(f"{data.current_a:+.3f} A")
        self.capacity_label.setText(f"{data.capacity_mah} mAh")
        self.temperature_label.setText(f"{data.temperature_c:.1f} \u00b0C")
        self.power_label.setText(f"{data.power_w:.2f} W")
        self.time_label.setText(data.work_time_formatted)

        if data.energy_mwh is not None:
            self.energy_label.setText(f"{data.energy_mwh / 1000:.3f} Wh")
        else:
            self.energy_label.setText("--- Wh")
        if data.average_voltage_mv:
            self.avg_voltage_label.setText(f"{data.average_voltage_mv / 1000:.3f} V")
        else:
            self.avg_voltage_label.setText("--- V")
        if data.internal_resistance_mohm:
            self.resistance_label.setText(f"{data.internal_resistance_mohm} m\u03a9")
        else:
            self.resistance_label.setText("--- m\u03a9")

    def set_stale(self, stale: bool):
        """Grey out values when the charger stopped answering."""
        self.setEnabled(not stale)

    def clear_data(self):
        """Clear all displayed data."""
        self.battery_label.setText("---")
        self.mode_label.setText("---")
        self.status_label.setText("Standby")
        self.status_label.setStyleSheet(f"color: {STATUS_COLORS[0]};")
        self.status_frame.setStyleSheet(f"background-color: {STATUS_COLORS[0]};")
        self.hint_label.hide()

        self.voltage_label.setText("--- V")
        self.current_label.setText("--- A")
        self.capacity_label.setText("--- mAh")
        self.temperature_label.setText("--- \u00b0C")
        self.power_label.setText("--- W")
        self.time_label.setText("--:--:--")
        self.energy_label.setText("--- Wh")
        self.avg_voltage_label.setText("--- V")
        self.resistance_label.setText("--- m\u03a9")
        self.setEnabled(True)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        # Transport layer - USB connection object (BLE is managed by worker)
        self.mc3000: Optional[MC3000USB] = None
        self.transport_type: Optional[str] = None

        # USB-specific
        self.mc3000_usb = MC3000USB()

        # BLE-specific (worker manages connection internally)
        self.ble_poll_worker: Optional[BLEPollWorker] = None
        self._ble_device_name: str = ""

        # USB polling runs in a worker thread (like BLE)
        self.usb_poll_worker: Optional[USBPollWorker] = None
        self._usb_slot_cache: List[Optional[SlotData]] = [None] * 4

        self._setup_ui()
        # Show connection dialog on startup
        self._show_connection_dialog()

    def _setup_ui(self):
        """Set up the main window UI."""
        self.setWindowTitle(f"SKYRC MC3000 Battery Charger v{__version__}")
        self.setMinimumSize(900, 800)
        self.resize(1100, 950)  # Default size

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Header with controls
        header_layout = QHBoxLayout()

        # Connect/Disconnect button
        self.connect_btn = QPushButton("Connect...")
        self.connect_btn.clicked.connect(self._on_connect_button_clicked)
        self.connect_btn.setFixedWidth(100)
        header_layout.addWidget(self.connect_btn)

        # Configure button
        if CONFIG_AVAILABLE:
            self.config_btn = QPushButton("Configure...")
            self.config_btn.clicked.connect(self._on_config_clicked)
            self.config_btn.setEnabled(False)
            self.config_btn.setFixedWidth(100)
            header_layout.addWidget(self.config_btn)

        self.system_settings_btn = QPushButton("System Settings...")
        self.system_settings_btn.clicked.connect(self._on_system_settings_clicked)
        self.system_settings_btn.setEnabled(False)
        self.system_settings_btn.setFixedWidth(140)
        header_layout.addWidget(self.system_settings_btn)

        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._on_start_clicked)
        self.start_btn.setEnabled(False)
        self.start_btn.setFixedWidth(80)
        header_layout.addWidget(self.start_btn)

        header_layout.addStretch()

        # Show/hide graphs checkbox
        if GRAPHS_AVAILABLE:
            self.show_graphs_cb = QCheckBox("Show Graphs")
            self.show_graphs_cb.setChecked(True)
            self.show_graphs_cb.stateChanged.connect(self._toggle_graphs)
            header_layout.addWidget(self.show_graphs_cb)
            header_layout.addSpacing(20)

        # Connection status indicator
        self.connection_indicator = QLabel("\u25cf")
        self.connection_indicator.setStyleSheet("color: #FF0000; font-size: 16px;")
        header_layout.addWidget(self.connection_indicator)

        self.transport_label = QLabel("")
        self.transport_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(self.transport_label)

        self.connection_status = QLabel("Disconnected")
        header_layout.addWidget(self.connection_status)

        main_layout.addLayout(header_layout)

        # System temperature
        self.firmware_label = QLabel("")
        main_layout.addWidget(self.firmware_label)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(line)

        # Create splitter for slots and graphs
        self.splitter = QSplitter(Qt.Vertical)

        # Slots container
        slots_widget = QWidget()
        slots_layout = QHBoxLayout(slots_widget)
        slots_layout.setSpacing(10)
        slots_layout.setContentsMargins(0, 0, 0, 0)

        self.slot_widgets: List[SlotWidget] = []
        for i in range(4):
            slot_widget = SlotWidget(i)
            self.slot_widgets.append(slot_widget)
            slots_layout.addWidget(slot_widget)

        self.splitter.addWidget(slots_widget)

        # Graph widget (if available)
        self.graph_widget = None
        if GRAPHS_AVAILABLE:
            self.graph_widget = GraphTabWidget()
            self.graph_widget.setMinimumHeight(200)
            self.splitter.addWidget(self.graph_widget)
            # Set initial splitter sizes (slots:graphs = 2:3)
            self.splitter.setStretchFactor(0, 2)
            self.splitter.setStretchFactor(1, 3)

        main_layout.addWidget(self.splitter, 1)  # stretch factor 1 to fill space

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _toggle_graphs(self, state):
        """Show or hide the graphs panel."""
        if self.graph_widget:
            show = self.show_graphs_cb.isChecked()
            if show:
                self.graph_widget.setVisible(True)
                # Restore splitter sizes when showing
                if hasattr(self, '_saved_splitter_sizes') and self._saved_splitter_sizes:
                    self.splitter.setSizes(self._saved_splitter_sizes)
            else:
                # Save splitter sizes before hiding
                self._saved_splitter_sizes = self.splitter.sizes()
                self.graph_widget.setVisible(False)

    def _is_connected(self) -> bool:
        """Check if connected to any device."""
        if self.transport_type == TRANSPORT_BLE:
            # BLE connection is managed by the worker
            return self.ble_poll_worker is not None and self.ble_poll_worker.isRunning()
        elif self.mc3000 is not None:
            return self.mc3000.is_connected()
        return False

    def _on_config_clicked(self):
        """Open the slot configuration dialog."""
        if CONFIG_AVAILABLE and self._is_connected():
            # Config dialog only works with USB
            if self.transport_type == TRANSPORT_USB:
                dialog = SlotConfigDialog(self.mc3000, self)
                dialog.exec()
            else:
                QMessageBox.information(
                    self,
                    "Not Available",
                    "Slot configuration is only available via USB connection."
                )

    def _on_system_settings_clicked(self):
        """Open the system settings dialog."""
        if self._is_connected():
            if self.transport_type == TRANSPORT_USB:
                dialog = SystemSettingsDialog(self.mc3000, self)
                dialog.exec()
            else:
                QMessageBox.information(
                    self,
                    "Not Available",
                    "System settings dialog is only available via USB connection."
                )

    def _on_start_clicked(self):
        """Show what a start would do, then start (resetting finished slots if needed)."""
        if not self._is_connected():
            QMessageBox.warning(self, "Not Connected", "Please connect to the charger first.")
            return

        if self.transport_type == TRANSPORT_BLE:
            QMessageBox.information(
                self,
                "Not Available",
                "Start command is not supported via BLE.\n"
                "Use the charger buttons to start processing."
            )
            return

        data = list(self._usb_slot_cache)
        settings = [None] * 4
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for i, d in enumerate(data):
                if d is not None and d.status not in ACTIVE and d.voltage_mv >= EMPTY_SLOT_MV:
                    try:
                        settings[i] = self.mc3000.get_slot_settings(i, tries=1)
                    except Exception:
                        settings[i] = None
        finally:
            QApplication.restoreOverrideCursor()

        plan = plan_start(data, settings)
        lines = [f"Slot {p.slot + 1}: {p.text}" for p in plan.slots]
        text = "\n".join(lines)

        if not plan.starting:
            QMessageBox.information(self, "Start Charger",
                                    f"No slot would start.\n\n{text}")
            return

        box = QMessageBox(self)
        box.setWindowTitle("Start Charger")
        box.setIcon(QMessageBox.Question)
        info = ("The charger has no per-slot start: every idle slot with a cell starts.\n"
                "Assign a do-nothing program (e.g. LiIon Charge, target 2.50 V) to slots "
                "that should stay idle.")
        if plan.needs_reset and plan.any_running:
            info += ("\n\nSome slots are finished and need a reset first, but other slots "
                     "are still running. A reset (stop) would abort the running slots.")
            box.setText(f"Start charging now?\n\n{text}")
            box.setInformativeText(info)
            restart_btn = box.addButton("Stop all && start", QMessageBox.DestructiveRole)
            start_btn = box.addButton("Start without reset", QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(start_btn)
        else:
            if plan.needs_reset:
                info += "\n\nFinished slots are reset automatically before starting."
            box.setText(f"Start charging now?\n\n{text}")
            box.setInformativeText(info)
            start_btn = box.addButton("Start", QMessageBox.AcceptRole)
            restart_btn = None
            box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(start_btn)
        box.exec()
        clicked = box.clickedButton()

        if clicked is restart_btn and restart_btn is not None:
            do_reset = True
        elif clicked is start_btn:
            do_reset = plan.needs_reset and not plan.any_running
        else:
            return

        ok = True
        if do_reset:
            ok = self.mc3000.stop_processing()
            time.sleep(0.5)
        ok = ok and self.mc3000.start_processing()
        if ok:
            self.status_bar.showMessage(
                "Reset + start command sent" if do_reset else "Start command sent")
        else:
            QMessageBox.warning(self, "Start Failed", "Failed to start charging.")

    def _on_connect_button_clicked(self):
        """Handle connect/disconnect button click."""
        if self._is_connected():
            self._disconnect()
        else:
            self._show_connection_dialog()

    def _show_connection_dialog(self):
        """Show device selection dialog."""
        dialog = DeviceSelectionDialog(self)
        if dialog.exec() == QDialog.Accepted:
            if dialog.selected_transport == TRANSPORT_USB:
                self._connect_usb(dialog.selected_device)
            elif dialog.selected_transport == TRANSPORT_BLE:
                self._connect_ble(dialog.selected_device)

    def _connect_usb(self, device_info: dict):
        """Connect via USB."""
        self.status_bar.showMessage("Connecting via USB...")

        try:
            device_path = device_info.get('path')
            self.mc3000_usb.connect(device_path)
            self.mc3000 = self.mc3000_usb
            self.transport_type = TRANSPORT_USB

            # Update UI for connected state
            self._update_connected_ui()

            if self.mc3000.firmware_version:
                self.status_bar.showMessage(
                    f"Connected via USB (firmware {self.mc3000.firmware_version}) - Monitoring active")
            else:
                self.status_bar.showMessage("Connected via USB - Monitoring active")

            # Start polling in background thread
            self._start_usb_worker()

        except MC3000PermissionError as e:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("USB Permission Error")
            msg.setText("Cannot access the MC3000 device due to insufficient permissions.")
            msg.setDetailedText(str(e))
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec()
            self.status_bar.showMessage("Permission denied - see instructions")
        except MC3000USBError as e:
            QMessageBox.critical(self, "USB Connection Error", str(e))
            self.status_bar.showMessage("USB connection failed")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Unexpected error: {e}")
            self.status_bar.showMessage("Connection failed")

    def _connect_ble(self, device_info: "BLEDeviceInfo"):
        """Connect via BLE."""
        if not BLE_AVAILABLE:
            QMessageBox.critical(self, "BLE Error", "BLE library not available")
            return

        self.status_bar.showMessage(f"Connecting via BLE to {device_info.name}...")
        self._ble_device_name = device_info.name

        # Set transport type before starting worker
        self.transport_type = TRANSPORT_BLE

        # Start BLE worker which handles both connection and polling
        # The worker runs connection and polling in its own event loop
        self.ble_poll_worker = BLEPollWorker(device_info.address)
        self.ble_poll_worker.slot_data_received.connect(self._on_ble_slot_data)
        self.ble_poll_worker.connection_established.connect(self._on_ble_connected)
        self.ble_poll_worker.connection_lost.connect(self._on_ble_connection_lost)
        self.ble_poll_worker.poll_error.connect(self._on_ble_poll_error)
        self.ble_poll_worker.start()

    @Slot()
    def _on_ble_connected(self):
        """Handle successful BLE connection."""
        self._update_connected_ui()
        device_name = getattr(self, '_ble_device_name', 'device')
        self.status_bar.showMessage(f"Connected via BLE to {device_name}")

    def _update_connected_ui(self):
        """Update UI elements for connected state."""
        self.connection_indicator.setStyleSheet("color: #00AA00; font-size: 16px;")
        self.connection_status.setText("Connected")
        self.transport_label.setText(f"[{self.transport_type}]")
        self.connect_btn.setText("Disconnect")

        if CONFIG_AVAILABLE and hasattr(self, 'config_btn'):
            # Config only works with USB
            self.config_btn.setEnabled(self.transport_type == TRANSPORT_USB)
        if hasattr(self, 'system_settings_btn'):
            # System settings only works with USB
            self.system_settings_btn.setEnabled(self.transport_type == TRANSPORT_USB)
        if hasattr(self, 'start_btn'):
            # Start button only works with USB
            self.start_btn.setEnabled(self.transport_type == TRANSPORT_USB)

        self.firmware_label.setText("")

    @Slot(int, object)
    def _on_ble_slot_data(self, slot: int, data: SlotData):
        """Handle slot data received from BLE worker."""
        if slot < len(self.slot_widgets):
            self.slot_widgets[slot].update_data(data)
            if self.graph_widget and data:
                self.graph_widget.update_data(slot, data)

            # Update internal temp display from first slot with data
            if slot == 0 and data:
                self.firmware_label.setText(
                    f"Charger Temp: {data.internal_temp_c:.1f} \u00b0C"
                )

    @Slot(str)
    def _on_ble_connection_lost(self, error: str):
        """Handle BLE connection loss."""
        logger.warning(f"BLE connection lost: {error}")
        self._disconnect()
        QMessageBox.warning(
            self,
            "Connection Lost",
            f"BLE connection was lost: {error}\n\nPlease reconnect."
        )

    @Slot(str)
    def _on_ble_poll_error(self, error: str):
        """Handle BLE polling error."""
        logger.warning(f"BLE poll error: {error}")
        self.status_bar.showMessage(f"BLE error: {error}")

    def _start_usb_worker(self):
        self._stop_usb_worker()
        self._usb_slot_cache = [None] * 4
        self.usb_poll_worker = USBPollWorker(self.mc3000, 1.0)
        self.usb_poll_worker.slot_data_received.connect(self._on_usb_slot_data)
        self.usb_poll_worker.no_response.connect(self._on_usb_no_response)
        self.usb_poll_worker.response_restored.connect(self._on_usb_response_restored)
        self.usb_poll_worker.poll_error.connect(self._on_usb_poll_error)
        self.usb_poll_worker.start()

    def _stop_usb_worker(self):
        if self.usb_poll_worker is not None:
            self.usb_poll_worker.stop()
            self.usb_poll_worker.wait(3000)
            self.usb_poll_worker = None

    @Slot(int, object)
    def _on_usb_slot_data(self, slot: int, data: SlotData):
        if self.transport_type != TRANSPORT_USB or slot >= len(self.slot_widgets):
            return
        self._usb_slot_cache[slot] = data
        self.slot_widgets[slot].set_stale(False)
        self.slot_widgets[slot].update_data(data)
        if self.graph_widget:
            self.graph_widget.update_data(slot, data)

        valid = [d for d in self._usb_slot_cache if d is not None]
        if valid:
            internal_temp_c = valid[0].internal_temp_c
            total_power_w = sum(abs(d.power_w) for d in valid if d.status in (1, 2))
            self.firmware_label.setText(
                f"Charger Temp: {internal_temp_c:.1f} \u00b0C    |    Total Power: {total_power_w:.2f} W"
            )

    @Slot(int)
    def _on_usb_no_response(self, cycles: int):
        # Keep the last values on screen, just mark them as stale
        for w in self.slot_widgets:
            w.set_stale(True)
        self.connection_indicator.setStyleSheet("color: #FFAA00; font-size: 16px;")
        self.status_bar.showMessage(
            "No response from charger - is the SkyRC app showing live data via "
            "Bluetooth? (The MC3000 stops answering USB while the app reads live data.)"
        )

    @Slot()
    def _on_usb_response_restored(self):
        self.connection_indicator.setStyleSheet("color: #00AA00; font-size: 16px;")
        self.status_bar.showMessage("Charger is answering again - Monitoring active")

    @Slot(str)
    def _on_usb_poll_error(self, error: str):
        logger.error(f"Poll error: {error}")
        self.status_bar.showMessage(f"Communication error: {error}")

    def _disconnect(self):
        """Disconnect from device and update UI."""
        # Stop USB polling worker
        self._stop_usb_worker()

        # Stop BLE worker if running
        if self.ble_poll_worker is not None:
            self.ble_poll_worker.stop()
            self.ble_poll_worker.wait(2000)  # Wait up to 2 seconds
            self.ble_poll_worker = None

        # Disconnect from USB device if connected
        if self.mc3000 is not None:
            try:
                self.mc3000.disconnect()
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")

        self.mc3000 = None
        self.transport_type = None

        # Update UI for disconnected state
        self.connection_indicator.setStyleSheet("color: #FF0000; font-size: 16px;")
        self.connection_status.setText("Disconnected")
        self.transport_label.setText("")
        self.connect_btn.setText("Connect...")

        if CONFIG_AVAILABLE and hasattr(self, 'config_btn'):
            self.config_btn.setEnabled(False)
        if hasattr(self, 'system_settings_btn'):
            self.system_settings_btn.setEnabled(False)
        if hasattr(self, 'start_btn'):
            self.start_btn.setEnabled(False)
        self.firmware_label.setText("")

        # Clear slot displays
        for slot_widget in self.slot_widgets:
            slot_widget.clear_data()

        self.status_bar.showMessage("Disconnected")

    def closeEvent(self, event):
        """Handle window close event."""
        self._stop_usb_worker()

        # Stop BLE worker if running
        if self.ble_poll_worker is not None:
            self.ble_poll_worker.stop()
            self.ble_poll_worker.wait(2000)
            self.ble_poll_worker = None

        # Disconnect from device
        if self._is_connected():
            try:
                self.mc3000.disconnect()
            except Exception as e:
                logger.warning(f"Error during disconnect on close: {e}")

        event.accept()


class SystemSettingsDialog(QDialog):
    """Dialog to display system settings (USB only)."""

    def __init__(self, mc3000: MC3000USB, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.mc3000 = mc3000
        self._setup_ui()
        self._refresh_settings()

    def _setup_ui(self):
        self.setWindowTitle("System Settings")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.firmware_label = QLabel("---")
        self.hardware_label = QLabel("---")
        self.temp_unit_label = QLabel("---")
        self.beep_label = QLabel("---")
        self.lcd_label = QLabel("---")
        self.ui_mode_label = QLabel("---")
        self.current_slot_label = QLabel("---")
        self.slot_programs_label = QLabel("---")
        self.min_voltage_label = QLabel("---")

        form_layout.addRow("Firmware:", self.firmware_label)
        form_layout.addRow("Hardware:", self.hardware_label)
        form_layout.addRow("Temperature Unit:", self.temp_unit_label)
        form_layout.addRow("Beep Tone:", self.beep_label)
        form_layout.addRow("LCD Off Time:", self.lcd_label)
        form_layout.addRow("UI Mode:", self.ui_mode_label)
        form_layout.addRow("Current Slot:", self.current_slot_label)
        form_layout.addRow("Slot Programs:", self.slot_programs_label)
        form_layout.addRow("Min Voltage:", self.min_voltage_label)

        layout.addLayout(form_layout)

        button_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._refresh_settings)
        button_layout.addWidget(self.refresh_btn)

        self.stop_btn = QPushButton("Stop All Slots")
        self.stop_btn.clicked.connect(self._stop_processing)
        self.stop_btn.setStyleSheet("QPushButton { color: #CC0000; }")
        button_layout.addWidget(self.stop_btn)

        button_layout.addStretch()
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

    def _set_label_text(self, label: QLabel, value: str):
        label.setText(value if value else "---")

    def _refresh_settings(self):
        if not self.mc3000.is_connected():
            QMessageBox.warning(self, "Not Connected", "Connect to the MC3000 to read system settings.")
            return

        settings = self.mc3000.get_system_settings()
        if not settings:
            QMessageBox.warning(self, "Read Failed", "Could not read system settings from the device.")
            return

        lcd_modes = {
            0: "Off",
            1: "Auto",
            2: "1 minute",
            3: "3 minutes",
            4: "5 minutes",
            5: "Always on",
        }
        beep_modes = {
            0: "Off",
            1: "On",
        }

        self._set_label_text(self.firmware_label, settings.firmware_version)
        self._set_label_text(self.hardware_label, str(settings.hardware_version))
        self._set_label_text(
            self.temp_unit_label,
            "Celsius (\u00b0C)" if settings.temperature_unit == 0 else "Fahrenheit (\u00b0F)",
        )
        self._set_label_text(
            self.beep_label,
            beep_modes.get(settings.beep_tone, f"Unknown ({settings.beep_tone})"),
        )
        self._set_label_text(
            self.lcd_label,
            lcd_modes.get(settings.lcd_off_time, f"Unknown ({settings.lcd_off_time})"),
        )
        self._set_label_text(self.ui_mode_label, str(settings.user_interface_mode))
        self._set_label_text(self.current_slot_label, str(settings.current_slot_number + 1))
        slot_programs = ", ".join(str(p) for p in settings.slot_programs)
        self._set_label_text(self.slot_programs_label, slot_programs)
        self._set_label_text(self.min_voltage_label, str(settings.min_voltage))

    def _stop_processing(self):
        """Stop processing on all slots."""
        if not self.mc3000.is_connected():
            QMessageBox.warning(self, "Not Connected", "Connect to the MC3000 first.")
            return

        reply = QMessageBox.question(
            self,
            "Stop All Slots",
            "Stop charging/discharging on all slots?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        if self.mc3000.stop_processing():
            QMessageBox.information(self, "Stopped", "Stop command sent to charger.")
        else:
            QMessageBox.warning(self, "Stop Failed", "Failed to send stop command.")


def create_udev_rules_message() -> str:
    """Return instructions for setting up udev rules on Linux."""
    return """
To access the MC3000 without root privileges on Linux, create a udev rule:

1. Create file /etc/udev/rules.d/99-mc3000.rules with content:
   SUBSYSTEM=="usb", ATTR{idVendor}=="0000", ATTR{idProduct}=="0001", MODE="0666"
   SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0000", ATTRS{idProduct}=="0001", MODE="0666"

2. Reload udev rules:
   sudo udevadm control --reload-rules
   sudo udevadm trigger

3. Reconnect the MC3000 device
"""


def run_gui():
    """Run the GUI application."""
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Use Fusion style for consistent cross-platform look

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(run_gui())
