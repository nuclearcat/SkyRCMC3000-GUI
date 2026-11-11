"""
Start planning for the MC3000.

The USB start command (0x05) has no slot parameter: it starts every slot
that holds a cell and is idle. Slots that are "Finished" or stopped with an
error (e.g. "Time Cut") ignore it until they are reset - a stop command
(0xFE) resets all slots to standby and the charger then picks up the slot
program. This module works out what a start would do so the GUI can show
it before anything is sent.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from mc3000_protocol import SlotData, SlotSettings, BATTERY_TYPES

ACTIVE = (1, 2, 3)          # charging, discharging, resting
EMPTY_SLOT_MV = 500         # below this no cell is inserted
MODE_CHARGE = 0
# Li chemistries (LiIon, LiFe, LiHV) check the target voltage before charging.
# Ni chemistries do not (tested with NiMH: charges until the cut-off time).
LI_TYPES = (0, 1, 2)

# Plan states
RUNNING = "running"
EMPTY = "empty"            # no voltage reading (may still hold a cell)
NO_DATA = "no_data"
STARTS = "starts"
BLOCKED = "blocked"          # starts, but will not charge (cell above target)


@dataclass
class SlotPlan:
    slot: int
    state: str
    needs_reset: bool = False
    text: str = ""


@dataclass
class StartPlan:
    slots: List[SlotPlan] = field(default_factory=list)

    @property
    def any_running(self) -> bool:
        return any(s.state == RUNNING for s in self.slots)

    @property
    def needs_reset(self) -> bool:
        return any(s.needs_reset for s in self.slots)

    @property
    def starting(self) -> List[SlotPlan]:
        return [s for s in self.slots if s.state in (STARTS, BLOCKED, EMPTY)]


def plan_start(data: List[Optional[SlotData]],
               settings: List[Optional[SlotSettings]]) -> StartPlan:
    plan = StartPlan()
    for slot in range(4):
        d = data[slot] if slot < len(data) else None
        st = settings[slot] if slot < len(settings) else None
        if d is None:
            plan.slots.append(SlotPlan(slot, NO_DATA, text="no data"))
            continue
        if d.status in ACTIVE:
            plan.slots.append(SlotPlan(slot, RUNNING, text=f"running ({d.status_name})"))
            continue
        if d.voltage_mv < EMPTY_SLOT_MV:
            # The charger does not measure every cell in standby (seen with
            # NiMH: 0.000 V reported although a cell was inserted).
            plan.slots.append(SlotPlan(
                slot, EMPTY,
                text="no voltage reading - starts if a cell is inserted"))
            continue

        needs_reset = d.status != 0
        if st is not None:
            btype = BATTERY_TYPES.get(st.battery_type, "?")
            mode = d.operation_mode_name
            prog = f"{btype} {mode}"
            if (st.operation_mode == MODE_CHARGE and st.battery_type in LI_TYPES
                    and st.charge_end_voltage_mv > 0
                    and d.voltage_mv >= st.charge_end_voltage_mv):
                plan.slots.append(SlotPlan(
                    slot, BLOCKED, needs_reset,
                    f"{prog}, target {st.charge_end_voltage_mv / 1000:.2f} V - "
                    f"cell at {d.voltage_v:.2f} V will not be charged"))
                continue
            if st.operation_mode == MODE_CHARGE:
                prog += f" to {st.charge_end_voltage_mv / 1000:.2f} V, {st.charge_current_ma} mA"
                if 0 < st.cut_time_min <= 5:
                    prog += f", stops after {st.cut_time_min} min"
        else:
            prog = f"{d.battery_type_name} {d.operation_mode_name}"
        plan.slots.append(SlotPlan(slot, STARTS, needs_reset,
                                   f"starts: {prog} (cell at {d.voltage_v:.2f} V)"))
    return plan
