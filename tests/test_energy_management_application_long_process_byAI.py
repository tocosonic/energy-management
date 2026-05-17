"""Long-running process integration test for car charging decisions.

This suite drives EnergyManagementApplication.update_car_charging over a simulated
75-minute timeline, with changing available power. It validates transitions between:
- no charging
- dynamic charging
- stop charging
and verifies phase/current switching behavior.
"""

from datetime import datetime, timedelta
from pathlib import Path
import os
import sys
import tempfile

import pytest
from unittest.mock import Mock, patch

# Allow imports like `from services...` and `from application...`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import application.energy_management_application as ema_module
from application.energy_management_application import EnergyManagementApplication
from services.database_service import ChargerAction


class _FakeDateTime:
    """Minimal datetime replacement used by EnergyManagementApplication during tests."""

    current = datetime(2026, 1, 1, 12, 0, 0)

    @classmethod
    def now(cls):
        return cls.current


@pytest.fixture
def app_with_mocked_io():
    """Create app instance with all I/O mocked."""

    fd, db_path = tempfile.mkstemp(suffix="_ema_long_process.db")
    os.close(fd)

    env_vars = {
        "RELAY_PIN_WW": "20",
        "RELAY_PIN_HEATING1": "21",
        "RELAY_PIN_HEATING2": "26",
        "OPENWEATHER_API_KEY": "test_weather_key",
        "OPENWEATHER_LAT": "48.2082",
        "OPENWEATHER_LON": "16.3738",
        "SONNEN_BATTERY_HOST": "192.168.1.100",
        "SONNEN_BATTERY_PORT": "8080",
        "SONNEN_BATTERY_API_KEY": "test_sonnen_key",
        "GOE_HOST": "192.168.1.50",
        "GOE_API_KEY": "test_goe_key",
        "GOE_FIXED_CHARGING_USER": "1",
        "GOE_DYNAMIC_CHARGING_USER": "0",
        "DATABASE_PATH": db_path,
        "WW_ENERGY_CONSUMPTION": "700",
        "HEATING1_ENERGY_CONSUMPTION": "1000",
        "HEATING2_ENERGY_CONSUMPTION": "500",
        "START_WW_WAIT_TIME": "5",
        "START_HEATING1_WAIT_TIME": "5",
        "START_HEATING2_WAIT_TIME": "5",
        "START_CAR_CHARGING_WAIT_TIME": "7",
        "STOP_WW_WAIT_TIME": "15",
        "STOP_HEATING1_WAIT_TIME": "10",
        "STOP_HEATING2_WAIT_TIME": "5",
        "STOP_CAR_CHARGING_WAIT_TIME": "15",
        "NON_USED_ENERGY_BUFFER": "500",
        "ENERGY_METER_SLAVE_ID": "1",
        "ENERGY_METER_PORT": "/dev/ttyUSB0",
        "ENERGY_METER_BAUDRATE": "9600",
    }

    goe_status = {
        "sse": "901234567",
        "fna": "GoE Charger",
    }
    sonnen_status = {
        "Consumption_Avg": 2000,
        "Production_W": 5000,
        "GridFeedIn_W": 3000,
        "Pac_total_W": -500,
        "USOC": 80,
        "OperatingMode": 2,
        "SystemStatus": 1,
    }
    weather_status = {
        "sys": {
            "sunrise": int((datetime.now() - timedelta(hours=12)).timestamp()),
            "sunset": int((datetime.now() + timedelta(hours=2)).timestamp()),
        }
    }

    with patch.dict(os.environ, env_vars), \
         patch("requests.get") as mock_get, \
         patch("requests.put") as mock_put, \
         patch("services.wago_energy_meter.ModbusSerialClient") as mock_modbus, \
         patch("services.sgready_device_service.GPIO"):

        def _mock_get(url, **_kwargs):
            response = Mock()
            response.status_code = 200

            if "openweathermap.org" in url:
                response.json.return_value = weather_status
            elif "/api/status?filter=" in url:
                filter_key = url.split("filter=")[-1]
                response.json.return_value = {filter_key: goe_status.get(filter_key)}
            else:
                response.json.return_value = sonnen_status
            return response

        def _mock_put(_url, **_kwargs):
            response = Mock()
            response.status_code = 200
            response.json.return_value = {"status": "ok"}
            return response

        mock_get.side_effect = _mock_get
        mock_put.side_effect = _mock_put

        mock_energy_meter_client = Mock()
        mock_energy_meter_client.connect.return_value = True
        mock_energy_meter_client.read_holding_registers.return_value = Mock(
            isError=Mock(return_value=False),
            registers=[0x43C8, 0x0000],
        )
        mock_modbus.return_value = mock_energy_meter_client

        app = EnergyManagementApplication()
        app.energy_meter.client = mock_energy_meter_client

        yield app

    if os.path.exists(db_path):
        os.remove(db_path)


class TestEnergyManagementLongCarChargingProcess:
    def test_dynamic_car_charging_over_75_simulated_minutes(self, app_with_mocked_io, monkeypatch):
        app = app_with_mocked_io

        # Replace module datetime used inside application logic.
        monkeypatch.setattr(ema_module, "datetime", _FakeDateTime)

        # Simulated charger state and event history.
        charger_state = {
            "is_charging": False,
            "phases": 1,
            "current": 0,
        }
        phase_events: list[int] = []
        current_events: list[int] = []
        charging_events: list[bool] = []

        # In-memory action storage to emulate DB timestamps for wait windows.
        action_state = {
            "action": None,
            "timestamp": None,
            "session_id": None,
        }

        session_counter = {"value": 0}

        def effective_power() -> int:
            if not charger_state["is_charging"]:
                return 0
            return charger_state["phases"] * charger_state["current"] * 230

        def fake_create_goe_action(action: ChargerAction, session_id: int = None):
            if action_state["action"] == action:
                return
            action_state["action"] = action
            action_state["timestamp"] = _FakeDateTime.now()
            action_state["session_id"] = session_id

        def fake_get_goe_action_timestamp():
            return action_state["timestamp"]

        def fake_get_goe_action_session_id():
            return action_state["session_id"]

        def fake_create_car_entry_start() -> int:
            session_counter["value"] += 1
            return session_counter["value"]

        # Patch DB and report-entry hooks used by update_car_charging.
        monkeypatch.setattr(app.db_service, "create_goe_action", fake_create_goe_action)
        monkeypatch.setattr(app.db_service, "get_goe_action_timestamp", fake_get_goe_action_timestamp)
        monkeypatch.setattr(app.db_service, "get_goe_action_session_id", fake_get_goe_action_session_id)
        monkeypatch.setattr(app, "create_car_charging_report_entry_start", fake_create_car_entry_start)

        # Patch GoE behavior for dynamic user flow while retaining set_charging_power logic.
        monkeypatch.setattr(app.goe_service, "is_car_charging_allowed", lambda: True)
        monkeypatch.setattr(app.goe_service, "is_car_charging", lambda: charger_state["is_charging"])
        monkeypatch.setattr(app.goe_service, "is_car_charging_complete", lambda: False)
        monkeypatch.setattr(app.goe_service, "is_dynamic_charging_user", lambda: True)
        monkeypatch.setattr(app.goe_service, "get_current_charging_power", lambda: effective_power())
        monkeypatch.setattr(app.goe_service, "get_configured_charging_power", lambda: effective_power())

        def fake_set_phases(phases: int) -> bool:
            if phases not in (1, 3):
                return False
            charger_state["phases"] = phases
            phase_events.append(phases)
            return True

        def fake_set_current(current: int) -> bool:
            if current < 6 or current > 16:
                return False
            charger_state["current"] = current
            current_events.append(current)
            return True

        def fake_set_charging_on() -> bool:
            charger_state["is_charging"] = True
            charging_events.append(True)
            return True

        def fake_set_charging_off() -> bool:
            charger_state["is_charging"] = False
            charger_state["current"] = 0
            charging_events.append(False)
            return True

        monkeypatch.setattr(app.goe_service, "_set_charging_phases", fake_set_phases)
        monkeypatch.setattr(app.goe_service, "_set_charging_current", fake_set_current)
        monkeypatch.setattr(app.goe_service, "set_charging_on", fake_set_charging_on)
        monkeypatch.setattr(app.goe_service, "set_charging_off", fake_set_charging_off)

        original_set_charging_power = app.goe_service.set_charging_power

        def fake_set_charging_power(power: int) -> bool:
            # In application flow, 0 W is a stop command.
            if power <= 0:
                return fake_set_charging_off()
            return original_set_charging_power(power)

        monkeypatch.setattr(app.goe_service, "set_charging_power", fake_set_charging_power)

        # Battery discharge control is not part of this process test.
        monkeypatch.setattr(app.sonnen_battery_service, "set_enable_discharge", lambda: None)
        monkeypatch.setattr(app.sonnen_battery_service, "set_disable_discharge", lambda: None)

        # Build available power profile: 75 simulated minutes.
        # 0-9: low (no charging)
        # 10-29: medium (single-phase dynamic charging)
        # 30-49: high (three-phase dynamic charging)
        # 50-65: zero (stop charging after stop wait time)
        # 66-74: medium/high (resume charging)
        available_power_profile = (
            [400] * 10
            + [1600, 1800, 2100, 2300, 2500, 2800, 3000, 3200, 3400, 3600] * 2
            + [5000, 5600, 6200, 6800, 7400, 8000, 8600, 9200, 9800, 10400] * 2
            + [0] * 16
            + [4200, 5000, 6200, 7000, 7800, 8600, 7000, 6200, 5000]
        )
        assert len(available_power_profile) == 75

        actions: list[ChargerAction] = []
        timeline: list[dict] = []

        minute_index = {"value": 0}

        def fake_grid_feed_in_minimum(_minutes: int) -> int:
            target_available = available_power_profile[minute_index["value"]]
            # update_car_charging computes:
            # available_power = min_power - buffer + current_charging_power
            # So choose min_power to produce the target available power for this minute.
            return int(target_available + app.control_structure.NON_USED_ENERGY_BUFFER - effective_power())

        monkeypatch.setattr(app.sonnen_battery_service, "get_grid_feed_in_minimum", fake_grid_feed_in_minimum)

        for minute in range(len(available_power_profile)):
            minute_index["value"] = minute
            _FakeDateTime.current = datetime(2026, 1, 1, 12, 0, 0) + timedelta(minutes=minute)

            action = app.update_car_charging(
                # app.control_structure.START_CAR_CHARGING_WAIT_TIME,
                # app.control_structure.STOP_CAR_CHARGING_WAIT_TIME,
            )
            actions.append(action)
            timeline.append(
                {
                    "minute": minute,
                    "available_power": available_power_profile[minute],
                    "action": action,
                    "is_charging": charger_state["is_charging"],
                    "phases": charger_state["phases"],
                    "current": charger_state["current"],
                    "effective_power": effective_power(),
                }
            )

        # Long-horizon simulation coverage.
        assert len(timeline) >= 60

        # Validate process-level action transitions across the whole run.
        assert ChargerAction.REQUEST_DYNAMIC_CHARGING in actions
        assert ChargerAction.DYNAMIC_CHARGING in actions
        assert ChargerAction.REQUEST_STOP_CHARGING in actions
        assert ChargerAction.CHARGING_STOPPED in actions

        # Charging must be both on and off at different times.
        assert any(row["is_charging"] for row in timeline)
        assert any(not row["is_charging"] for row in timeline)

        # Verify phase and current adaptation took place.
        charging_rows = [row for row in timeline if row["is_charging"]]
        assert any(row["phases"] == 1 for row in charging_rows)
        assert any(row["phases"] == 3 for row in charging_rows)
        assert len({row["current"] for row in charging_rows}) >= 4

        # Ensure explicit on/off transitions happened.
        assert any(event is True for event in charging_events)
        assert any(event is False for event in charging_events)

        # Ensure phase changes happened at least once to 3-phase and 1-phase.
        assert 1 in phase_events
        assert 3 in phase_events

    def test_dynamic_car_charging_cloud_cover_oscillation_no_flapping(self, app_with_mocked_io, monkeypatch):
        app = app_with_mocked_io

        # Replace module datetime used inside application logic.
        monkeypatch.setattr(ema_module, "datetime", _FakeDateTime)

        # Simulated charger state and event history.
        charger_state = {
            "is_charging": False,
            "phases": 1,
            "current": 0,
        }
        phase_events: list[int] = []
        current_events: list[int] = []
        charging_events: list[bool] = []

        # In-memory action storage to emulate DB timestamps for wait windows.
        action_state = {
            "action": None,
            "timestamp": None,
            "session_id": None,
        }

        session_counter = {"value": 0}

        def effective_power() -> int:
            if not charger_state["is_charging"]:
                return 0
            return charger_state["phases"] * charger_state["current"] * 230

        def fake_create_goe_action(action: ChargerAction, session_id: int = None):
            if action_state["action"] == action:
                return
            action_state["action"] = action
            action_state["timestamp"] = _FakeDateTime.now()
            action_state["session_id"] = session_id

        def fake_get_goe_action_timestamp():
            return action_state["timestamp"]

        def fake_get_goe_action_session_id():
            return action_state["session_id"]

        def fake_create_car_entry_start() -> int:
            session_counter["value"] += 1
            return session_counter["value"]

        monkeypatch.setattr(app.db_service, "create_goe_action", fake_create_goe_action)
        monkeypatch.setattr(app.db_service, "get_goe_action_timestamp", fake_get_goe_action_timestamp)
        monkeypatch.setattr(app.db_service, "get_goe_action_session_id", fake_get_goe_action_session_id)
        monkeypatch.setattr(app, "create_car_charging_report_entry_start", fake_create_car_entry_start)

        monkeypatch.setattr(app.goe_service, "is_car_charging_allowed", lambda: True)
        monkeypatch.setattr(app.goe_service, "is_car_charging", lambda: charger_state["is_charging"])
        monkeypatch.setattr(app.goe_service, "is_car_charging_complete", lambda: False)
        monkeypatch.setattr(app.goe_service, "is_dynamic_charging_user", lambda: True)
        monkeypatch.setattr(app.goe_service, "get_current_charging_power", lambda: effective_power())
        monkeypatch.setattr(app.goe_service, "get_configured_charging_power", lambda: effective_power())

        def fake_set_phases(phases: int) -> bool:
            if phases not in (1, 3):
                return False
            charger_state["phases"] = phases
            phase_events.append(phases)
            return True

        def fake_set_current(current: int) -> bool:
            if current < 6 or current > 16:
                return False
            charger_state["current"] = current
            current_events.append(current)
            return True

        def fake_set_charging_on() -> bool:
            charger_state["is_charging"] = True
            charging_events.append(True)
            return True

        def fake_set_charging_off() -> bool:
            charger_state["is_charging"] = False
            charger_state["current"] = 0
            charging_events.append(False)
            return True

        monkeypatch.setattr(app.goe_service, "_set_charging_phases", fake_set_phases)
        monkeypatch.setattr(app.goe_service, "_set_charging_current", fake_set_current)
        monkeypatch.setattr(app.goe_service, "set_charging_on", fake_set_charging_on)
        monkeypatch.setattr(app.goe_service, "set_charging_off", fake_set_charging_off)

        original_set_charging_power = app.goe_service.set_charging_power

        def fake_set_charging_power(power: int) -> bool:
            if power <= 0:
                return fake_set_charging_off()
            return original_set_charging_power(power)

        monkeypatch.setattr(app.goe_service, "set_charging_power", fake_set_charging_power)

        monkeypatch.setattr(app.sonnen_battery_service, "set_enable_discharge", lambda: None)
        monkeypatch.setattr(app.sonnen_battery_service, "set_disable_discharge", lambda: None)

        # 75 minutes: stabilize high power for startup, then frequent oscillation windows
        # shorter than STOP wait time (15 min), then recover. This should avoid stop/start flapping.
        startup = [4600] * 10
        oscillation_cycle = [900] * 3 + [4600] * 3
        oscillation = oscillation_cycle * 8  # 48 minutes
        recovery = [5600] * 17
        available_power_profile = startup + oscillation + recovery
        assert len(available_power_profile) == 75

        actions: list[ChargerAction] = []
        timeline: list[dict] = []

        minute_index = {"value": 0}

        def fake_grid_feed_in_minimum(_minutes: int) -> int:
            target_available = available_power_profile[minute_index["value"]]
            return int(target_available + app.control_structure.NON_USED_ENERGY_BUFFER - effective_power())

        monkeypatch.setattr(app.sonnen_battery_service, "get_grid_feed_in_minimum", fake_grid_feed_in_minimum)

        for minute in range(len(available_power_profile)):
            minute_index["value"] = minute
            _FakeDateTime.current = datetime(2026, 1, 1, 12, 0, 0) + timedelta(minutes=minute)

            action = app.update_car_charging(
                # app.control_structure.START_CAR_CHARGING_WAIT_TIME,
                # app.control_structure.STOP_CAR_CHARGING_WAIT_TIME,
            )
            actions.append(action)
            timeline.append(
                {
                    "minute": minute,
                    "available_power": available_power_profile[minute],
                    "action": action,
                    "is_charging": charger_state["is_charging"],
                    "phases": charger_state["phases"],
                    "current": charger_state["current"],
                    "effective_power": effective_power(),
                }
            )

        assert len(timeline) >= 60

        # Controller should enter dynamic charging.
        assert ChargerAction.DYNAMIC_CHARGING in actions

        # Frequent short dips should request stop at times, but should not actually stop charging.
        assert ChargerAction.REQUEST_STOP_CHARGING in actions
        assert ChargerAction.CHARGING_STOPPED not in actions

        # No off-transition expected once charging has started in this oscillating scenario.
        assert any(event is True for event in charging_events)
        assert all(event is not False for event in charging_events)

        # Verify no timeline sample reports charging off after the initial startup.
        assert all(row["is_charging"] for row in timeline[10:])

        # We still expect adaptive current updates.
        assert len(set(current_events)) >= 2

    def test_dynamic_car_charging_storm_cloud_sustained_low_triggers_stop(self, app_with_mocked_io, monkeypatch):
        app = app_with_mocked_io

        # Replace module datetime used inside application logic.
        monkeypatch.setattr(ema_module, "datetime", _FakeDateTime)

        charger_state = {
            "is_charging": False,
            "phases": 1,
            "current": 0,
        }
        charging_events: list[bool] = []

        action_state = {
            "action": None,
            "timestamp": None,
            "session_id": None,
        }

        session_counter = {"value": 0}

        def effective_power() -> int:
            if not charger_state["is_charging"]:
                return 0
            return charger_state["phases"] * charger_state["current"] * 230

        def fake_create_goe_action(action: ChargerAction, session_id: int = None):
            if action_state["action"] == action:
                return
            action_state["action"] = action
            action_state["timestamp"] = _FakeDateTime.now()
            action_state["session_id"] = session_id

        def fake_get_goe_action_timestamp():
            return action_state["timestamp"]

        def fake_get_goe_action_session_id():
            return action_state["session_id"]

        def fake_create_car_entry_start() -> int:
            session_counter["value"] += 1
            return session_counter["value"]

        monkeypatch.setattr(app.db_service, "create_goe_action", fake_create_goe_action)
        monkeypatch.setattr(app.db_service, "get_goe_action_timestamp", fake_get_goe_action_timestamp)
        monkeypatch.setattr(app.db_service, "get_goe_action_session_id", fake_get_goe_action_session_id)
        monkeypatch.setattr(app, "create_car_charging_report_entry_start", fake_create_car_entry_start)

        monkeypatch.setattr(app.goe_service, "is_car_charging_allowed", lambda: True)
        monkeypatch.setattr(app.goe_service, "is_car_charging", lambda: charger_state["is_charging"])
        monkeypatch.setattr(app.goe_service, "is_car_charging_complete", lambda: False)
        monkeypatch.setattr(app.goe_service, "is_dynamic_charging_user", lambda: True)
        monkeypatch.setattr(app.goe_service, "get_current_charging_power", lambda: effective_power())
        monkeypatch.setattr(app.goe_service, "get_configured_charging_power", lambda: effective_power())

        def fake_set_phases(phases: int) -> bool:
            if phases not in (1, 3):
                return False
            charger_state["phases"] = phases
            return True

        def fake_set_current(current: int) -> bool:
            if current < 6 or current > 16:
                return False
            charger_state["current"] = current
            return True

        def fake_set_charging_on() -> bool:
            charger_state["is_charging"] = True
            charging_events.append(True)
            return True

        def fake_set_charging_off() -> bool:
            charger_state["is_charging"] = False
            charger_state["current"] = 0
            charging_events.append(False)
            return True

        monkeypatch.setattr(app.goe_service, "_set_charging_phases", fake_set_phases)
        monkeypatch.setattr(app.goe_service, "_set_charging_current", fake_set_current)
        monkeypatch.setattr(app.goe_service, "set_charging_on", fake_set_charging_on)
        monkeypatch.setattr(app.goe_service, "set_charging_off", fake_set_charging_off)

        original_set_charging_power = app.goe_service.set_charging_power

        def fake_set_charging_power(power: int) -> bool:
            if power <= 0:
                return fake_set_charging_off()
            return original_set_charging_power(power)

        monkeypatch.setattr(app.goe_service, "set_charging_power", fake_set_charging_power)

        monkeypatch.setattr(app.sonnen_battery_service, "set_enable_discharge", lambda: None)
        monkeypatch.setattr(app.sonnen_battery_service, "set_disable_discharge", lambda: None)

        # 75 minutes:
        # - startup high power to begin charging,
        # - sustained storm cloud low-power period (> stop wait time) to force real stop,
        # - recovery high power to start charging again.
        startup = [5200] * 12
        sustained_low = [500] * 20
        recovery = [6200] * 43
        available_power_profile = startup + sustained_low + recovery
        assert len(available_power_profile) == 75

        actions: list[ChargerAction] = []

        minute_index = {"value": 0}

        def fake_grid_feed_in_minimum(_minutes: int) -> int:
            target_available = available_power_profile[minute_index["value"]]
            return int(target_available + app.control_structure.NON_USED_ENERGY_BUFFER - effective_power())

        monkeypatch.setattr(app.sonnen_battery_service, "get_grid_feed_in_minimum", fake_grid_feed_in_minimum)

        for minute in range(len(available_power_profile)):
            minute_index["value"] = minute
            _FakeDateTime.current = datetime(2026, 1, 1, 12, 0, 0) + timedelta(minutes=minute)

            action = app.update_car_charging(
                # app.control_structure.START_CAR_CHARGING_WAIT_TIME,
                # app.control_structure.STOP_CAR_CHARGING_WAIT_TIME,
            )
            actions.append(action)

        assert len(actions) == 75

        # During storm period we expect a full stop path, not just requests.
        assert ChargerAction.REQUEST_STOP_CHARGING in actions
        assert ChargerAction.CHARGING_STOPPED in actions

        # After recovery we should request and enter dynamic charging again.
        assert ChargerAction.REQUEST_DYNAMIC_CHARGING in actions
        assert ChargerAction.DYNAMIC_CHARGING in actions

        # Confirm at least one off transition and a later on transition occurred.
        assert any(event is False for event in charging_events)
        assert any(event is True for event in charging_events)

        first_off_idx = next(i for i, event in enumerate(charging_events) if event is False)
        assert any(event is True for event in charging_events[first_off_idx + 1:])
