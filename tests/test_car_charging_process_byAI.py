"""Long-horizon process tests for car charging behavior.

This suite simulates changing available power over more than 60 minutes and
verifies switching between:
- not charging and charging,
- single-phase and three-phase charging,
- different charging currents.

No HTTP calls are performed in these tests.
"""

from dataclasses import dataclass
from pathlib import Path
import sys

import pytest

# Allow imports like `from services...` when running pytest from repository root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.goe_service import GoEService


@dataclass
class SimulatedChargerState:
    """In-memory charger state used by the GoE process simulation tests."""

    is_charging: bool = False
    phases: int = 1
    current_a: int = 0


def _build_available_power_profile() -> list[int]:
    """Create a profile with more than 60 minutes of power changes.

    Timeline (75 minutes total):
    - 15 min: no power -> charging off
    - 20 min: low-to-mid power -> single-phase charging with changing current
    - 20 min: high power -> three-phase charging with changing current
    - 10 min: no power -> charging off
    - 10 min: medium/high power -> charging resumes
    """

    segment_1 = [0] * 15
    segment_2 = [1380, 1500, 1800, 2000, 2300, 2600, 2900, 3200, 3400, 3600] * 2
    segment_3 = [4600, 5200, 5800, 6400, 7000, 7600, 8200, 9000, 9800, 10500] * 2
    segment_4 = [0] * 10
    segment_5 = [4800, 5400, 6000, 6600, 7200, 7800, 8400, 9000, 7200, 5400]

    return segment_1 + segment_2 + segment_3 + segment_4 + segment_5


@pytest.fixture
def simulated_goe_service(monkeypatch):
    """Build a GoEService instance with side effects replaced by in-memory state updates."""

    service = object.__new__(GoEService)
    service.MINIMUM_ENERGY_CONSUMPTION = 1380

    state = SimulatedChargerState()
    events: list[tuple[str, int | bool]] = []

    def _set_charging_phases(phases: int) -> bool:
        if phases not in (1, 3):
            return False
        state.phases = phases
        events.append(("phase", phases))
        return True

    def _set_charging_current(current: int) -> bool:
        if current < 6 or current > 16:
            return False
        state.current_a = current
        events.append(("current", current))
        return True

    def set_charging_on() -> bool:
        state.is_charging = True
        events.append(("charging", True))
        return True

    def set_charging_off() -> bool:
        state.is_charging = False
        state.current_a = 0
        events.append(("charging", False))
        return True

    monkeypatch.setattr(service, "_set_charging_phases", _set_charging_phases)
    monkeypatch.setattr(service, "_set_charging_current", _set_charging_current)
    monkeypatch.setattr(service, "set_charging_on", set_charging_on)
    monkeypatch.setattr(service, "set_charging_off", set_charging_off)

    return service, state, events


def _apply_available_power(service: GoEService, available_power_w: int) -> bool:
    """Apply available power as controller input for one simulated minute.

    The process expectation is:
    - below minimum threshold -> charging off
    - otherwise -> adapt phase/current via set_charging_power
    """

    if available_power_w < service.MINIMUM_ENERGY_CONSUMPTION:
        return service.set_charging_off()
    return service.set_charging_power(available_power_w)


def _effective_power_w(state: SimulatedChargerState) -> int:
    if not state.is_charging:
        return 0
    return state.phases * state.current_a * 230


class TestCarChargingProcess:
    def test_long_running_profile_switches_phase_current_and_off(self, simulated_goe_service):
        service, state, events = simulated_goe_service
        available_power_profile = _build_available_power_profile()

        history: list[dict[str, int | bool]] = []

        for minute, available_power in enumerate(available_power_profile):
            _apply_available_power(service, available_power)
            history.append(
                {
                    "minute": minute,
                    "available_power": available_power,
                    "is_charging": state.is_charging,
                    "phases": state.phases,
                    "current_a": state.current_a,
                    "effective_power": _effective_power_w(state),
                }
            )

        # Requirement: long-horizon process simulation (> 60 minutes).
        assert len(history) >= 60

        # Requirement: both charging and not-charging periods are present.
        assert any(not row["is_charging"] for row in history)
        assert any(row["is_charging"] for row in history)

        # Requirement: phase switching occurs (single and three phase).
        charging_rows = [row for row in history if row["is_charging"]]
        assert any(row["phases"] == 1 for row in charging_rows)
        assert any(row["phases"] == 3 for row in charging_rows)

        # Requirement: current is adjusted over time.
        currents = {row["current_a"] for row in charging_rows}
        assert len(currents) >= 4

        # Requirement: no power should force charging off.
        off_rows = [row for row in history if row["available_power"] == 0]
        assert off_rows
        assert all(not row["is_charging"] for row in off_rows)

        # Ensure transitions happened at runtime, not only static state.
        phase_events = [event for event in events if event[0] == "phase"]
        charging_events = [event for event in events if event[0] == "charging"]
        assert len(phase_events) >= 2
        assert any(event[1] is False for event in charging_events)
        assert any(event[1] is True for event in charging_events)

    def test_repeated_low_power_windows_stop_charging(self, simulated_goe_service):
        service, state, _events = simulated_goe_service

        # 65-minute profile with multiple stop/resume windows.
        profile = ([5000] * 10) + ([0] * 8) + ([6200] * 12) + ([0] * 5) + ([7000] * 30)

        charging_flags: list[bool] = []
        for available_power in profile:
            _apply_available_power(service, available_power)
            charging_flags.append(state.is_charging)

        assert len(charging_flags) == 65

        # We expect at least one stop and one resume in this timeline.
        saw_stop = any(charging_flags[i - 1] and not charging_flags[i] for i in range(1, len(charging_flags)))
        saw_resume = any((not charging_flags[i - 1]) and charging_flags[i] for i in range(1, len(charging_flags)))

        assert saw_stop
        assert saw_resume
