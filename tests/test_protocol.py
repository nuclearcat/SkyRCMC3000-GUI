"""Tests for USB 0x55 parsing, using packets captured from a real MC3000
(firmware 1.27, hardware 22) and cross-checked against the SkyRC app."""

from mc3000_protocol import parse_slot_data


def pkt(hexstr: str) -> bytes:
    data = bytes.fromhex(hexstr.replace(" ", ""))
    return data + bytes(64 - len(data))


# Slot 1 discharging Li-Ion at 1 A (app showed Batt IR 27 mOhm)
DISCHARGING = pkt("55 00 00 01 00 02 0a 4e 0f 8a 03 e8 02 d9 01 2b 00 1b 01 7b 0b 83 0f 8f 07 0f c7 e1 00 00 00 00")
# Slot 2 finished (app showed Batt IR 12 mOhm)
FINISHED = pkt("55 01 00 01 00 04 19 dc 10 4c 00 00 0f f9 01 2b 00 0c 01 7b 3c 89 00 00 06 0e 45 e1 00 00 00 00")
# Slot 4 with the cell removed: live values 0, last-run values kept
EMPTY = pkt("55 03 00 01 00 00 19 9c 00 00 00 00 10 21 01 12 00 0c 01 74 3d 24 00 00 00 0e 48 61 00 00 00 00")


def test_discharging_values():
    d = parse_slot_data(DISCHARGING, 0)
    assert d.status == 2
    assert d.voltage_mv == 3978
    assert d.current_ma == 1000
    assert d.capacity_mah == 729
    assert d.temperature_c == 29.9
    assert d.internal_temp_c == 37.9
    assert d.internal_resistance_mohm == 27
    assert d.energy_mwh == 2947
    assert d.power_mw == 3983
    assert abs(d.power_w - 3.983) < 1e-9
    assert d.average_voltage_mv == 4039


def test_finished_values():
    d = parse_slot_data(FINISHED, 1)
    assert d.status == 4
    assert d.capacity_mah == 4089
    assert d.internal_resistance_mohm == 12
    assert d.energy_mwh == 15497
    assert d.power_mw == 0
    assert d.average_voltage_mv == 3653


def test_empty_slot_keeps_last_run():
    d = parse_slot_data(EMPTY, 3)
    assert d.status == 0
    assert d.voltage_mv == 0
    assert d.current_ma == 0
    assert d.capacity_mah == 4129
    assert d.internal_resistance_mohm == 12
    assert d.energy_mwh == 15652


def test_rejects_non_status_packet():
    other = bytearray(FINISHED)
    other[0] = 0x5F
    assert parse_slot_data(bytes(other), 1) is None


def test_resistance_ffff_is_invalid():
    data = bytearray(FINISHED)
    data[16] = 0xFF
    data[17] = 0xFF
    d = parse_slot_data(bytes(data), 1)
    assert d.internal_resistance_mohm is None
