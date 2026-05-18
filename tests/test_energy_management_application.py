
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

@pytest.fixture
def app_with_mocked_io():
    """Create app instance with all I/O mocked."""

    print("")
    print(">>> create database file for testing and ensure it's removed after the test")
    # create database file for testing and ensure it's removed after the test
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
        "DATABASE_PATH": "./test-db.db",
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
        "tpa": 3000.0
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
            elif "/api/v1/status" in url:
                response.json.return_value = sonnen_status
            else:
                print(f"Unexpected GET request to URL: {url}")
                response.json.return_value = {}
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

        print(">>> initialize app with mocked I/O")
        app = EnergyManagementApplication()
        app.energy_meter.client = mock_energy_meter_client

        yield app

    # Ensure the temporary database file is removed after the test.
    # removing switched off for testing purposes, as we want to inspect the database after the test run
    # if os.path.exists(db_path):
    #     os.remove(db_path)

class TestEnergyManagementApplicationUpdateCarChargingProcess:
    def test_long_running_profile_max_power_stop_with_charging_not_allowed(self, app_with_mocked_io: EnergyManagementApplication):
        print(">>> start long-running simulation of car charging process with max power")
        
        app = app_with_mocked_io
        energy_meter_start = 25000  # Start with 25 kWh total energy
        app.energy_meter.get_total_energy_wh = Mock(return_value=energy_meter_start)

        # Simulate a long-running process with varying available power.
        # 10 + 8 + 12 + 5 + 30 = 65 minutes total, which meets the requirement of > 60 minutes.
        available_power_profile = [5000] * 20 + [0] * 8 + [1400] * 12 + [0] * 5 + [7000] * 30

        history: list[dict[str, int | bool]] = []

        for minute, available_power in enumerate(available_power_profile):
            # Mock the method that retrieves the minimum grid feed-in value to return the current available power in the profile.
            app.sonnen_battery_service.get_grid_feed_in_minimum = Mock(return_value=available_power)

            # make sure, that the preconditions for car charging are met, so that the app would turn on the car charging if there is enough excess energy available
            app.goe_service.is_car_charging_allowed = Mock(return_value=True)
            app.goe_service.get_last_user_with_name = Mock(return_value=(1, "Fixed Charging User"))
            
            #.get_last_user = Mock(return_value="1")  # Return the fixed charging user as the last user to ensure that the car is allowed to charge when there is enough excess energy

            action = app.update_car_charging()
            history.append(
                {
                    "minute": minute,
                    "available_power": available_power,
                    "charger_action": action,
                }
            )

        # set car charging off at the end of the profile to test the stopping process as well
        total_energy = 36500
        app.energy_meter.get_total_energy_wh = Mock(return_value=total_energy + energy_meter_start)  # Mock total energy
        app.goe_service.is_car_charging_allowed = Mock(return_value=False)
        action = app.update_car_charging()
        history.append(
            {
                "minute": len(available_power_profile),
                "available_power": available_power_profile[len(available_power_profile) - 1],
                "charger_action": action,
            }
        )
            
        print("History of car charging actions:")
        for record in history:
            print(record)

    def test_long_running_profile_max_power_stop_with_charging_finished(self, app_with_mocked_io: EnergyManagementApplication):
        print(">>> start long-running simulation of car charging process with max power")
        
        app = app_with_mocked_io
        energy_meter_start = 61500  # Start with 61.5 kWh total energy
        app.energy_meter.get_total_energy_wh = Mock(return_value=energy_meter_start)

        # Simulate a long-running process with varying available power.
        # 10 + 8 + 12 + 5 + 30 = 65 minutes total, which meets the requirement of > 60 minutes.
        available_power_profile = [5000] * 20 + [0] * 8 + [1400] * 12 + [0] * 5 + [7000] * 30

        history: list[dict[str, int | bool]] = []

        for minute, available_power in enumerate(available_power_profile):
            # Mock the method that retrieves the minimum grid feed-in value to return the current available power in the profile.
            app.sonnen_battery_service.get_grid_feed_in_minimum = Mock(return_value=available_power)

            # make sure, that the preconditions for car charging are met, so that the app would turn on the car charging if there is enough excess energy available
            app.goe_service.is_car_charging_allowed = Mock(return_value=True)
            app.goe_service.get_last_user_with_name = Mock(return_value=(1, "Fixed Charging User"))
            
            #.get_last_user = Mock(return_value="1")  # Return the fixed charging user as the last user to ensure that the car is allowed to charge when there is enough excess energy

            action = app.update_car_charging()
            history.append(
                {
                    "minute": minute,
                    "available_power": available_power,
                    "charger_action": action,
                }
            )

        # set car charging off at the end of the profile to test the stopping process as well
        total_energy = 31000
        app.energy_meter.get_total_energy_wh = Mock(return_value=total_energy + energy_meter_start)  # Mock total energy
        app.goe_service.is_car_charging_complete = Mock(return_value=True)
        action = app.update_car_charging()
        history.append(
            {
                "minute": len(available_power_profile),
                "available_power": available_power_profile[len(available_power_profile) - 1],
                "charger_action": action,
            }
        )

        print("History of car charging actions:")
        for record in history:
            print(record)
        
    def test_long_running_profile_switches_phase_current_and_off(self, app_with_mocked_io: EnergyManagementApplication):
        print(">>> start long-running simulation of car charging process with variable power")
        
        app = app_with_mocked_io
        
        