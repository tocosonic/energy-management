
from datetime import datetime, timedelta
from pathlib import Path
import os
import sys
import tempfile
from time import sleep
from dotenv import load_dotenv

import pytest
from unittest.mock import Mock, patch
from freezegun import freeze_time

TEST_START_TIME = datetime(2026, 5, 21, 12, 0, 0)

@pytest.fixture(autouse=True)
def frozen_time():
    with freeze_time(TEST_START_TIME) as frozen:
        yield frozen

# Allow imports like `from services...` and `from application...`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import application.energy_management_application as ema_module
from application.energy_management_application import EnergyManagementApplication
from services.database_service import HeatpumpAction

@pytest.fixture
def app_with_mocked_io():
    """Create app instance with all I/O mocked."""

    # create database file for testing and ensure it's removed after the test
    # fd, db_path = tempfile.mkstemp(suffix="_ema_long_process.db")
    # os.close(fd)

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
        # "DATABASE_PATH": db_path, --- IGNORE ---
        "DATABASE_PATH": "./test-db.db",
        "WW_ENERGY_CONSUMPTION": "700",
        "HEATING1_ENERGY_CONSUMPTION": "500",
        "HEATING2_ENERGY_CONSUMPTION": "200",
        "START_WW_WAIT_TIME": "5",
        "START_HEATING_WAIT_TIME": "5",
        "START_CAR_CHARGING_WAIT_TIME": "7",
        "STOP_WW_WAIT_TIME": "15",
        "STOP_HEATING_WAIT_TIME": "10",
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
            "sunrise": int((TEST_START_TIME - timedelta(hours=12)).timestamp()),
            "sunset": int((TEST_START_TIME + timedelta(hours=2)).timestamp()),
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
        app.db_service._clear_tables()  # Clear the database to ensure a clean state for testing
        app.energy_meter.client = mock_energy_meter_client

        yield app

    # Ensure the temporary database file is removed after the test.
    # removing switched off for testing purposes, as we want to inspect the database after the test run
    # if os.path.exists(db_path):
    #     os.remove(db_path)

class TestEnergyManagementApplicationUpdateHeatpumpProcess:
    """
    Test the heatpump process with long-running profiles of available power to ensure that the
    application correctly handles starting and stopping the heatpump based on the available
    excess energy and the configured waiting times for starting and stopping the heatpump process.
    
    Run all tests with:
        pytest -vv -s test_energy_management_application_heatpump.py
    
    Run a single test with:
        pytest -vv -s test_energy_management_application_heatpump.py::TestEnergyManagementApplicationUpdateHeatpumpProcess::test_long_running_profile_ww_heatpump
    
    PS: pytest option "-s" is needed to see the print statements in the test output, which are helpful to understand the sequence of actions and the state of the application during the test run.
    """

    def _set_sonnen_battery_power(self, app: EnergyManagementApplication, production: int, grid_feed_in: int, consumption: int):
        app.sonnen_battery_service.get_energy_production = Mock(return_value=production)  # Mock energy production to 5000 W to simulate a situation where there is some excess energy available for charging, but not the full 7000 W as in the previous test with max power. This allows us to test the dynamic adjustment of the charging power based on the available excess energy.
        app.sonnen_battery_service.get_grid_feed = Mock(return_value=grid_feed_in)  # Mock maximum available power to 7000 W to simulate a situation where there is enough excess energy available for charging with max power.
        app.sonnen_battery_service.get_energy_consumption = Mock(return_value=consumption)  # Mock energy consumption to 2000 W to simulate a situation where there is excess energy available for charging, but not the full 7000 W as in the previous test with max power. This allows us to test the dynamic adjustment of the charging power based on the available excess energy.
        app.sonnen_battery_service.refresh_status()  # Refresh the Sonnen battery status to update the grid feed-in value based on the mocked available power
    
    def test_long_running_profile_ww_heatpump(self, app_with_mocked_io: EnergyManagementApplication, frozen_time):
        print(">>> start long-running simulation of WW heatpump process with varying power")
        
        app = app_with_mocked_io

        # Simulate a long-running process with varying available power.
        # 10 + 17 + 12 + 5 + 10 = 54 minutes total
        available_power_profile = [5000] * 10 + [0] * 17 + [1400] * 12 + [0] * 5 + [7000] * 10
        history: list[dict[str, int | bool]] = []

        frozen_time_start = TEST_START_TIME  # Start at a fixed time for consistent testing
        frozen_time.move_to(frozen_time_start)
        
        app.warm_water_heatpump_service.is_on = Mock(return_value=False)  # Start with heatpump off

        for minute, available_power in enumerate(available_power_profile):
            # datetime.now needs to be mocked to simulate the waiting times for starting and stopping the car charging process. The waiting times are defined in the environment variables START_CAR_CHARGING_WAIT_TIME and STOP_CAR_CHARGING_WAIT_TIME, which are set to 7 and 15 minutes respectively in the test environment variables. So we need to simulate a time progression of at least 22 minutes to test both the starting and stopping process of the car charging.
            frozen_time.move_to(frozen_time_start + timedelta(minutes=minute))

            grid_feed_in = available_power
            consumption = 1500
            production = consumption + grid_feed_in  # Ensure that there is some excess energy available for charging
            self._set_sonnen_battery_power(app, production, grid_feed_in, consumption)

            action = app.update_heatpump(app.warm_water_heatpump_service, app.control_structure.START_WW_WAIT_TIME, app.control_structure.STOP_WW_WAIT_TIME)
            if action in [HeatpumpAction.HEATPUMP_ON, HeatpumpAction.REQUEST_HEATPUMP_OFF]:
                app.warm_water_heatpump_service.is_on = Mock(return_value=True)  # Mock heatpump status to on after it has been turned on
            elif action in [HeatpumpAction.HEATPUMP_OFF, HeatpumpAction.REQUEST_HEATPUMP_ON]:
                app.warm_water_heatpump_service.is_on = Mock(return_value=False)  # Mock heatpump status to off after it has been turned off
            
            history.append(
                {
                    "minute": minute,
                    "available_power": available_power,
                    "heatpump_action": action,
                }
            )
            
        print("History of heatpump actions:")
        for record in history:
            print(record)
