import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("pyqtgraph")

from mc3000_protocol import SlotData
from mc3000_graphs import SlotDataHistory


def make(status, cap=100, ir=12, t=10):
    return SlotData(
        slot_number=0, battery_type=0, battery_type_name="LiIon",
        operation_mode=1, operation_mode_name="Refresh",
        work_time_seconds=t, status=status, status_name="x",
        voltage_mv=4000, current_ma=1000, capacity_mah=cap,
        temperature_c=25.0, internal_temp_c=30.0,
        is_error=False, error_code=None,
        internal_resistance_mohm=ir, energy_mwh=1500, power_mw=4000,
        average_voltage_mv=3900,
    )


def test_standby_not_recorded():
    h = SlotDataHistory()
    assert not h.add_data(make(0))
    assert len(h) == 0


def test_finished_recorded_once():
    h = SlotDataHistory()
    for _ in range(3):
        h.add_data(make(2))
    for _ in range(5):
        h.add_data(make(4))
    assert len(h) == 4


def test_new_start_resets_history():
    h = SlotDataHistory()
    for _ in range(3):
        h.add_data(make(1))
    h.add_data(make(4))
    h.add_data(make(1))
    assert len(h) == 1


def test_growth_and_cap():
    h = SlotDataHistory(max_points=5000)
    for i in range(6000):
        h.add_data(make(1, cap=i))
    assert len(h) <= 5000
    arr = h.get_arrays()
    assert arr["capacity"][-1] == 5999
    assert arr["resistance"][-1] == 12
    assert abs(arr["energy"][-1] - 1.5) < 1e-9
