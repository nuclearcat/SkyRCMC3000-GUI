"""
MC3000 Protocol Constants and Data Parsing

Based on GNU DataExplorer reference implementation by Winfried Bruegmann.
Protocol constants and data structures for SKYRC MC3000 battery charger.
"""

from dataclasses import dataclass
from typing import Optional
import struct

# USB Device Constants
VENDOR_ID = 0x0000
PRODUCT_ID = 0x0001
INTERFACE_ID = 0x01
ENDPOINT_IN = 0x81
ENDPOINT_OUT = 0x01
DATA_SIZE = 64
TIMEOUT_MS = 1000

# BLE Constants
# BLE uses 20-byte packets (default ATT MTU) with checksum at byte 19
BLE_PACKET_SIZE = 20
BLE_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
BLE_CHARACTERISTIC_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
BLE_DEVICE_NAMES = ("SimpleBLEPeripheral", "Charger", "HitecCharger")

# Battery Types
BATTERY_TYPES = {
    0: "LiIon",
    1: "LiFe",
    2: "LiHV",
    3: "NiMH",
    4: "NiCd",
    5: "NiZn",
    6: "Eneloop",
    7: "RAM",
}

# Status Codes
STATUS_CODES = {
    0: "Standby",
    1: "Charging",
    2: "Discharging",
    3: "Resting",
    4: "Finished",
}

# Error Codes (status >= 0x80)
# Extracted from MC3000_Monitor_V1.06.exe via reverse engineering (see docs/RE_DETAILS.md)
ERROR_CODES = {
    0x80: "Input Low",           # Input voltage too low
    0x81: "Input High",          # Input voltage too high
    0x82: "MCP3424-1 Error",     # ADC chip 1 error
    0x83: "MCP3424-2 Error",     # ADC chip 2 error
    0x84: "Battery Break",       # Battery connection lost
    0x85: "Check Battery",       # Battery check failed
    0x86: "Capacity Cut",        # Capacity limit reached
    0x87: "Time Cut",            # Time limit reached
    0x88: "Int. Temp High",      # Internal temperature too high
    0x89: "Batt. Temp High",     # Battery temperature too high
    0x8A: "Over Load",           # Overload condition
    0x8B: "Batt. Reverse",       # Battery inserted backwards
    0x8C: "Unknown Error",       # Unknown error (AnKnow Error in original)
}


def get_error_description(error_code: int) -> str:
    """Get human-readable description for an error code."""
    if error_code < 0x80:
        return ""
    return ERROR_CODES.get(error_code, f"Unknown Error (0x{error_code:02X})")


# Operation Modes for Li batteries (LiIon, LiFe, LiHV)
OPERATION_MODES_LI = {
    0: "Charge",
    1: "Refresh",
    2: "Storage",
    3: "Discharge",
    4: "Cycle",
}

# Operation Modes for Ni batteries (NiMH, NiCd, Eneloop)
OPERATION_MODES_NI = {
    0: "Charge",
    1: "Refresh",
    2: "Break-in",
    3: "Discharge",
    4: "Cycle",
}

# Operation Modes for Zn/RAM batteries (NiZn, RAM)
OPERATION_MODES_ZN = {
    0: "Charge",
    1: "Refresh",
    2: "Discharge",
    3: "Cycle",
}

# Cycle Mode Names
CYCLE_MODES = {
    0: "C>D",
    1: "C>D>C",
    2: "D>C",
    3: "D>C>D",
}


def calculate_checksum(buffer: bytes, length: Optional[int] = None) -> int:
    """
    Calculate checksum for MC3000 protocol.
    Checksum is sum of bytes from index 0 to length-2, mod 256.
    """
    if length is None:
        length = len(buffer)
    return sum(buffer[:length]) % 256


def build_command(cmd_byte: int, param1: int = 0x00, param2: int = 0x00) -> bytes:
    """
    Build a 64-byte command packet.
    Format: 0x0F [length] [cmd] [param1] [param2] [checksum] 0xFF 0xFF (padded to 64 bytes)
    """
    base_cmd = bytearray([0x0F, 0x04, cmd_byte, param1, param2])
    checksum = sum(base_cmd[2:]) % 256
    base_cmd.append(checksum)
    base_cmd.extend([0xFF, 0xFF])
    # Pad to 64 bytes
    base_cmd.extend([0x00] * (DATA_SIZE - len(base_cmd)))
    return bytes(base_cmd)


# Pre-built Commands
def cmd_query_slot(slot: int) -> bytes:
    """Query slot settings/configuration for a slot (0-3)."""
    return build_command(0x5F, 0x00, slot)


def cmd_query_slot_settings(slot: int) -> bytes:
    """Query slot settings/configuration for a slot (0-3). Alias for cmd_query_slot."""
    return build_command(0x5F, 0x00, slot)


def cmd_take_mtu(slot: int) -> bytes:
    """Take MTU data for a slot (0-3)."""
    return build_command(0x55, 0x00, slot)


def cmd_get_system_settings() -> bytes:
    """Get system settings."""
    return build_command(0x5A, 0x00, 0x00)


def cmd_start_processing() -> bytes:
    """Start processing command."""
    base_cmd = bytearray([0x0F, 0x03, 0x05, 0x00])
    checksum = sum(base_cmd[2:]) % 256
    base_cmd.append(checksum)
    base_cmd.extend([0xFF, 0xFF, 0xFF])
    base_cmd.extend([0x00] * (DATA_SIZE - len(base_cmd)))
    return bytes(base_cmd)


def cmd_stop_processing() -> bytes:
    """Stop processing command."""
    base_cmd = bytearray([0x0F, 0x03, 0xFE, 0x00])
    checksum = sum(base_cmd[2:]) % 256
    base_cmd.append(checksum)
    base_cmd.extend([0xFF, 0xFF, 0xFF])
    base_cmd.extend([0x00] * (DATA_SIZE - len(base_cmd)))
    return bytes(base_cmd)


def parse_signed_short(high_byte: int, low_byte: int) -> int:
    """Parse two bytes as a signed 16-bit integer (big-endian in Java code)."""
    value = (high_byte << 8) | low_byte
    if value >= 32768:
        value -= 65536
    return value


@dataclass
class SlotData:
    """Parsed data from a single charger slot."""
    slot_number: int
    battery_type: int
    battery_type_name: str
    operation_mode: int
    operation_mode_name: str
    work_time_seconds: int  # Time elapsed/remaining in seconds
    status: int
    status_name: str
    voltage_mv: int
    current_ma: int
    capacity_mah: int
    temperature_c: float      # Battery temperature
    internal_temp_c: float    # Internal/charger temperature
    is_error: bool
    error_code: Optional[int]
    # Extra values from the USB 0x55 response (verified against the SkyRC app).
    # None means "not provided by this transport".
    internal_resistance_mohm: Optional[int] = None
    energy_mwh: Optional[int] = None
    power_mw: Optional[int] = None
    average_voltage_mv: Optional[int] = None

    @property
    def voltage_v(self) -> float:
        """Voltage in Volts."""
        return self.voltage_mv / 1000.0

    @property
    def current_a(self) -> float:
        """Current in Amps."""
        return self.current_ma / 1000.0

    @property
    def power_w(self) -> float:
        """Power in Watts. Uses the value reported by the charger if available,
        otherwise voltage × current."""
        if self.power_mw is not None:
            return self.power_mw / 1000.0
        return self.voltage_v * self.current_a

    @property
    def energy_wh(self) -> Optional[float]:
        """Accumulated energy of the current/last run in Wh, if available."""
        if self.energy_mwh is None:
            return None
        return self.energy_mwh / 1000.0

    @property
    def average_voltage_v(self) -> Optional[float]:
        """Average voltage of the current/last run in V, if available."""
        if self.average_voltage_mv is None:
            return None
        return self.average_voltage_mv / 1000.0

    @property
    def work_time_formatted(self) -> str:
        """Work time as HH:MM:SS string."""
        hours = self.work_time_seconds // 3600
        minutes = (self.work_time_seconds % 3600) // 60
        seconds = self.work_time_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def get_operation_mode_name(battery_type: int, mode: int) -> str:
    """Get operation mode name based on battery type."""
    if battery_type <= 2:  # Li batteries
        return OPERATION_MODES_LI.get(mode, f"Unknown({mode})")
    elif battery_type in (3, 4, 6):  # Ni batteries
        return OPERATION_MODES_NI.get(mode, f"Unknown({mode})")
    elif battery_type in (5, 7):  # Zn/RAM batteries
        return OPERATION_MODES_ZN.get(mode, f"Unknown({mode})")
    return f"Unknown({mode})"


def parse_slot_data(data: bytes, slot_number: int) -> Optional[SlotData]:
    """
    Parse slot data from a 64-byte response buffer.

    Protocol based on RE of MC3000_Monitor_V1.06.exe (see docs/RE_DETAILS.md)
    with corrections from DataExplorer and real hardware testing.
    Note: hidapi strips Report ID, so offsets are shifted by -1 from raw protocol.

    Data format (0-indexed, after Report ID stripped):
    - Byte 0: Command echo (0x55)
    - Byte 1: Slot number (0-3)
    - Byte 2: Battery type (0-6)
    - Byte 3: Work mode (0-4)
    - Byte 4: Reserved
    - Byte 5: Work status (0-4 normal, 0x80+ error)
    - Bytes 6-7: Work time (seconds, big-endian)
    - Bytes 8-9: Voltage (mV, big-endian)
    - Bytes 10-11: Current (mA, big-endian)
    - Bytes 12-13: Capacity (mAh, big-endian)
    - Bytes 14-15: Battery temperature (0.1°C, big-endian, masked with 0x7FFF)
    - Bytes 16-17: Internal resistance (mOhm, big-endian). Verified: identical to
                   "Batt IR" in the SkyRC app. Keeps the value of the last cell
                   when the slot is empty (status 0).
    - Bytes 18-19: Internal/charger temperature (0.1°C, big-endian)
    - Bytes 20-21: Energy of the current/last run (mWh, big-endian)
    - Bytes 22-23: Power (mW, big-endian)
    - Byte 24: Capacity decimal
    - Bytes 25-26: Average voltage of the current/last run (mV, big-endian)
    - Byte 27: Unknown (global value, changes over time)
    """
    if len(data) < 25:
        return None
    # Reject packets that are not a 0x55 status response (e.g. stale responses
    # to other commands still waiting in the HID input queue).
    if data[0] != 0x55:
        return None

    battery_type = data[2] & 0xFF
    operation_mode = data[3] & 0xFF
    # Byte 4 is Reserved per MC3000 Monitor protocol
    status = data[5] & 0xFF

    # Check for error status
    is_error = status >= 0x80
    error_code = status if is_error else None

    # Work time in seconds (bytes 6-7, big-endian)
    work_time_seconds = (data[6] << 8) | data[7]

    # Parse measurements - byte order: first byte is high, second is low
    voltage_mv = parse_signed_short(data[8], data[9])
    current_ma = parse_signed_short(data[10], data[11])
    capacity_mah = parse_signed_short(data[12], data[13])

    # Battery temperature with 0x7FFF mask (high bit may be a flag)
    batt_temp_raw = parse_signed_short(data[14], data[15]) & 0x7FFF
    # Internal/charger temperature (bytes 18-19)
    # Note: RE_DETAILS says 16-17, but DataExplorer and real hardware testing shows 18-19
    internal_temp_raw = parse_signed_short(data[18], data[19])

    # Capacity decimal (byte 24, 0.01 mAh units per RE_DETAILS)
    if len(data) > 24:
        capacity_decimal = data[24] & 0xFF
        # Add decimal portion: value is in 0.01 mAh units
        capacity_mah += int(capacity_decimal * 0.01)

    # Convert temperatures (raw is in 0.1°C units)
    temperature_c = batt_temp_raw / 10.0
    internal_temp_c = internal_temp_raw / 10.0

    # Extra values (see docstring)
    internal_resistance_mohm = (data[16] << 8) | data[17]
    if internal_resistance_mohm == 0xFFFF:  # no valid measurement (e.g. finished)
        internal_resistance_mohm = None
    energy_mwh = (data[20] << 8) | data[21]
    power_mw = (data[22] << 8) | data[23]
    average_voltage_mv = ((data[25] << 8) | data[26]) if len(data) > 26 else None

    # Get status name
    if is_error:
        error_desc = ERROR_CODES.get(status, None)
        if error_desc:
            status_name = error_desc
        else:
            status_name = f"Error (0x{status:02X})"
    else:
        status_name = STATUS_CODES.get(status, f"Unknown({status})")

    # Get battery type name
    battery_type_name = BATTERY_TYPES.get(battery_type, f"Unknown({battery_type})")

    # Get operation mode name
    operation_mode_name = get_operation_mode_name(battery_type, operation_mode)

    return SlotData(
        slot_number=slot_number,
        battery_type=battery_type,
        battery_type_name=battery_type_name,
        operation_mode=operation_mode,
        operation_mode_name=operation_mode_name,
        work_time_seconds=work_time_seconds,
        status=status,
        status_name=status_name,
        voltage_mv=voltage_mv,
        current_ma=current_ma,
        capacity_mah=capacity_mah,
        temperature_c=temperature_c,
        internal_temp_c=internal_temp_c,
        is_error=is_error,
        error_code=error_code,
        internal_resistance_mohm=internal_resistance_mohm,
        energy_mwh=energy_mwh,
        power_mw=power_mw,
        average_voltage_mv=average_voltage_mv,
    )


@dataclass
class SlotSettings:
    """Parsed slot configuration/settings from MC3000."""
    slot_number: int
    is_busy: bool
    battery_type: int
    operation_mode: int
    capacity_mah: int
    charge_current_ma: int
    discharge_current_ma: int
    discharge_cut_voltage_mv: int
    charge_end_voltage_mv: int
    charge_end_current_ma: int
    discharge_reduce_current_ma: int
    num_cycles: int
    charge_resting_min: int
    cycle_mode: int
    peak_sense_mv: int
    trickle_current_ma: int
    restart_voltage_mv: int
    cut_temperature_c: int
    cut_time_min: int
    # FW 1.12+ fields
    discharge_resting_min: int = 0
    trickle_time: int = 0


def parse_slot_settings(data: bytes, firmware_version: int = 123) -> Optional[SlotSettings]:
    """
    Parse slot settings from a 64-byte response buffer (0x5F command response).

    Data format (0-indexed):
    - Byte 0: 0x5F (command echo)
    - Byte 1: slot number
    - Byte 2: busy tag (0x01 = busy)
    - Byte 3: battery type
    - Byte 4: operation mode
    - Bytes 5-6: capacity (mAh)
    - Bytes 7-8: charge current (mA)
    - Bytes 9-10: discharge current (mA)
    - Bytes 11-12: discharge cut voltage (mV)
    - Bytes 13-14: charge end voltage (mV)
    - Bytes 15-16: charge end current (mA)
    - Bytes 17-18: discharge reduce current (mA)
    - Byte 19: number of cycles
    - Byte 20: charge resting time (min)
    - Byte 21: cycle mode
    - Byte 22: peak sense voltage (mV, for Ni)
    - Byte 23: trickle current (mA)
    - Bytes 24-25: restart voltage (mV)
    - Byte 26: cut temperature (°C)
    - Bytes 27-28: cut time (min)
    - Byte 29: temperature unit
    - Byte 30: trickle time (FW 1.12+)
    - Byte 31: discharge resting time (FW 1.12+)
    """
    if len(data) < 30:
        return None

    # Verify command echo
    if data[0] != 0x5F:
        return None

    def parse_uint16(high: int, low: int) -> int:
        """Parse 16-bit value from big-endian byte pair."""
        return (high << 8) | low

    slot_number = data[1]
    is_busy = data[2] == 0x01
    battery_type = data[3]
    operation_mode = data[4]
    capacity_mah = parse_uint16(data[5], data[6])
    charge_current_ma = parse_uint16(data[7], data[8])
    discharge_current_ma = parse_uint16(data[9], data[10])
    discharge_cut_voltage_mv = parse_uint16(data[11], data[12])
    charge_end_voltage_mv = parse_uint16(data[13], data[14])
    charge_end_current_ma = parse_uint16(data[15], data[16])
    discharge_reduce_current_ma = parse_uint16(data[17], data[18])
    num_cycles = data[19]
    charge_resting_min = data[20]
    cycle_mode = data[21]
    peak_sense_mv = data[22]
    trickle_current_ma = data[23]
    restart_voltage_mv = parse_uint16(data[24], data[25])
    cut_temperature_c = data[26]
    cut_time_min = parse_uint16(data[27], data[28])

    # FW 1.12+ fields
    discharge_resting_min = 0
    trickle_time = 0
    if firmware_version > 111 and len(data) > 31:
        trickle_time = data[30]
        discharge_resting_min = data[31]

    return SlotSettings(
        slot_number=slot_number,
        is_busy=is_busy,
        battery_type=battery_type,
        operation_mode=operation_mode,
        capacity_mah=capacity_mah,
        charge_current_ma=charge_current_ma,
        discharge_current_ma=discharge_current_ma,
        discharge_cut_voltage_mv=discharge_cut_voltage_mv,
        charge_end_voltage_mv=charge_end_voltage_mv,
        charge_end_current_ma=charge_end_current_ma,
        discharge_reduce_current_ma=discharge_reduce_current_ma,
        num_cycles=num_cycles,
        charge_resting_min=charge_resting_min,
        cycle_mode=cycle_mode,
        peak_sense_mv=peak_sense_mv,
        trickle_current_ma=trickle_current_ma,
        restart_voltage_mv=restart_voltage_mv,
        cut_temperature_c=cut_temperature_c,
        cut_time_min=cut_time_min,
        discharge_resting_min=discharge_resting_min,
        trickle_time=trickle_time,
    )


@dataclass
class SystemSettings:
    """Parsed system settings from MC3000."""
    current_slot_number: int
    slot_programs: tuple  # (slot1, slot2, slot3, slot4)
    user_interface_mode: int
    temperature_unit: int  # 0=Celsius, 1=Fahrenheit
    beep_tone: int
    lcd_off_time: int
    min_voltage: int
    firmware_major: int
    firmware_minor: int
    hardware_version: int

    @property
    def firmware_version(self) -> str:
        return f"{self.firmware_major}.{self.firmware_minor:02d}"

    @property
    def firmware_version_int(self) -> int:
        return self.firmware_major * 100 + self.firmware_minor

    @property
    def temperature_unit_str(self) -> str:
        return "°F" if self.temperature_unit == 1 else "°C"


def parse_system_settings(data: bytes) -> Optional[SystemSettings]:
    """
    Parse system settings from a 64-byte response buffer.

    Data format (0-indexed):
    - Byte 2: Current slot number
    - Byte 3-6: Slot program numbers (1-4)
    - Byte 7: User interface mode
    - Byte 8: Temperature unit (0=C, 1=F)
    - Byte 9: Beep tone
    - Byte 10-13: Hide flags for battery types
    - Byte 14: LCD off time
    - Byte 15: Min voltage
    - Bytes 16-31: Machine ID (including FW version at 27-28, HW at 29)
    """
    if len(data) < 33:
        return None

    current_slot = data[2] & 0xFF
    slot_programs = (
        (data[3] & 0xFF) + 1,
        (data[4] & 0xFF) + 1,
        (data[5] & 0xFF) + 1,
        (data[6] & 0xFF) + 1,
    )
    ui_mode = data[7] & 0xFF
    temp_unit = data[8] & 0xFF
    beep = data[9] & 0xFF
    lcd_off = data[14] & 0xFF
    min_volt = data[15] & 0xFF

    # Firmware version is in machine ID area (bytes 27-28 relative, which is 16+11 and 16+12)
    fw_major = data[27] & 0xFF
    fw_minor = data[28] & 0xFF
    hw_version = data[29] & 0xFF

    return SystemSettings(
        current_slot_number=current_slot,
        slot_programs=slot_programs,
        user_interface_mode=ui_mode,
        temperature_unit=temp_unit,
        beep_tone=beep,
        lcd_off_time=lcd_off,
        min_voltage=min_volt,
        firmware_major=fw_major,
        firmware_minor=fw_minor,
        hardware_version=hw_version,
    )


# =============================================================================
# BLE Protocol Functions
# =============================================================================


def build_ble_command(cmd: int, channel: int = 0, channel_mask: int = 0) -> bytes:
    """
    Build a 20-byte BLE command packet.

    Args:
        cmd: Command byte (0x55 for slot data, 0x57 for version, 0x61 for basic data)
        channel: Channel number (0-3) for 0x55 command
        channel_mask: Channel bitmask for other commands

    Returns:
        20-byte command packet with checksum at byte 19
    """
    buf = bytearray(BLE_PACKET_SIZE)  # 20 bytes
    buf[0] = 0x0F  # Start byte
    buf[1] = cmd   # Command
    if cmd == 0x55:
        buf[2] = channel
    else:
        buf[2] = channel_mask
    # Checksum is sum of bytes 0..18, masked to 0xFF, stored at byte 19
    buf[19] = sum(buf[:19]) % 256
    return bytes(buf)


def cmd_ble_take_mtu(slot: int) -> bytes:
    """Build BLE command to query slot data (0x55)."""
    return build_ble_command(0x55, channel=slot)


def cmd_ble_get_version() -> bytes:
    """Build BLE command to get version info (0x57)."""
    return build_ble_command(0x57)


def cmd_ble_get_basic_data(channel_mask: int = 0x0F) -> bytes:
    """Build BLE command to get basic system data (0x61)."""
    return build_ble_command(0x61, channel_mask=channel_mask)


def parse_ble_slot_data(data: bytes, slot_number: int) -> Optional[SlotData]:
    """
    Parse BLE slot data from a 20-byte response.

    BLE Slot Data Format (0-indexed, 20 bytes total):
    - Byte 0: 0x0F (start byte)
    - Byte 1: 0x55 (command echo)
    - Byte 2: channel (0-3)
    - Byte 3: battery type
    - Byte 4: mode
    - Byte 5: cycle count
    - Byte 6: status
    - Bytes 7-8: time (seconds, big-endian)
    - Bytes 9-10: voltage (mV, big-endian)
    - Bytes 11-12: current (mA, big-endian, signed)
    - Bytes 13-14: capacity (mAh, big-endian)
    - Byte 15: temperature (integer in current unit)
    - Bytes 16-17: internal resistance (mOhm, big-endian)
    - Byte 18: LED bitmask
    - Byte 19: checksum

    Args:
        data: 20-byte response from BLE device
        slot_number: Slot number (0-3)

    Returns:
        SlotData object or None on failure
    """
    if len(data) < BLE_PACKET_SIZE:
        return None

    # Verify start byte and command
    if data[0] != 0x0F or data[1] != 0x55:
        return None

    # Verify checksum (sum of bytes 0..18 mod 256)
    expected_checksum = sum(data[:19]) % 256
    if data[19] != expected_checksum:
        return None

    battery_type = data[3] & 0xFF
    operation_mode = data[4] & 0xFF
    # cycle_count = data[5] & 0xFF  # Available but not used in SlotData
    status = data[6] & 0xFF

    # Check for error status
    is_error = status >= 0x80
    error_code = status if is_error else None

    # Work time in seconds (bytes 7-8, big-endian)
    work_time_seconds = (data[7] << 8) | data[8]

    # Voltage in mV (bytes 9-10, big-endian)
    voltage_mv = (data[9] << 8) | data[10]

    # Current in mA (bytes 11-12, big-endian, signed)
    current_ma = parse_signed_short(data[11], data[12])

    # Capacity in mAh (bytes 13-14, big-endian)
    capacity_mah = (data[13] << 8) | data[14]

    # Temperature in integer (byte 15)
    temperature_c = float(data[15] & 0xFF)

    # Internal resistance in mOhm (bytes 16-17)
    internal_resistance = (data[16] << 8) | data[17]
    if internal_resistance == 0xFFFF:
        internal_resistance = None

    # Get status name
    if is_error:
        error_desc = ERROR_CODES.get(status, None)
        if error_desc:
            status_name = error_desc
        else:
            status_name = f"Error (0x{status:02X})"
    else:
        status_name = STATUS_CODES.get(status, f"Unknown({status})")

    # Get battery type name
    battery_type_name = BATTERY_TYPES.get(battery_type, f"Unknown({battery_type})")

    # Get operation mode name
    operation_mode_name = get_operation_mode_name(battery_type, operation_mode)

    return SlotData(
        slot_number=slot_number,
        battery_type=battery_type,
        battery_type_name=battery_type_name,
        operation_mode=operation_mode,
        operation_mode_name=operation_mode_name,
        work_time_seconds=work_time_seconds,
        status=status,
        status_name=status_name,
        voltage_mv=voltage_mv,
        current_ma=current_ma,
        capacity_mah=capacity_mah,
        temperature_c=temperature_c,
        internal_temp_c=temperature_c,  # BLE doesn't provide separate internal temp
        is_error=is_error,
        error_code=error_code,
        internal_resistance_mohm=internal_resistance,
    )


@dataclass
class BLEBasicData:
    """Parsed basic data from BLE 0x61 command response."""
    channel_status: tuple  # Status for each channel (4 values)
    firmware_version: str
    hardware_version: int


def parse_ble_basic_data(data: bytes) -> Optional[BLEBasicData]:
    """
    Parse BLE basic data from 0x61 command response.

    Format is device-specific and may vary.

    Args:
        data: Response bytes from BLE device

    Returns:
        BLEBasicData object or None on failure
    """
    if len(data) < BLE_PACKET_SIZE:
        return None

    if data[0] != 0x0F or data[1] != 0x61:
        return None

    # Parse channel status (bytes 3-6)
    channel_status = tuple(data[i] & 0xFF for i in range(3, 7))

    # Firmware/hardware info may be at different offsets
    # This is a placeholder - actual format may need adjustment
    fw_major = data[7] & 0xFF if len(data) > 7 else 1
    fw_minor = data[8] & 0xFF if len(data) > 8 else 0
    hw_version = data[9] & 0xFF if len(data) > 9 else 0

    return BLEBasicData(
        channel_status=channel_status,
        firmware_version=f"{fw_major}.{fw_minor:02d}",
        hardware_version=hw_version,
    )


@dataclass
class BLEVersionInfo:
    """Parsed version info from BLE 0x57 command response."""
    firmware_major: int
    firmware_minor: int
    hardware_version: int

    @property
    def firmware_version(self) -> str:
        return f"{self.firmware_major}.{self.firmware_minor:02d}"


def parse_ble_version(data: bytes) -> Optional[BLEVersionInfo]:
    """
    Parse BLE version info from 0x57 command response.

    According to BLE_PROTOCOL.md:
    - Firmware version: bytes 14-15 (major.minor)
    - Hardware version: byte 16

    Args:
        data: Response bytes from BLE device

    Returns:
        BLEVersionInfo object or None on failure
    """
    if len(data) < BLE_PACKET_SIZE:
        return None

    if data[0] != 0x0F or data[1] != 0x57:
        return None

    # Version info per BLE_PROTOCOL.md - bytes 14-16
    fw_major = data[14] & 0xFF
    fw_minor = data[15] & 0xFF
    hw_version = data[16] & 0xFF

    return BLEVersionInfo(
        firmware_major=fw_major,
        firmware_minor=fw_minor,
        hardware_version=hw_version,
    )
