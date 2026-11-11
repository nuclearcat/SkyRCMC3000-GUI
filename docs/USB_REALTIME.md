# USB realtime data (command 0x55)

Verified on an MC3000 (firmware 1.27, hardware 22) by comparing raw USB
reports with the values shown in the SkyRC app (November 2026).

Request: `build_command(0x55, 0x00, slot)`. Offsets below are in the
64-byte response **without** the HID report ID (hidapi strips it).
All 16-bit values are big-endian.

| Byte  | Content                                   | Notes |
|-------|-------------------------------------------|-------|
| 0     | `0x55` (command echo)                     | used to validate the answer |
| 1     | slot (0-3)                                | used to validate the answer |
| 2     | battery type                              | 0 LiIon, 1 LiFe, 2 LiHV, 3 NiMH, 4 NiCd, 5 NiZn, 6 Eneloop, 7 RAM |
| 3     | operation mode                            | depends on chemistry |
| 5     | status                                    | 0 standby/empty, 1 charging, 2 discharging, 3 resting, 4 finished, >= 0x80 error (e.g. 0x87 Time Cut) |
| 6-7   | work time (s)                             | |
| 8-9   | voltage (mV)                              | NiMH: not updated while current flows, only in pauses |
| 10-11 | current (mA)                              | |
| 12-13 | capacity (mAh)                            | |
| 14-15 | battery temperature (0.1 °C, `& 0x7FFF`)  | |
| 16-17 | internal resistance (mΩ)                  | same value as the app; `0xFFFF` = no measurement; NiMH after very short runs: implausible values (also in the app) |
| 18-19 | charger temperature (0.1 °C)              | |
| 20-21 | energy (mWh)                              | |
| 22-23 | power (mW)                                | |
| 24    | capacity decimal                          | |
| 25-26 | average voltage (mV)                      | |
| 27    | unknown, changes globally                 | not a fan/BT flag |

An empty slot keeps the values of the last run (status 0). In standby the
charger does not measure every cell: a NiMH cell can show 0.000 V until the
program starts.

## Behaviour notes

- **SkyRC app live view blocks USB.** While the app shows live data via
  Bluetooth (home screen with bars or the detail view), the charger does not
  answer USB queries at all. Pages without live data (e.g. "Program") do not
  block. The GUI keeps the last values greyed out and shows a hint.
- **Start (0x05) has no slot parameter.** It starts every idle slot that holds
  a cell. Slots that are "Finished" or stopped with an error ignore it until
  they are reset; stop (0xFE) resets all slots to standby, the charger then
  picks up the slot program. The GUI does stop + start automatically when
  nothing is running.
- **Keeping a slot idle:** Li chemistries check the target voltage before
  charging, so LiIon Charge with target 2.50 V does not charge any healthy
  cell (0 mA, "Time Cut" after the 1 min cut-off time). Ni chemistries do not
  check it: NiMH charges ~20 s at the set current, then ~40 s at 10 mA, then
  Time Cut (< 1 mAh).
- Commands 0x56, 0x57 and 0x61 (BLE) get no answer over USB. Never send 0x88
  (firmware/bootloader mode).
