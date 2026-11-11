"""
MC3000 Slot Configuration

Dialog and data structures for configuring MC3000 charger slots.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import IntEnum

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QSpinBox, QDoubleSpinBox,
    QPushButton, QGroupBox, QTabWidget, QWidget,
    QMessageBox, QFormLayout, QCheckBox, QInputDialog, QApplication,
)
from PySide6.QtCore import Qt, Signal

from mc3000_protocol import BATTERY_TYPES, OPERATION_MODES_LI, OPERATION_MODES_NI, OPERATION_MODES_ZN, SlotSettings

# Try to import profiles module
try:
    from mc3000_profiles import ProfileManager, ProfileDialog
    PROFILES_AVAILABLE = True
except ImportError:
    PROFILES_AVAILABLE = False
    ProfileManager = None
    ProfileDialog = None



class BatteryType(IntEnum):
    LiIon = 0
    LiFe = 1
    LiHV = 2
    NiMH = 3
    NiCd = 4
    NiZn = 5
    Eneloop = 6
    RAM = 7


# Manual restart-voltage ranges per chemistry (MC3000 user manual).
# A value outside the range means "restart OFF" (e.g. LiIon encodes OFF as 2300 mV).
RESTART_VOLTAGE_RANGES = {
    0: (3980, 4180),  # LiIon
    1: (3380, 3580),  # LiFe
    2: (4080, 4330),  # LiHV
    3: (1300, 1450),  # NiMH
    4: (1300, 1450),  # NiCd
    5: (1500, 1880),  # NiZn
    6: (1300, 1450),  # Eneloop
    7: (1400, 1500),  # RAM
}


def restart_voltage_is_off(battery_type: int, mv: int) -> bool:
    """True if the raw restart voltage is outside the manual range (= OFF)."""
    rng = RESTART_VOLTAGE_RANGES.get(battery_type)
    if rng is None:
        return False
    return not (rng[0] <= mv <= rng[1])


class CycleMode(IntEnum):
    CHARGE_DISCHARGE = 0  # C>D
    CHARGE_DISCHARGE_CHARGE = 1  # C>D>C
    DISCHARGE_CHARGE = 2  # D>C
    DISCHARGE_CHARGE_DISCHARGE = 3  # D>C>D


@dataclass
class SlotConfig:
    """Configuration for a single charger slot."""
    slot_number: int = 0
    battery_type: int = 0
    operation_mode: int = 0
    capacity_mah: int = 2000
    charge_current_ma: int = 1000
    discharge_current_ma: int = 500
    discharge_cut_voltage_mv: int = 900
    charge_end_voltage_mv: int = 1450
    charge_end_current_ma: int = 100
    discharge_reduce_current_ma: int = 300
    num_cycles: int = 1
    charge_resting_min: int = 3
    discharge_resting_min: int = 3
    cycle_mode: int = 0
    peak_sense_mv: int = 5  # -dV for Ni cells
    trickle_current_ma: int = 50
    trickle_time: int = 0  # 0=OFF, 1=End, 2=Rest
    restart_voltage_mv: int = 1000
    cut_temperature_c: int = 45
    cut_time_min: int = 120

    def get_operation_modes(self) -> Dict[int, str]:
        """Get available operation modes for current battery type."""
        if self.battery_type <= 2:  # Li batteries
            return OPERATION_MODES_LI
        elif self.battery_type in (3, 4, 6):  # Ni batteries
            return OPERATION_MODES_NI
        else:  # Zn/RAM
            return OPERATION_MODES_ZN

    def get_voltage_limits(self) -> tuple:
        """Get min/max voltage limits for current battery type."""
        limits = {
            0: (2500, 4200),  # LiIon
            1: (2000, 3600),  # LiFe
            2: (2500, 4350),  # LiHV
            3: (900, 1600),   # NiMH
            4: (900, 1550),   # NiCd
            5: (1200, 1900),  # NiZn
            6: (900, 1500),   # Eneloop
            7: (1200, 1800),  # RAM
        }
        return limits.get(self.battery_type, (500, 5000))

    def to_bytes(self, firmware_version: int = 123) -> bytes:
        """Convert configuration to bytes for sending to device."""
        buf = bytearray(64)

        if firmware_version <= 111:
            buf[0] = 0x0F
            buf[1] = 0x1D  # 29 bytes
            buf[2] = 0x11  # Set slot command
            buf[3] = 0x00
            buf[4] = self.slot_number
            buf[5] = self.battery_type
            buf[6] = self.capacity_mah // 100  # Capacity in 100mAh units
            buf[7] = self.operation_mode
            # Charge current (2 bytes, big-endian)
            buf[8] = (self.charge_current_ma >> 8) & 0xFF
            buf[9] = self.charge_current_ma & 0xFF
            # Discharge current (big-endian)
            buf[10] = (self.discharge_current_ma >> 8) & 0xFF
            buf[11] = self.discharge_current_ma & 0xFF
            # Discharge cut voltage (big-endian)
            buf[12] = (self.discharge_cut_voltage_mv >> 8) & 0xFF
            buf[13] = self.discharge_cut_voltage_mv & 0xFF
            # Charge end voltage (big-endian)
            buf[14] = (self.charge_end_voltage_mv >> 8) & 0xFF
            buf[15] = self.charge_end_voltage_mv & 0xFF
            # Charge end current (big-endian)
            buf[16] = (self.charge_end_current_ma >> 8) & 0xFF
            buf[17] = self.charge_end_current_ma & 0xFF
            # Discharge reduce current (big-endian)
            buf[18] = (self.discharge_reduce_current_ma >> 8) & 0xFF
            buf[19] = self.discharge_reduce_current_ma & 0xFF
            buf[20] = self.num_cycles
            buf[21] = self.charge_resting_min
            buf[22] = self.cycle_mode
            buf[23] = self.peak_sense_mv
            buf[24] = self.trickle_current_ma
            buf[25] = self.cut_temperature_c
            # Cut time (big-endian)
            buf[26] = (self.cut_time_min >> 8) & 0xFF
            buf[27] = self.cut_time_min & 0xFF
            # Restart voltage (big-endian)
            buf[28] = (self.restart_voltage_mv >> 8) & 0xFF
            buf[29] = self.restart_voltage_mv & 0xFF
            # Checksum
            buf[30] = sum(buf[2:30]) % 256
            buf[31] = 0xFF
            buf[32] = 0xFF
        else:
            buf[0] = 0x0F
            buf[1] = 0x20  # 32 bytes
            buf[2] = 0x11  # Set slot command
            buf[3] = 0x00
            buf[4] = self.slot_number
            buf[5] = self.battery_type
            # Capacity (2 bytes, big-endian)
            buf[6] = (self.capacity_mah >> 8) & 0xFF
            buf[7] = self.capacity_mah & 0xFF
            buf[8] = self.operation_mode
            # Charge current (big-endian)
            buf[9] = (self.charge_current_ma >> 8) & 0xFF
            buf[10] = self.charge_current_ma & 0xFF
            # Discharge current (big-endian)
            buf[11] = (self.discharge_current_ma >> 8) & 0xFF
            buf[12] = self.discharge_current_ma & 0xFF
            # Discharge cut voltage (big-endian)
            buf[13] = (self.discharge_cut_voltage_mv >> 8) & 0xFF
            buf[14] = self.discharge_cut_voltage_mv & 0xFF
            # Charge end voltage (big-endian)
            buf[15] = (self.charge_end_voltage_mv >> 8) & 0xFF
            buf[16] = self.charge_end_voltage_mv & 0xFF
            # Charge end current (big-endian)
            buf[17] = (self.charge_end_current_ma >> 8) & 0xFF
            buf[18] = self.charge_end_current_ma & 0xFF
            # Discharge reduce current (big-endian)
            buf[19] = (self.discharge_reduce_current_ma >> 8) & 0xFF
            buf[20] = self.discharge_reduce_current_ma & 0xFF
            buf[21] = self.num_cycles
            buf[22] = self.charge_resting_min
            buf[23] = self.discharge_resting_min
            buf[24] = self.cycle_mode
            buf[25] = self.peak_sense_mv
            buf[26] = self.trickle_current_ma
            buf[27] = self.trickle_time
            buf[28] = self.cut_temperature_c
            # Cut time (big-endian)
            buf[29] = (self.cut_time_min >> 8) & 0xFF
            buf[30] = self.cut_time_min & 0xFF
            # Restart voltage (big-endian)
            buf[31] = (self.restart_voltage_mv >> 8) & 0xFF
            buf[32] = self.restart_voltage_mv & 0xFF
            # Checksum
            buf[33] = sum(buf[2:33]) % 256
            buf[34] = 0xFF
            buf[35] = 0xFF

        return bytes(buf)


class SlotConfigWidget(QWidget):
    """Widget for configuring a single slot."""

    configChanged = Signal()

    def __init__(self, slot_number: int, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.slot_number = slot_number
        self.config = SlotConfig(slot_number=slot_number)
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Quick profile selector
        if PROFILES_AVAILABLE:
            profile_layout = QHBoxLayout()
            profile_layout.addWidget(QLabel("Quick Profile:"))
            self.profile_combo = QComboBox()
            self.profile_combo.addItem("-- Select Profile --", None)
            self._populate_profiles()
            self.profile_combo.currentIndexChanged.connect(self._on_profile_selected)
            profile_layout.addWidget(self.profile_combo, 1)
            layout.addLayout(profile_layout)

        # Row 1: Battery Settings | Current Settings
        row1 = QHBoxLayout()

        # Battery type and mode
        type_group = QGroupBox("Battery Settings")
        type_layout = QFormLayout(type_group)

        self.battery_type_combo = QComboBox()
        for idx, name in BATTERY_TYPES.items():
            self.battery_type_combo.addItem(name, idx)
        type_layout.addRow("Type:", self.battery_type_combo)

        self.mode_combo = QComboBox()
        self._update_mode_combo()
        type_layout.addRow("Mode:", self.mode_combo)

        self.capacity_spin = QSpinBox()
        self.capacity_spin.setRange(100, 20000)
        self.capacity_spin.setSingleStep(100)
        self.capacity_spin.setValue(2000)
        self.capacity_spin.setSuffix(" mAh")
        type_layout.addRow("Capacity:", self.capacity_spin)

        row1.addWidget(type_group)

        # Current settings
        current_group = QGroupBox("Current Settings")
        current_layout = QFormLayout(current_group)

        self.charge_current_spin = QSpinBox()
        self.charge_current_spin.setRange(100, 3000)
        self.charge_current_spin.setSingleStep(100)
        self.charge_current_spin.setValue(1000)
        self.charge_current_spin.setSuffix(" mA")
        current_layout.addRow("Charge:", self.charge_current_spin)

        self.discharge_current_spin = QSpinBox()
        self.discharge_current_spin.setRange(100, 2000)
        self.discharge_current_spin.setSingleStep(100)
        self.discharge_current_spin.setValue(500)
        self.discharge_current_spin.setSuffix(" mA")
        current_layout.addRow("Discharge:", self.discharge_current_spin)

        self.end_current_spin = QSpinBox()
        self.end_current_spin.setRange(50, 500)
        self.end_current_spin.setSingleStep(10)
        self.end_current_spin.setValue(100)
        self.end_current_spin.setSuffix(" mA")
        current_layout.addRow("End (CC/CV):", self.end_current_spin)

        row1.addWidget(current_group)
        layout.addLayout(row1)

        # Row 2: Voltage Settings | Cycle Settings
        row2 = QHBoxLayout()

        # Voltage settings
        voltage_group = QGroupBox("Voltage Settings")
        voltage_layout = QFormLayout(voltage_group)

        self.end_voltage_spin = QSpinBox()
        self.end_voltage_spin.setRange(500, 5000)
        self.end_voltage_spin.setSingleStep(10)
        self.end_voltage_spin.setValue(1450)
        self.end_voltage_spin.setSuffix(" mV")
        voltage_layout.addRow("Target:", self.end_voltage_spin)

        self.cut_voltage_spin = QSpinBox()
        self.cut_voltage_spin.setRange(500, 4000)
        self.cut_voltage_spin.setSingleStep(10)
        self.cut_voltage_spin.setValue(900)
        self.cut_voltage_spin.setSuffix(" mV")
        voltage_layout.addRow("Cut-off:", self.cut_voltage_spin)

        self.restart_voltage_spin = QSpinBox()
        self.restart_voltage_spin.setRange(500, 4500)
        self.restart_voltage_spin.setSingleStep(10)
        self.restart_voltage_spin.setValue(1000)
        self.restart_voltage_spin.setSuffix(" mV")
        self.restart_voltage_spin.setToolTip(
            "Voltage threshold to resume charging after the program finished.\n"
            "Values outside the range given in the manual mean OFF "
            "(the charger encodes OFF e.g. as 2300 mV for LiIon).")
        self.restart_state_label = QLabel("")
        self.restart_state_label.setStyleSheet("color: gray;")
        restart_row = QHBoxLayout()
        restart_row.addWidget(self.restart_voltage_spin, 1)
        restart_row.addWidget(self.restart_state_label)
        voltage_layout.addRow("Restart:", restart_row)

        row2.addWidget(voltage_group)

        # Cycle settings
        cycle_group = QGroupBox("Cycle Settings")
        cycle_layout = QFormLayout(cycle_group)

        self.cycle_count_spin = QSpinBox()
        self.cycle_count_spin.setRange(1, 99)
        self.cycle_count_spin.setValue(1)
        cycle_layout.addRow("Count:", self.cycle_count_spin)

        self.cycle_mode_combo = QComboBox()
        self.cycle_mode_combo.addItems(["C>D", "C>D>C", "D>C", "D>C>D"])
        cycle_layout.addRow("Mode:", self.cycle_mode_combo)

        self.charge_rest_time_spin = QSpinBox()
        self.charge_rest_time_spin.setRange(1, 60)
        self.charge_rest_time_spin.setValue(3)
        self.charge_rest_time_spin.setSuffix(" min")
        cycle_layout.addRow("Charge Rest:", self.charge_rest_time_spin)

        self.discharge_rest_time_spin = QSpinBox()
        self.discharge_rest_time_spin.setRange(1, 60)
        self.discharge_rest_time_spin.setValue(3)
        self.discharge_rest_time_spin.setSuffix(" min")
        cycle_layout.addRow("Discharge Rest:", self.discharge_rest_time_spin)

        row2.addWidget(cycle_group)
        layout.addLayout(row2)

        # Row 3: Advanced Settings | Safety Limits
        row3 = QHBoxLayout()

        # Advanced settings
        advanced_group = QGroupBox("Advanced Settings")
        advanced_layout = QFormLayout(advanced_group)

        self.discharge_end_current_spin = QSpinBox()
        self.discharge_end_current_spin.setRange(100, 500)
        self.discharge_end_current_spin.setSingleStep(10)
        self.discharge_end_current_spin.setValue(300)
        self.discharge_end_current_spin.setSuffix(" mA")
        advanced_layout.addRow("Disch. End Current:", self.discharge_end_current_spin)

        self.peak_sense_spin = QSpinBox()
        self.peak_sense_spin.setRange(1, 20)
        self.peak_sense_spin.setValue(5)
        self.peak_sense_spin.setSuffix(" mV")
        self.peak_sense_spin.setToolTip("-dV detection for NiMH/NiCd batteries")
        advanced_layout.addRow("Peak Sense (-dV):", self.peak_sense_spin)

        self.trickle_current_spin = QSpinBox()
        self.trickle_current_spin.setRange(0, 200)
        self.trickle_current_spin.setSingleStep(10)
        self.trickle_current_spin.setValue(50)
        self.trickle_current_spin.setSuffix(" mA")
        self.trickle_current_spin.setSpecialValueText("OFF")
        self.trickle_current_spin.setToolTip("Trickle current to maintain charge after charging ends")
        advanced_layout.addRow("Trickle Current:", self.trickle_current_spin)

        self.trickle_time_combo = QComboBox()
        self.trickle_time_combo.addItem("OFF", 0)
        self.trickle_time_combo.addItem("End", 1)
        self.trickle_time_combo.addItem("Rest", 2)
        self.trickle_time_combo.setToolTip("When to activate trickle charging")
        advanced_layout.addRow("Trickle Time:", self.trickle_time_combo)

        row3.addWidget(advanced_group)

        # Safety settings
        safety_group = QGroupBox("Safety Limits")
        safety_layout = QFormLayout(safety_group)

        self.cut_temp_spin = QSpinBox()
        self.cut_temp_spin.setRange(20, 80)
        self.cut_temp_spin.setValue(45)
        self.cut_temp_spin.setSuffix(" °C")
        safety_layout.addRow("Cut-off Temp:", self.cut_temp_spin)

        self.cut_time_spin = QSpinBox()
        self.cut_time_spin.setRange(0, 600)
        self.cut_time_spin.setValue(120)
        self.cut_time_spin.setSuffix(" min")
        self.cut_time_spin.setSpecialValueText("OFF")
        safety_layout.addRow("Cut-off Time:", self.cut_time_spin)

        row3.addWidget(safety_group)
        layout.addLayout(row3)

        # Initialize voltage limits and peak sense visibility based on default battery type
        self._update_voltage_limits()

        layout.addStretch()

    def _connect_signals(self):
        self.battery_type_combo.currentIndexChanged.connect(self._on_battery_type_changed)
        self.battery_type_combo.currentIndexChanged.connect(self.configChanged)
        self.mode_combo.currentIndexChanged.connect(self.configChanged)
        self.capacity_spin.valueChanged.connect(self.configChanged)
        self.charge_current_spin.valueChanged.connect(self.configChanged)
        self.discharge_current_spin.valueChanged.connect(self.configChanged)
        self.end_current_spin.valueChanged.connect(self.configChanged)
        self.end_voltage_spin.valueChanged.connect(self.configChanged)
        self.cut_voltage_spin.valueChanged.connect(self.configChanged)
        self.cycle_count_spin.valueChanged.connect(self.configChanged)
        self.cycle_mode_combo.currentIndexChanged.connect(self.configChanged)
        self.charge_rest_time_spin.valueChanged.connect(self.configChanged)
        self.discharge_rest_time_spin.valueChanged.connect(self.configChanged)
        self.discharge_end_current_spin.valueChanged.connect(self.configChanged)
        self.peak_sense_spin.valueChanged.connect(self.configChanged)
        self.trickle_current_spin.valueChanged.connect(self.configChanged)
        self.trickle_time_combo.currentIndexChanged.connect(self.configChanged)
        self.restart_voltage_spin.valueChanged.connect(self.configChanged)
        self.restart_voltage_spin.valueChanged.connect(self._update_restart_label)
        self.cut_temp_spin.valueChanged.connect(self.configChanged)
        self.cut_time_spin.valueChanged.connect(self.configChanged)

    def _on_battery_type_changed(self, index):
        self._update_mode_combo()
        self._update_voltage_limits()

    def _update_mode_combo(self):
        self.mode_combo.clear()
        battery_type = self.battery_type_combo.currentData()
        if battery_type is None:
            battery_type = 0
        self.config.battery_type = battery_type
        modes = self.config.get_operation_modes()
        for idx, name in modes.items():
            self.mode_combo.addItem(name, idx)

    def _update_voltage_limits(self):
        battery_type = self.battery_type_combo.currentData()
        if battery_type is None:
            battery_type = 0
        min_v, max_v = self.config.get_voltage_limits()
        self.end_voltage_spin.setRange(min_v, max_v)
        self.cut_voltage_spin.setRange(min_v - 500, max_v)
        # Update restart voltage range based on battery type
        self.restart_voltage_spin.setRange(min_v - 200, max_v)
        self._update_restart_label()
        # Peak sense (-dV) is only for Ni batteries (NiMH, NiCd, Eneloop)
        is_ni_battery = battery_type in (3, 4, 6)  # NiMH, NiCd, Eneloop
        self.peak_sense_spin.setEnabled(is_ni_battery)
        if not is_ni_battery:
            self.peak_sense_spin.setToolTip("-dV detection (only for NiMH/NiCd/Eneloop)")
        else:
            self.peak_sense_spin.setToolTip("-dV detection for NiMH/NiCd batteries")

    def _update_restart_label(self, *_):
        battery_type = self.battery_type_combo.currentData()
        if battery_type is None:
            battery_type = 0
        if restart_voltage_is_off(battery_type, self.restart_voltage_spin.value()):
            self.restart_state_label.setText("= OFF")
        else:
            self.restart_state_label.setText("")

    def _set_spin_raw(self, spin: QSpinBox, value: int):
        """Set a spin box without clamping the raw device value.

        If the charger reports a value outside the GUI range, the range is
        widened instead of silently changing the value (which would be
        written back on "Apply").
        """
        if value < spin.minimum():
            spin.setMinimum(value)
        if value > spin.maximum():
            spin.setMaximum(value)
        spin.setValue(value)

    def get_config(self) -> SlotConfig:
        """Get current configuration from UI."""
        return SlotConfig(
            slot_number=self.slot_number,
            battery_type=self.battery_type_combo.currentData() or 0,
            operation_mode=self.mode_combo.currentData() or 0,
            capacity_mah=self.capacity_spin.value(),
            charge_current_ma=self.charge_current_spin.value(),
            discharge_current_ma=self.discharge_current_spin.value(),
            charge_end_voltage_mv=self.end_voltage_spin.value(),
            discharge_cut_voltage_mv=self.cut_voltage_spin.value(),
            charge_end_current_ma=self.end_current_spin.value(),
            discharge_reduce_current_ma=self.discharge_end_current_spin.value(),
            num_cycles=self.cycle_count_spin.value(),
            cycle_mode=self.cycle_mode_combo.currentIndex(),
            charge_resting_min=self.charge_rest_time_spin.value(),
            discharge_resting_min=self.discharge_rest_time_spin.value(),
            peak_sense_mv=self.peak_sense_spin.value(),
            trickle_current_ma=self.trickle_current_spin.value(),
            trickle_time=self.trickle_time_combo.currentData() or 0,
            restart_voltage_mv=self.restart_voltage_spin.value(),
            cut_temperature_c=self.cut_temp_spin.value(),
            cut_time_min=self.cut_time_spin.value(),
        )

    def set_config(self, config: SlotConfig):
        """Set UI from configuration."""
        self.battery_type_combo.setCurrentIndex(
            self.battery_type_combo.findData(config.battery_type)
        )
        self._update_mode_combo()
        self.mode_combo.setCurrentIndex(
            self.mode_combo.findData(config.operation_mode)
        )
        self.capacity_spin.setValue(config.capacity_mah)
        self.charge_current_spin.setValue(config.charge_current_ma)
        self.discharge_current_spin.setValue(config.discharge_current_ma)
        self.end_voltage_spin.setValue(config.charge_end_voltage_mv)
        self.cut_voltage_spin.setValue(config.discharge_cut_voltage_mv)
        self.end_current_spin.setValue(config.charge_end_current_ma)
        self.discharge_end_current_spin.setValue(config.discharge_reduce_current_ma)
        self.cycle_count_spin.setValue(config.num_cycles)
        self.cycle_mode_combo.setCurrentIndex(config.cycle_mode)
        self.charge_rest_time_spin.setValue(config.charge_resting_min)
        self.discharge_rest_time_spin.setValue(config.discharge_resting_min)
        self.peak_sense_spin.setValue(config.peak_sense_mv)
        self.trickle_current_spin.setValue(config.trickle_current_ma)
        self.trickle_time_combo.setCurrentIndex(
            self.trickle_time_combo.findData(config.trickle_time)
        )
        self.restart_voltage_spin.setValue(config.restart_voltage_mv)
        self.cut_temp_spin.setValue(config.cut_temperature_c)
        self.cut_time_spin.setValue(config.cut_time_min)

    def set_from_slot_settings(self, settings: SlotSettings):
        """Set UI from SlotSettings read from device."""
        self.battery_type_combo.setCurrentIndex(
            self.battery_type_combo.findData(settings.battery_type)
        )
        self._update_mode_combo()
        self._update_voltage_limits()
        self.mode_combo.setCurrentIndex(
            self.mode_combo.findData(settings.operation_mode)
        )
        self._set_spin_raw(self.capacity_spin, settings.capacity_mah)
        self._set_spin_raw(self.charge_current_spin, settings.charge_current_ma)
        self._set_spin_raw(self.discharge_current_spin, settings.discharge_current_ma)
        self._set_spin_raw(self.end_voltage_spin, settings.charge_end_voltage_mv)
        self._set_spin_raw(self.cut_voltage_spin, settings.discharge_cut_voltage_mv)
        self._set_spin_raw(self.end_current_spin, settings.charge_end_current_ma)
        self._set_spin_raw(self.discharge_end_current_spin, settings.discharge_reduce_current_ma)
        self.cycle_count_spin.setValue(settings.num_cycles)
        self.cycle_mode_combo.setCurrentIndex(settings.cycle_mode)
        self.charge_rest_time_spin.setValue(settings.charge_resting_min)
        # discharge_resting_min may be 0 for older firmware, use charge_resting_min as fallback
        discharge_rest = settings.discharge_resting_min if settings.discharge_resting_min > 0 else settings.charge_resting_min
        self.discharge_rest_time_spin.setValue(discharge_rest)
        self.peak_sense_spin.setValue(settings.peak_sense_mv)
        self.trickle_current_spin.setValue(settings.trickle_current_ma)
        trickle_time_idx = self.trickle_time_combo.findData(settings.trickle_time)
        if trickle_time_idx >= 0:
            self.trickle_time_combo.setCurrentIndex(trickle_time_idx)
        self._set_spin_raw(self.restart_voltage_spin, settings.restart_voltage_mv)
        self._set_spin_raw(self.cut_temp_spin, settings.cut_temperature_c)
        self._set_spin_raw(self.cut_time_spin, settings.cut_time_min)
        self._update_restart_label()

    def _populate_profiles(self):
        """Populate the profile combo box."""
        if not PROFILES_AVAILABLE:
            return
        from mc3000_profiles import ProfileManager, BUILTIN_PRESETS
        pm = ProfileManager()
        # Add built-in profiles
        for name in sorted(BUILTIN_PRESETS.keys()):
            self.profile_combo.addItem(name, name)
        # Add user profiles
        user_profiles = pm.get_user_profiles()
        if user_profiles:
            self.profile_combo.insertSeparator(self.profile_combo.count())
            for name in sorted(user_profiles.keys()):
                self.profile_combo.addItem(f"* {name}", name)

    def _on_profile_selected(self, index):
        """Handle profile selection from combo box."""
        if not PROFILES_AVAILABLE or index <= 0:
            return
        profile_name = self.profile_combo.currentData()
        if not profile_name:
            return
        from mc3000_profiles import ProfileManager
        pm = ProfileManager()
        config = pm.profile_to_config(profile_name, self.slot_number)
        if config:
            self.set_config(config)
        # Reset combo to "Select Profile" after applying
        self.profile_combo.blockSignals(True)
        self.profile_combo.setCurrentIndex(0)
        self.profile_combo.blockSignals(False)


class SlotConfigDialog(QDialog):
    """Dialog for configuring charger slots."""

    def __init__(self, mc3000_usb, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.mc3000 = mc3000_usb
        self.profile_manager = ProfileManager() if PROFILES_AVAILABLE else None
        self.setWindowTitle("Slot Configuration")
        self.setMinimumSize(580, 730)
        self.resize(620, 785)
        self._slot_read_ok = [False] * 4
        self._setup_ui()
        self._read_all_configs(show_message=False)

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Tab widget for each slot
        self.tab_widget = QTabWidget()
        self.slot_widgets: List[SlotConfigWidget] = []

        for i in range(4):
            widget = SlotConfigWidget(i)
            self.slot_widgets.append(widget)
            self.tab_widget.addTab(widget, f"Slot {i + 1}")

        layout.addWidget(self.tab_widget)

        # Shown when slot settings could not be read from the charger
        self.read_status_label = QLabel("")
        self.read_status_label.setWordWrap(True)
        self.read_status_label.setStyleSheet("color: #CC0000; font-weight: bold;")
        self.read_status_label.hide()
        layout.addWidget(self.read_status_label)

        # Copy settings controls
        copy_group = QGroupBox("Copy Settings")
        copy_layout = QHBoxLayout(copy_group)

        copy_layout.addWidget(QLabel("Copy from:"))
        self.copy_from_combo = QComboBox()
        self.copy_from_combo.addItems(["Slot 1", "Slot 2", "Slot 3", "Slot 4"])
        copy_layout.addWidget(self.copy_from_combo)

        copy_layout.addWidget(QLabel("to:"))
        self.copy_to_combo = QComboBox()
        self.copy_to_combo.addItem("Slot 1", 0)
        self.copy_to_combo.addItem("Slot 2", 1)
        self.copy_to_combo.addItem("Slot 3", 2)
        self.copy_to_combo.addItem("Slot 4", 3)
        self.copy_to_combo.addItem("All slots", -1)
        self.copy_to_combo.setCurrentIndex(1)
        copy_layout.addWidget(self.copy_to_combo)

        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(self._copy_settings)
        copy_layout.addWidget(copy_btn)

        copy_layout.addStretch()
        layout.addWidget(copy_group)

        # Profile controls
        if PROFILES_AVAILABLE:
            profile_group = QGroupBox("Profiles")
            profile_layout = QHBoxLayout(profile_group)

            self.save_profile_btn = QPushButton("Save Current as Profile...")
            self.save_profile_btn.clicked.connect(self._save_profile)
            profile_layout.addWidget(self.save_profile_btn)

            self.manage_profiles_btn = QPushButton("Manage Profiles...")
            self.manage_profiles_btn.clicked.connect(self._manage_profiles)
            profile_layout.addWidget(self.manage_profiles_btn)

            profile_layout.addStretch()
            layout.addWidget(profile_group)

        # Buttons
        button_layout = QHBoxLayout()

        self.apply_btn = QPushButton("Apply to Charger")
        self.apply_btn.clicked.connect(self._apply_config)
        button_layout.addWidget(self.apply_btn)

        self.read_all_btn = QPushButton("Read All Slots")
        self.read_all_btn.clicked.connect(self._read_all_configs)
        button_layout.addWidget(self.read_all_btn)

        button_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _refresh_profile_combos(self):
        """Refresh profile combo boxes in all slot widgets."""
        if not PROFILES_AVAILABLE:
            return
        from mc3000_profiles import ProfileManager, BUILTIN_PRESETS
        pm = ProfileManager()
        user_profiles = pm.get_user_profiles()

        for widget in self.slot_widgets:
            if hasattr(widget, 'profile_combo'):
                widget.profile_combo.blockSignals(True)
                widget.profile_combo.clear()
                widget.profile_combo.addItem("-- Select Profile --", None)
                # Add built-in profiles
                for name in sorted(BUILTIN_PRESETS.keys()):
                    widget.profile_combo.addItem(name, name)
                # Add user profiles
                if user_profiles:
                    widget.profile_combo.insertSeparator(widget.profile_combo.count())
                    for name in sorted(user_profiles.keys()):
                        widget.profile_combo.addItem(f"* {name}", name)
                widget.profile_combo.blockSignals(False)

    def _copy_settings(self):
        """Copy settings from one slot to another."""
        from_idx = self.copy_from_combo.currentIndex()
        to_idx = self.copy_to_combo.currentData()
        if to_idx is None:
            to_idx = self.copy_to_combo.currentIndex()

        if to_idx != -1 and from_idx == to_idx:
            QMessageBox.warning(self, "Copy Error", "Source and destination slots are the same.")
            return

        config = self.slot_widgets[from_idx].get_config()

        if to_idx == -1:
            for slot_idx in range(4):
                config.slot_number = slot_idx
                self.slot_widgets[slot_idx].set_config(config)
            QMessageBox.information(
                self, "Copy Complete",
                f"Settings copied from Slot {from_idx + 1} to all slots"
            )
            return

        config.slot_number = to_idx
        self.slot_widgets[to_idx].set_config(config)
        self.tab_widget.setCurrentIndex(to_idx)

        QMessageBox.information(
            self, "Copy Complete",
            f"Settings copied from Slot {from_idx + 1} to Slot {to_idx + 1}"
        )

    def _apply_config(self):
        """Apply current slot configuration to charger."""
        if not self.mc3000.is_connected():
            QMessageBox.warning(self, "Not Connected", "Please connect to the charger first.")
            return

        current_slot = self.tab_widget.currentIndex()
        config = self.slot_widgets[current_slot].get_config()

        if not self._slot_read_ok[current_slot]:
            warn = QMessageBox.warning(
                self, "Slot not read",
                f"The settings of Slot {current_slot + 1} were never read from the "
                "charger. The values shown may be defaults.\n\n"
                "Apply them anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if warn != QMessageBox.Yes:
                return

        reply = QMessageBox.question(
            self, "Confirm Apply",
            f"Apply configuration to Slot {current_slot + 1}?\n\n"
            f"Battery: {BATTERY_TYPES.get(config.battery_type, 'Unknown')}\n"
            f"Mode: {config.get_operation_modes().get(config.operation_mode, 'Unknown')}\n"
            f"Capacity: {config.capacity_mah} mAh\n"
            f"Charge Current: {config.charge_current_ma} mA",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            try:
                fw_version = self.mc3000.firmware_version_int or 123
                data = config.to_bytes(fw_version)
                success = self.mc3000.set_slot_config(data)
                if success:
                    QMessageBox.information(self, "Success", "Configuration applied successfully!")
                else:
                    QMessageBox.warning(self, "Error", "Failed to apply configuration.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error applying configuration: {e}")

    # def _read_config(self):
    #     """Read configuration from charger for current slot."""
    #     if not self.mc3000.is_connected():
    #         QMessageBox.warning(self, "Not Connected", "Please connect to the charger first.")
    #         return
    #
    #     current_slot = self.tab_widget.currentIndex()
    #
    #     try:
    #         settings = self.mc3000.get_slot_settings(current_slot)
    #         if settings:
    #             self.slot_widgets[current_slot].set_from_slot_settings(settings)
    #             QMessageBox.information(
    #                 self, "Read Complete",
    #                 f"Configuration read from Slot {current_slot + 1}.\n\n"
    #                 f"Battery: {BATTERY_TYPES.get(settings.battery_type, 'Unknown')}\n"
    #                 f"Capacity: {settings.capacity_mah} mAh\n"
    #                 f"Charge Current: {settings.charge_current_ma} mA\n"
    #                 f"Discharge Current: {settings.discharge_current_ma} mA"
    #             )
    #         else:
    #             QMessageBox.warning(
    #                 self, "Read Failed",
    #                 f"Could not read configuration from Slot {current_slot + 1}."
    #             )
    #     except Exception as e:
    #         QMessageBox.critical(self, "Error", f"Error reading configuration: {e}")

    def _read_slots(self):
        """Read all four slots; give up quickly when the charger is silent."""
        failures = 0
        for i in range(4):
            ok = False
            try:
                # After two silent slots the charger is most likely busy
                # (SkyRC app live view) - do not keep the GUI waiting.
                settings = self.mc3000.get_slot_settings(i, tries=1 if failures else 2)
                if settings:
                    self.slot_widgets[i].set_from_slot_settings(settings)
                    ok = True
            except Exception:
                pass  # Continue with other slots
            if not ok:
                failures += 1
            self._slot_read_ok[i] = ok
            self.tab_widget.setTabText(i, f"Slot {i + 1}" if ok else f"Slot {i + 1} (not read)")

    def _read_all_configs(self, show_message: bool = True):
        """Read configuration from all slots."""
        if not self.mc3000.is_connected():
            if show_message:
                QMessageBox.warning(self, "Not Connected", "Please connect to the charger first.")
            return

        success_count = 0
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._read_slots()
        finally:
            QApplication.restoreOverrideCursor()
        success_count = sum(self._slot_read_ok)

        failed = [str(i + 1) for i in range(4) if not self._slot_read_ok[i]]
        if failed:
            self.read_status_label.setText(
                f"Could not read slot(s) {', '.join(failed)} from the charger - the values "
                "shown there may be defaults or outdated. If the SkyRC app is "
                "showing live data via Bluetooth, close that view and click \"Read All Slots\"."
            )
            self.read_status_label.show()
        else:
            self.read_status_label.hide()

        if show_message:
            if success_count > 0:
                QMessageBox.information(
                    self, "Read Complete",
                    f"Successfully read configuration from {success_count}/4 slots."
                )
            else:
                QMessageBox.warning(self, "Read Failed", "Could not read configuration from any slot.")

    def _manage_profiles(self):
        """Open profile management dialog."""
        if not self.profile_manager:
            return

        dialog = ProfileDialog(self.profile_manager, self)
        result = dialog.exec()
        # Refresh combos in case profiles were deleted
        self._refresh_profile_combos()
        if result == QDialog.Accepted:
            profile_name = dialog.get_selected_profile()
            if profile_name:
                current_slot = self.tab_widget.currentIndex()
                config = self.profile_manager.profile_to_config(profile_name, current_slot)
                if config:
                    self.slot_widgets[current_slot].set_config(config)

    def _save_profile(self):
        """Save current slot configuration as a profile."""
        if not self.profile_manager:
            return

        current_slot = self.tab_widget.currentIndex()
        config = self.slot_widgets[current_slot].get_config()

        name, ok = QInputDialog.getText(
            self, "Save Profile",
            "Enter a name for this profile:",
            text=f"My {BATTERY_TYPES.get(config.battery_type, 'Battery')} Profile"
        )

        if ok and name:
            # Check if name already exists
            if self.profile_manager.get_profile(name):
                if self.profile_manager.is_builtin(name):
                    QMessageBox.warning(
                        self, "Cannot Overwrite",
                        "Cannot overwrite a built-in preset. Please choose a different name."
                    )
                    return

                reply = QMessageBox.question(
                    self, "Overwrite Profile",
                    f"Profile '{name}' already exists. Overwrite?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return

            try:
                self.profile_manager.save_profile(name, config)
                self._refresh_profile_combos()
                QMessageBox.information(
                    self, "Profile Saved",
                    f"Profile '{name}' saved successfully."
                )
            except Exception as e:
                QMessageBox.critical(
                    self, "Save Error",
                    f"Failed to save profile: {e}"
                )
