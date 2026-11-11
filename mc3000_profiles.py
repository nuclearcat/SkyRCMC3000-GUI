"""
MC3000 Configuration Profiles

Save, load, and manage charging profiles for common battery types.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QMessageBox, QGroupBox,
    QFormLayout, QWidget, QInputDialog,
)
from PySide6.QtCore import Qt, Signal

# Default profiles directory
def get_profiles_dir() -> Path:
    """Get the profiles directory, creating it if needed."""
    # Use XDG config dir on Linux, AppData on Windows, etc.
    if os.name == 'nt':  # Windows
        base = Path(os.environ.get('APPDATA', Path.home()))
    else:  # Linux/Mac
        base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))

    profiles_dir = base / 'mc3000-gui' / 'profiles'
    profiles_dir.mkdir(parents=True, exist_ok=True)
    return profiles_dir


def get_profiles_file() -> Path:
    """Get the profiles JSON file path."""
    return get_profiles_dir() / 'profiles.json'


# Built-in presets for common battery types
BUILTIN_PRESETS: Dict[str, Dict[str, Any]] = {
    # "Idle" programs: the USB start command has no slot parameter, so every
    # idle slot with a cell starts. These programs keep a slot from charging:
    # the target voltage is below any healthy cell, so no current flows and
    # the slot ends with "Time Cut" after one minute.
    # LiIon variant tested on the device (cells 3.29-4.19 V: 0 mA, 0 mAh).
    "Idle - LiIon (no charge)": {
        "battery_type": 0,  # LiIon
        "operation_mode": 0,  # Charge
        "capacity_mah": 100,
        "charge_current_ma": 100,
        "discharge_current_ma": 500,
        "charge_end_voltage_mv": 2500,
        "discharge_cut_voltage_mv": 3000,
        "charge_end_current_ma": 100,
        "discharge_reduce_current_ma": 500,
        "num_cycles": 1,
        "cycle_mode": 0,
        "charge_resting_min": 1,
        "discharge_resting_min": 1,
        "trickle_current_ma": 1,
        "trickle_time": 0,
        "restart_voltage_mv": 2300,  # = OFF
        "cut_temperature_c": 45,
        "cut_time_min": 1,
    },
    # NiMH variant (tested): the charger does not check the target before
    # starting, it charges ~20 s at 100 mA and stops with "Time Cut" after
    # one minute - below 1 mAh.
    "Idle - NiMH (max 1 min, <2 mAh)": {
        "battery_type": 3,  # NiMH
        "operation_mode": 0,  # Charge
        "capacity_mah": 100,
        "charge_current_ma": 100,
        "discharge_current_ma": 100,
        "charge_end_voltage_mv": 900,
        "discharge_cut_voltage_mv": 900,
        "charge_end_current_ma": 100,
        "discharge_reduce_current_ma": 100,
        "num_cycles": 1,
        "cycle_mode": 0,
        "charge_resting_min": 1,
        "discharge_resting_min": 1,
        "peak_sense_mv": 3,
        "trickle_current_ma": 1,
        "trickle_time": 0,
        "restart_voltage_mv": 1300,
        "cut_temperature_c": 45,
        "cut_time_min": 1,
    },
    # NiMH AA batteries
    "NiMH AA 2000mAh (Standard)": {
        "battery_type": 3,  # NiMH
        "operation_mode": 0,  # Charge
        "capacity_mah": 2000,
        "charge_current_ma": 1000,
        "discharge_current_ma": 500,
        "charge_end_voltage_mv": 1450,
        "discharge_cut_voltage_mv": 900,
        "charge_end_current_ma": 100,
        "num_cycles": 1,
        "cycle_mode": 0,
        "charge_resting_min": 3,
        "cut_temperature_c": 45,
        "cut_time_min": 180,
    },
    "NiMH AA 2500mAh (High Cap)": {
        "battery_type": 3,
        "operation_mode": 0,
        "capacity_mah": 2500,
        "charge_current_ma": 1000,
        "discharge_current_ma": 500,
        "charge_end_voltage_mv": 1450,
        "discharge_cut_voltage_mv": 900,
        "charge_end_current_ma": 100,
        "num_cycles": 1,
        "cycle_mode": 0,
        "charge_resting_min": 3,
        "cut_temperature_c": 45,
        "cut_time_min": 210,
    },
    "NiMH AAA 800mAh": {
        "battery_type": 3,
        "operation_mode": 0,
        "capacity_mah": 800,
        "charge_current_ma": 400,
        "discharge_current_ma": 200,
        "charge_end_voltage_mv": 1450,
        "discharge_cut_voltage_mv": 900,
        "charge_end_current_ma": 50,
        "num_cycles": 1,
        "cycle_mode": 0,
        "charge_resting_min": 3,
        "cut_temperature_c": 45,
        "cut_time_min": 150,
    },
    # Eneloop
    "Eneloop AA 2000mAh": {
        "battery_type": 6,  # Eneloop
        "operation_mode": 0,
        "capacity_mah": 2000,
        "charge_current_ma": 1000,
        "discharge_current_ma": 500,
        "charge_end_voltage_mv": 1450,
        "discharge_cut_voltage_mv": 900,
        "charge_end_current_ma": 100,
        "num_cycles": 1,
        "cycle_mode": 0,
        "charge_resting_min": 3,
        "cut_temperature_c": 45,
        "cut_time_min": 180,
    },
    "Eneloop Pro AA 2500mAh": {
        "battery_type": 6,
        "operation_mode": 0,
        "capacity_mah": 2500,
        "charge_current_ma": 1000,
        "discharge_current_ma": 500,
        "charge_end_voltage_mv": 1450,
        "discharge_cut_voltage_mv": 900,
        "charge_end_current_ma": 100,
        "num_cycles": 1,
        "cycle_mode": 0,
        "charge_resting_min": 3,
        "cut_temperature_c": 45,
        "cut_time_min": 210,
    },
    # Li-Ion 18650
    "Li-Ion 18650 2600mAh": {
        "battery_type": 0,  # LiIon
        "operation_mode": 0,
        "capacity_mah": 2600,
        "charge_current_ma": 1000,
        "discharge_current_ma": 500,
        "charge_end_voltage_mv": 4200,
        "discharge_cut_voltage_mv": 2800,
        "charge_end_current_ma": 100,
        "num_cycles": 1,
        "cycle_mode": 0,
        "charge_resting_min": 5,
        "cut_temperature_c": 45,
        "cut_time_min": 240,
    },
    "Li-Ion 18650 3000mAh": {
        "battery_type": 0,
        "operation_mode": 0,
        "capacity_mah": 3000,
        "charge_current_ma": 1500,
        "discharge_current_ma": 500,
        "charge_end_voltage_mv": 4200,
        "discharge_cut_voltage_mv": 2800,
        "charge_end_current_ma": 100,
        "num_cycles": 1,
        "cycle_mode": 0,
        "charge_resting_min": 5,
        "cut_temperature_c": 45,
        "cut_time_min": 240,
    },
    "Li-Ion 18650 3500mAh": {
        "battery_type": 0,
        "operation_mode": 0,
        "capacity_mah": 3500,
        "charge_current_ma": 1500,
        "discharge_current_ma": 500,
        "charge_end_voltage_mv": 4200,
        "discharge_cut_voltage_mv": 2800,
        "charge_end_current_ma": 100,
        "num_cycles": 1,
        "cycle_mode": 0,
        "charge_resting_min": 5,
        "cut_temperature_c": 45,
        "cut_time_min": 270,
    },
    # LiFePO4
    "LiFePO4 18650 1500mAh": {
        "battery_type": 1,  # LiFe
        "operation_mode": 0,
        "capacity_mah": 1500,
        "charge_current_ma": 750,
        "discharge_current_ma": 500,
        "charge_end_voltage_mv": 3650,
        "discharge_cut_voltage_mv": 2500,
        "charge_end_current_ma": 75,
        "num_cycles": 1,
        "cycle_mode": 0,
        "charge_resting_min": 5,
        "cut_temperature_c": 45,
        "cut_time_min": 180,
    },
    # NiCd
    "NiCd AA 1000mAh": {
        "battery_type": 4,  # NiCd
        "operation_mode": 0,
        "capacity_mah": 1000,
        "charge_current_ma": 500,
        "discharge_current_ma": 500,
        "charge_end_voltage_mv": 1450,
        "discharge_cut_voltage_mv": 900,
        "charge_end_current_ma": 50,
        "num_cycles": 1,
        "cycle_mode": 0,
        "charge_resting_min": 3,
        "cut_temperature_c": 45,
        "cut_time_min": 150,
    },
    # Refresh/Break-in profiles
    "NiMH Refresh (C>D>C)": {
        "battery_type": 3,
        "operation_mode": 1,  # Refresh
        "capacity_mah": 2000,
        "charge_current_ma": 1000,
        "discharge_current_ma": 500,
        "charge_end_voltage_mv": 1450,
        "discharge_cut_voltage_mv": 900,
        "charge_end_current_ma": 100,
        "num_cycles": 1,
        "cycle_mode": 0,
        "charge_resting_min": 5,
        "cut_temperature_c": 45,
        "cut_time_min": 300,
    },
    "NiMH Break-in (New Battery)": {
        "battery_type": 3,
        "operation_mode": 2,  # Break-in
        "capacity_mah": 2000,
        "charge_current_ma": 200,  # Slow charge for break-in
        "discharge_current_ma": 200,
        "charge_end_voltage_mv": 1450,
        "discharge_cut_voltage_mv": 900,
        "charge_end_current_ma": 50,
        "num_cycles": 3,
        "cycle_mode": 0,
        "charge_resting_min": 10,
        "cut_temperature_c": 40,
        "cut_time_min": 600,
    },
    # Capacity test
    "Capacity Test (D>C)": {
        "battery_type": 3,
        "operation_mode": 1,  # Refresh
        "capacity_mah": 2000,
        "charge_current_ma": 1000,
        "discharge_current_ma": 500,
        "charge_end_voltage_mv": 1450,
        "discharge_cut_voltage_mv": 900,
        "charge_end_current_ma": 100,
        "num_cycles": 1,
        "cycle_mode": 2,  # D>C
        "charge_resting_min": 5,
        "cut_temperature_c": 45,
        "cut_time_min": 300,
    },
}


def ordered_preset_names() -> List[str]:
    """Built-in preset names for the quick-profile list: idle programs first."""
    idle = [n for n in BUILTIN_PRESETS if n.startswith("Idle")]
    rest = sorted(n for n in BUILTIN_PRESETS if not n.startswith("Idle"))
    return idle + rest


class ProfileManager:
    """Manages saving and loading of charging profiles."""

    def __init__(self):
        self.profiles: Dict[str, Dict[str, Any]] = {}
        self.load_profiles()

    def load_profiles(self):
        """Load profiles from file."""
        profiles_file = get_profiles_file()
        if profiles_file.exists():
            try:
                with open(profiles_file, 'r') as f:
                    self.profiles = json.load(f)
            except Exception:
                self.profiles = {}
        else:
            self.profiles = {}

    def save_profiles(self):
        """Save profiles to file."""
        profiles_file = get_profiles_file()
        try:
            with open(profiles_file, 'w') as f:
                json.dump(self.profiles, f, indent=2)
        except Exception as e:
            raise RuntimeError(f"Failed to save profiles: {e}")

    def get_all_profiles(self) -> Dict[str, Dict[str, Any]]:
        """Get all profiles (built-in + user)."""
        all_profiles = dict(BUILTIN_PRESETS)
        all_profiles.update(self.profiles)
        return all_profiles

    def get_user_profiles(self) -> Dict[str, Dict[str, Any]]:
        """Get user-created profiles only."""
        return dict(self.profiles)

    def get_profile(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a profile by name."""
        if name in self.profiles:
            return self.profiles[name]
        if name in BUILTIN_PRESETS:
            return BUILTIN_PRESETS[name]
        return None

    def save_profile(self, name: str, config):
        """Save a configuration as a profile."""
        self.profiles[name] = {
            "battery_type": config.battery_type,
            "operation_mode": config.operation_mode,
            "capacity_mah": config.capacity_mah,
            "charge_current_ma": config.charge_current_ma,
            "discharge_current_ma": config.discharge_current_ma,
            "charge_end_voltage_mv": config.charge_end_voltage_mv,
            "discharge_cut_voltage_mv": config.discharge_cut_voltage_mv,
            "charge_end_current_ma": config.charge_end_current_ma,
            "discharge_reduce_current_ma": config.discharge_reduce_current_ma,
            "num_cycles": config.num_cycles,
            "cycle_mode": config.cycle_mode,
            "charge_resting_min": config.charge_resting_min,
            "discharge_resting_min": config.discharge_resting_min,
            "peak_sense_mv": config.peak_sense_mv,
            "trickle_current_ma": config.trickle_current_ma,
            "trickle_time": config.trickle_time,
            "restart_voltage_mv": config.restart_voltage_mv,
            "cut_temperature_c": config.cut_temperature_c,
            "cut_time_min": config.cut_time_min,
        }
        self.save_profiles()

    def delete_profile(self, name: str) -> bool:
        """Delete a user profile."""
        if name in self.profiles:
            del self.profiles[name]
            self.save_profiles()
            return True
        return False

    def is_builtin(self, name: str) -> bool:
        """Check if a profile is built-in."""
        return name in BUILTIN_PRESETS

    def profile_to_config(self, name: str, slot_number: int = 0):
        """Convert a profile to a SlotConfig."""
        from mc3000_config import SlotConfig
        profile = self.get_profile(name)
        if not profile:
            return None

        return SlotConfig(
            slot_number=slot_number,
            battery_type=profile.get("battery_type", 0),
            operation_mode=profile.get("operation_mode", 0),
            capacity_mah=profile.get("capacity_mah", 2000),
            charge_current_ma=profile.get("charge_current_ma", 1000),
            discharge_current_ma=profile.get("discharge_current_ma", 500),
            charge_end_voltage_mv=profile.get("charge_end_voltage_mv", 1450),
            discharge_cut_voltage_mv=profile.get("discharge_cut_voltage_mv", 900),
            charge_end_current_ma=profile.get("charge_end_current_ma", 100),
            discharge_reduce_current_ma=profile.get("discharge_reduce_current_ma", 300),
            num_cycles=profile.get("num_cycles", 1),
            cycle_mode=profile.get("cycle_mode", 0),
            charge_resting_min=profile.get("charge_resting_min", 3),
            discharge_resting_min=profile.get("discharge_resting_min", 3),
            peak_sense_mv=profile.get("peak_sense_mv", 5),
            trickle_current_ma=profile.get("trickle_current_ma", 50),
            trickle_time=profile.get("trickle_time", 0),
            restart_voltage_mv=profile.get("restart_voltage_mv", 1000),
            cut_temperature_c=profile.get("cut_temperature_c", 45),
            cut_time_min=profile.get("cut_time_min", 120),
        )


class ProfileDialog(QDialog):
    """Dialog for managing and selecting profiles."""

    profileSelected = Signal(str)  # Emits profile name when selected

    def __init__(self, profile_manager: ProfileManager, parent=None):
        super().__init__(parent)
        self.profile_manager = profile_manager
        self.setWindowTitle("Charging Profiles")
        self.setMinimumSize(500, 400)
        self._setup_ui()
        self._refresh_list()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Profile list
        list_group = QGroupBox("Available Profiles")
        list_layout = QVBoxLayout(list_group)

        self.profile_list = QListWidget()
        self.profile_list.itemDoubleClicked.connect(self._on_load_clicked)
        self.profile_list.currentItemChanged.connect(self._on_selection_changed)
        list_layout.addWidget(self.profile_list)

        layout.addWidget(list_group)

        # Profile details
        details_group = QGroupBox("Profile Details")
        self.details_layout = QFormLayout(details_group)
        self.details_labels: Dict[str, QLabel] = {}

        for field in ["Battery Type", "Mode", "Capacity", "Charge Current",
                      "Discharge Current", "Cycles"]:
            label = QLabel("---")
            self.details_labels[field] = label
            self.details_layout.addRow(f"{field}:", label)

        layout.addWidget(details_group)

        # Buttons
        button_layout = QHBoxLayout()

        self.load_btn = QPushButton("Load Profile")
        self.load_btn.clicked.connect(self._on_load_clicked)
        self.load_btn.setEnabled(False)
        button_layout.addWidget(self.load_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        self.delete_btn.setEnabled(False)
        button_layout.addWidget(self.delete_btn)

        button_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _refresh_list(self):
        """Refresh the profile list."""
        self.profile_list.clear()

        # Add built-in profiles
        builtin_header = QListWidgetItem("── Built-in Presets ──")
        builtin_header.setFlags(Qt.NoItemFlags)
        self.profile_list.addItem(builtin_header)

        for name in sorted(BUILTIN_PRESETS.keys()):
            item = QListWidgetItem(f"  {name}")
            item.setData(Qt.UserRole, name)
            self.profile_list.addItem(item)

        # Add user profiles
        user_profiles = self.profile_manager.get_user_profiles()
        if user_profiles:
            user_header = QListWidgetItem("── User Profiles ──")
            user_header.setFlags(Qt.NoItemFlags)
            self.profile_list.addItem(user_header)

            for name in sorted(user_profiles.keys()):
                item = QListWidgetItem(f"  {name}")
                item.setData(Qt.UserRole, name)
                self.profile_list.addItem(item)

    def _on_selection_changed(self, current, previous):
        """Handle profile selection change."""
        if not current:
            self.load_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            return

        name = current.data(Qt.UserRole)
        if not name:
            self.load_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            return

        self.load_btn.setEnabled(True)
        self.delete_btn.setEnabled(not self.profile_manager.is_builtin(name))

        # Update details
        profile = self.profile_manager.get_profile(name)
        if profile:
            from mc3000_protocol import BATTERY_TYPES, OPERATION_MODES_LI, OPERATION_MODES_NI, OPERATION_MODES_ZN

            batt_type = profile.get("battery_type", 0)
            self.details_labels["Battery Type"].setText(BATTERY_TYPES.get(batt_type, "Unknown"))

            if batt_type <= 2:
                modes = OPERATION_MODES_LI
            elif batt_type in (3, 4, 6):
                modes = OPERATION_MODES_NI
            else:
                modes = OPERATION_MODES_ZN
            mode = profile.get("operation_mode", 0)
            self.details_labels["Mode"].setText(modes.get(mode, "Unknown"))

            self.details_labels["Capacity"].setText(f"{profile.get('capacity_mah', 0)} mAh")
            self.details_labels["Charge Current"].setText(f"{profile.get('charge_current_ma', 0)} mA")
            self.details_labels["Discharge Current"].setText(f"{profile.get('discharge_current_ma', 0)} mA")
            self.details_labels["Cycles"].setText(str(profile.get("num_cycles", 1)))

    def _on_load_clicked(self):
        """Handle load button click."""
        current = self.profile_list.currentItem()
        if current:
            name = current.data(Qt.UserRole)
            if name:
                self.profileSelected.emit(name)
                self.accept()

    def _on_delete_clicked(self):
        """Handle delete button click."""
        current = self.profile_list.currentItem()
        if not current:
            return

        name = current.data(Qt.UserRole)
        if not name or self.profile_manager.is_builtin(name):
            return

        reply = QMessageBox.question(
            self, "Delete Profile",
            f"Delete profile '{name}'?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.profile_manager.delete_profile(name)
            self._refresh_list()

    def get_selected_profile(self) -> Optional[str]:
        """Get the selected profile name."""
        current = self.profile_list.currentItem()
        if current:
            return current.data(Qt.UserRole)
        return None
