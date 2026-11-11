# SKYRC MC3000 Battery Charger GUI

[![PyPI version](https://badge.fury.io/py/skyrc-mc3000-gui.svg)](https://pypi.org/project/skyrc-mc3000-gui/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Cross-platform Python GUI for monitoring and controlling the SKYRC MC3000 battery charger.

## Changes in 1.8.0

- **Internal resistance, energy, average voltage**: parsed from the USB `0x55`
  realtime packet (bytes 16-17 mΩ, 20-21 mWh, 22-23 mW, 25-26 mV; verified
  against the SkyRC app) and shown per slot, in the graphs and in the CSV export.
- **No more freezing**: USB polling runs in a background thread; every query
  waits for the matching answer (command echo + slot), so stale reports can no
  longer end up in the wrong slot.
- **Bluetooth hint**: while the SkyRC app shows live data via Bluetooth the
  charger stops answering USB. The GUI now keeps the last values (greyed out)
  and says so in the status bar instead of hanging.
- **Full-run graphs**: history covers up to 48 h per slot (peak downsampling
  keeps it fast), restarts automatically when a new program starts, time axis
  in h:mm:ss, shared between "All Slots" and the slot tabs.
- **CSV export** of all slots ("Export CSV..." next to the graph tabs).
- **Configure dialog**: marks slots that could not be read ("not read") and
  warns before applying them; restart voltage values outside the manual range
  are labelled "= OFF"; raw device values are no longer clamped by the spin
  box ranges (which used to change them silently on "Apply").
- Window title shows the installed package version.

## Features

- Real-time monitoring of all 4 charging slots
- Voltage, current, capacity, temperature, resistance, power, energy display
- Slot configuration with battery type selection
- Profile management (save/load charging profiles)
- Charging graphs with history
- Backup and restore slot configurations
- Color-coded status indicators
- Cross-platform (Windows, macOS, Linux)

## Screenshots

![Charging Mode](screenshots/charger1.png)
*Real-time monitoring with voltage graphs during charging*

![Refresh Mode](screenshots/charger2.png)
*Discharge curves during refresh/analyze mode*

## Installation

### From PyPI

```bash
pip install skyrc-mc3000-gui
```

### From Source

```bash
git clone https://github.com/nuclearcat/SkyRCMC3000-GUI.git
cd SkyRCMC3000-GUI
pip install .
```

### Linux Dependencies

On Linux, you also need libhidapi:
```bash
# Debian/Ubuntu
sudo apt install libhidapi-hidraw0

# Fedora
sudo dnf install hidapi

# Arch
sudo pacman -S hidapi
```

## Usage

### Run the GUI

```bash
mc3000-gui
```

Or run directly from source:
```bash
python main.py
```

### Command-line Tools

```bash
# Backup/restore tool
mc3000-backup --help
```

## Linux USB Access

To access the MC3000 without root, create `/etc/udev/rules.d/99-mc3000.rules`:

```
SUBSYSTEM=="usb", ATTR{idVendor}=="0000", ATTR{idProduct}=="0001", MODE="0666"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0000", ATTRS{idProduct}=="0001", MODE="0666"
```

Then reload:
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

## Documentation

- [Protocol Documentation](docs/protocol.rst) - MC3000 USB HID protocol details
- [Protocol Notes](docs/protocol_notes.md) - Additional protocol observations

## Example Code

### Reading Slot Data

```python
from mc3000_usb import MC3000USB
from mc3000_protocol import parse_slot_data

# Connect to charger
usb = MC3000USB()
usb.connect()

# Get real-time data for slot 0
data = usb.get_slot_data(0)
if data:
    print(f"Voltage: {data.voltage_v:.3f} V")
    print(f"Current: {data.current_ma} mA")
    print(f"Capacity: {data.capacity_mah} mAh")
    print(f"Temperature: {data.temperature_c:.1f} C")

usb.disconnect()
```

### Reading Slot Configuration

```python
from mc3000_usb import MC3000USB

usb = MC3000USB()
usb.connect()

# Get settings for slot 0
settings = usb.get_slot_settings(0)
if settings:
    print(f"Battery Type: {settings.battery_type}")
    print(f"Capacity: {settings.capacity_mah} mAh")
    print(f"Charge Current: {settings.charge_current_ma} mA")

usb.disconnect()
```

### Using Profiles

```python
from mc3000_profiles import ProfileManager

pm = ProfileManager()

# List available profiles
for name in pm.list_profiles():
    print(f"Profile: {name}")

# Get a profile
profile = pm.get_profile("NiMH AA 2000mAh")
```

## Development

### Install Development Dependencies

```bash
pip install -e ".[dev]"
```

### Run Tests

```bash
pytest
```

## Known Limitations

- **Starting after "Finished"**: When a slot completes charging, you may need to press a button on the charger to clear the finished state before starting a new operation via USB.
- See [Protocol Notes](docs/protocol_notes.md) for more details.

## Firmware Updates (Linux)

The official SKYRC firmware update tool (`MC3000_Firmware_Update__V1.25.exe`) is a Windows application. However, Linux users have reported success running it under Wine with .NET Framework 4.5.2 installed:

```bash
winetricks dotnet452
wine MC3000_Firmware_Update__V1.25.exe
```

**Warning:** Firmware updates carry inherent risk. Proceed at your own discretion. Results may vary depending on your Wine configuration and system setup.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Links

- [GitHub Repository](https://github.com/nuclearcat/SkyRCMC3000-GUI)
- [PyPI Package](https://pypi.org/project/skyrc-mc3000-gui/)
- [Issue Tracker](https://github.com/nuclearcat/SkyRCMC3000-GUI/issues)

## Acknowledgments

Protocol implementation based on [GNU DataExplorer](https://www.nongnu.org/dataexplorer/) by Winfried Bruegmann.
