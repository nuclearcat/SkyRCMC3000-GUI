import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mc3000_protocol import SlotData, SlotSettings
from mc3000_start import plan_start, STARTS, BLOCKED, EMPTY, RUNNING


def d(status, mv, slot=0):
    return SlotData(
        slot_number=slot, battery_type=0, battery_type_name="LiIon",
        operation_mode=0, operation_mode_name="Charge",
        work_time_seconds=0, status=status, status_name="x",
        voltage_mv=mv, current_ma=0, capacity_mah=0,
        temperature_c=25.0, internal_temp_c=27.0,
        is_error=status >= 0x80, error_code=None,
    )


def s(target, mode=0, slot=0):
    return SlotSettings(
        slot_number=slot, is_busy=False, battery_type=0, operation_mode=mode,
        capacity_mah=100, charge_current_ma=100, discharge_current_ma=500,
        discharge_cut_voltage_mv=3000, charge_end_voltage_mv=target,
        charge_end_current_ma=100, discharge_reduce_current_ma=500,
        num_cycles=1, charge_resting_min=1, cycle_mode=0, peak_sense_mv=3,
        trickle_current_ma=1, restart_voltage_mv=2300, cut_temperature_c=45,
        cut_time_min=1,
    )


def test_plan_states():
    data = [d(4, 3600), d(0x8A, 3292), d(0, 0), d(1, 4100)]
    settings = [s(4200), s(2500), None, None]
    plan = plan_start(data, settings)
    assert [p.state for p in plan.slots] == [STARTS, BLOCKED, EMPTY, RUNNING]
    assert plan.needs_reset and plan.any_running
    assert len(plan.starting) == 3


def test_standby_no_reset():
    plan = plan_start([d(0, 3600)] * 4, [s(4200)] * 4)
    assert not plan.needs_reset
    assert all(p.state == STARTS for p in plan.slots)


def test_idle_presets_listed_first():
    from mc3000_profiles import ordered_preset_names
    names = ordered_preset_names()
    assert names[0].startswith("Idle") and names[1].startswith("Idle")
    assert not names[2].startswith("Idle")
