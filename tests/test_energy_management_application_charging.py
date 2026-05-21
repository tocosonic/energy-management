
from datetime import datetime, timedelta
from pathlib import Path
import os
import sys
import tempfile
from dotenv import load_dotenv

import pytest
from unittest.mock import Mock, patch
from freezegun import freeze_time

TEST_START_TIME = datetime(2026, 5, 20, 12, 0, 0)

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
from services.database_service import ChargerAction

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

        app.goe_service.set_charging_off = Mock(return_value=True)
        app.goe_service._set_charging_phases = Mock(return_value=True)
        app.goe_service._set_charging_current= Mock(return_value=True)
        app.goe_service._update_setting = Mock(return_value=True)
        app.goe_service._get_sleep_time = Mock(return_value=0)  # override sleep time to speed up tests

        yield app

    # Ensure the temporary database file is removed after the test.
    # removing switched off for testing purposes, as we want to inspect the database after the test run
    # if os.path.exists(db_path):
    #     os.remove(db_path)

class TestEnergyManagementApplicationUpdateCarChargingProcess:
    """
    Test the car charging process with long-running profiles of available power to ensure that the
    application correctly handles starting and stopping the car charging based on the available
    excess energy and the configured waiting times for starting and stopping the charging process.
    
    Run all tests with:
        pytest -vv -s test_energy_management_application.py
    
    Run a single test with:
        pytest -vv -s test_energy_management_application.py::TestEnergyManagementApplicationUpdateCarChargingProcess::test_long_running_profile_dynamic_power
    
    PS: pytest option "-s" is needed to see the print statements in the test output, which are helpful to understand the sequence of actions and the state of the application during the test run.
    """

    def _set_sonnen_battery_power(self, app: EnergyManagementApplication, production: int, grid_feed_in: int, consumption: int):
        app.sonnen_battery_service.get_energy_production = Mock(return_value=production)  # Mock energy production to 5000 W to simulate a situation where there is some excess energy available for charging, but not the full 7000 W as in the previous test with max power. This allows us to test the dynamic adjustment of the charging power based on the available excess energy.
        app.sonnen_battery_service.get_grid_feed = Mock(return_value=grid_feed_in)  # Mock maximum available power to 7000 W to simulate a situation where there is enough excess energy available for charging with max power.
        app.sonnen_battery_service.get_energy_consumption = Mock(return_value=consumption)  # Mock energy consumption to 2000 W to simulate a situation where there is excess energy available for charging, but not the full 7000 W as in the previous test with max power. This allows us to test the dynamic adjustment of the charging power based on the available excess energy.
        app.sonnen_battery_service.refresh_status()  # Refresh the Sonnen battery status to update the grid feed-in value based on the mocked available power
    
    def _set_goe_service(self, app: EnergyManagementApplication, charging_allowed: bool, last_user_id: int, last_user_name: str, authenticated_user_id: int):
        app.goe_service.is_car_charging_allowed = Mock(return_value=charging_allowed)
        app.goe_service.get_last_user_with_name = Mock(return_value=(last_user_id, last_user_name))
        app.goe_service.get_authenticated_user = Mock(return_value=(authenticated_user_id))
    
    def test_long_running_profile_max_power_stop_with_charging_not_allowed(self, app_with_mocked_io: EnergyManagementApplication, frozen_time):
        print(">>> start long-running simulation of car charging process with max power")
        
        app = app_with_mocked_io
        energy_meter_start = 25000  # Start with 25 kWh total energy
        app.energy_meter.get_total_energy_wh = Mock(return_value=energy_meter_start)
        # make sure, that the preconditions for car charging are met, so that the app would turn on the car charging if there is enough excess energy available
        self._set_goe_service(app, charging_allowed=True, last_user_id=1, last_user_name="Fixed Charging User", authenticated_user_id=1)

        # Simulate a long-running process with varying available power.
        # 10 + 8 + 12 + 5 + 10 = 45 minutes total
        available_power_profile = [5000] * 10 + [0] * 8 + [1400] * 12 + [0] * 5 + [7000] * 10
        history: list[dict[str, int | bool]] = []

        frozen_time_start = TEST_START_TIME  # Start at a fixed time for consistent testing
        frozen_time.move_to(frozen_time_start)

        for minute, available_power in enumerate(available_power_profile):
            # datetime.now needs to be mocked to simulate the waiting times for starting and stopping the car charging process. The waiting times are defined in the environment variables START_CAR_CHARGING_WAIT_TIME and STOP_CAR_CHARGING_WAIT_TIME, which are set to 7 and 15 minutes respectively in the test environment variables. So we need to simulate a time progression of at least 22 minutes to test both the starting and stopping process of the car charging.
            frozen_time.move_to(frozen_time_start + timedelta(minutes=minute))

            grid_feed_in = available_power
            consumption = 1500
            production = consumption + grid_feed_in  # Ensure that there is some excess energy available for charging, but not the full 7000 W as in the previous test with max power. This allows us to test the dynamic adjustment of the charging power based on the available excess energy.
            self._set_sonnen_battery_power(app, production, grid_feed_in, consumption)

            # total energy consumed so far
            total_energy = sum(available_power_profile[:minute + 1])  # Total energy is the sum of available power up to the current minute
            app.energy_meter.get_total_energy_wh = Mock(return_value=total_energy + energy_meter_start)  # Mock total energy

            action = app.update_car_charging()
            history.append(
                {
                    "minute": minute,
                    "available_power": available_power,
                    "charger_action": action,
                }
            )

        # set car charging off at the end of the profile to test the stopping process as well
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

    def test_long_running_profile_max_power_stop_with_charging_finished(self, app_with_mocked_io: EnergyManagementApplication, frozen_time):
        print(">>> start long-running simulation of car charging process with max power")
        
        app = app_with_mocked_io
        energy_meter_start = 61500  # Start with 61.5 kWh total energy
        app.energy_meter.get_total_energy_wh = Mock(return_value=energy_meter_start)
        # make sure, that the preconditions for car charging are met, so that the app would turn on the car charging if there is enough excess energy available
        self._set_goe_service(app, charging_allowed=True, last_user_id=1, last_user_name="Fixed Charging User", authenticated_user_id=1)

        # Simulate a long-running process with varying available power.
        # 10 + 8 + 12 + 5 + 30 = 65 minutes total
        available_power_profile = [5000] * 20 + [0] * 8 + [1400] * 12 + [0] * 5 + [7000] * 30
        history: list[dict[str, int | bool]] = []

        frozen_time_start = TEST_START_TIME + timedelta(minutes=60)  # Start at a fixed time for consistent testing
        frozen_time.move_to(frozen_time_start)

        for minute, available_power in enumerate(available_power_profile):
            # datetime.now needs to be mocked to simulate the waiting times for starting and stopping the car charging process. The waiting times are defined in the environment variables START_CAR_CHARGING_WAIT_TIME and STOP_CAR_CHARGING_WAIT_TIME, which are set to 7 and 15 minutes respectively in the test environment variables. So we need to simulate a time progression of at least 22 minutes to test both the starting and stopping process of the car charging.
            frozen_time.move_to(frozen_time_start + timedelta(minutes=minute))

            grid_feed_in = available_power
            consumption = 1500
            production = consumption + grid_feed_in  # Ensure that there is some excess energy available for charging, but not the full 7000 W as in the previous test with max power. This allows us to test the dynamic adjustment of the charging power based on the available excess energy.
            self._set_sonnen_battery_power(app, production, grid_feed_in, consumption)
            
            # total energy consumed so far
            total_energy = sum(available_power_profile[:minute + 1])  # Total energy is the sum of available power up to the current minute
            app.energy_meter.get_total_energy_wh = Mock(return_value=total_energy + energy_meter_start)  # Mock total energy

            action = app.update_car_charging()
            history.append(
                {
                    "minute": minute,
                    "available_power": available_power,
                    "charger_action": action,
                }
            )

        # set car charging off at the end of the profile to test the stopping process as well
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
        
    def test_long_running_profile_dynamic_power(self, app_with_mocked_io: EnergyManagementApplication, frozen_time):
        print(">>> start long-running simulation of car charging process with variable power")
        load_dotenv()
        
        app = app_with_mocked_io
        energy_meter_start = 200000  # Start with 200 kWh total energy
        app.energy_meter.get_total_energy_wh = Mock(return_value=energy_meter_start)
        # make sure, that the preconditions for car charging are met, so that the app would turn on the car charging if there is enough excess energy available
        self._set_goe_service(app, charging_allowed=True, last_user_id=0, last_user_name="Dynamic Charging User", authenticated_user_id=0)

        # available_power_profile = [5000] * 10
        available_power_profile = [0] * 7 + [5000] * 10 + [0] * 8 + [1400] * 12 + [0] * 5 + [7000] * 10
        history: list[dict[str, int | bool]] = []

        frozen_time_start = TEST_START_TIME + timedelta(minutes=180)  # Start at a fixed time for consistent testing
        frozen_time.move_to(frozen_time_start)
        
        for minute, available_power in enumerate(available_power_profile):
            # datetime.now needs to be mocked to simulate the waiting times for starting and stopping the car charging process. The waiting times are defined in the environment variables START_CAR_CHARGING_WAIT_TIME and STOP_CAR_CHARGING_WAIT_TIME, which are set to 7 and 15 minutes respectively in the test environment variables. So we need to simulate a time progression of at least 22 minutes to test both the starting and stopping process of the car charging.
            frozen_time.move_to(frozen_time_start + timedelta(minutes=minute))

            grid_feed_in = available_power
            consumption = 1500
            production = consumption + grid_feed_in  # Ensure that there is some excess energy available for charging, but not the full 7000 W as in the previous test with max power. This allows us to test the dynamic adjustment of the charging power based on the available excess energy.
            self._set_sonnen_battery_power(app, production, grid_feed_in, consumption)
            
            # total energy consumed so far
            total_energy = sum(available_power_profile[:minute + 1])  # Total energy is the sum of available power up to the current minute
            app.energy_meter.get_total_energy_wh = Mock(return_value=total_energy + energy_meter_start)  # Mock total energy

            action = app.update_car_charging()
            history.append(
                {
                    "minute": minute,
                    "available_power": available_power,
                    "charger_action": action,
                }
            )
            
            # check if the charging wait time 
            if minute == int(os.getenv("START_CAR_CHARGING_WAIT_TIME")) - 1 + 7:
                assert action == ChargerAction.NO_ACTION, f"Expected to still be requesting to charge at minute {minute}, but got {action}"
            elif minute == int(os.getenv("START_CAR_CHARGING_WAIT_TIME")) + 7:
                assert action == ChargerAction.DYNAMIC_CHARGING, f"Expected to be in dynamic charging phase at minute {minute}, but got {action}"

        # set car charging off at the end of the profile to test the stopping process as well
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

    def test_long_running_profile_fixed_and_dynamic_power(self, app_with_mocked_io: EnergyManagementApplication, frozen_time):
        print(">>> start long-running simulation of car charging process with fixed and dynamic power")
        load_dotenv()
        
        app = app_with_mocked_io
        energy_meter_start = 400000  # Start with 400 kWh total energy
        app.energy_meter.get_total_energy_wh = Mock(return_value=energy_meter_start)
        # make sure, that the preconditions for car charging are met, so that the app would turn on the car charging if there is enough excess energy available
        self._set_goe_service(app, charging_allowed=True, last_user_id=0, last_user_name="Dynamic Charging User", authenticated_user_id=0)

        # available_power_profile = [5000] * 10
        available_power_profile = [[0, 0, "Dynamic Charging User"]] * 7 + [[5000, 0, "Dynamic Charging User"]] * 10 + [[0, 0, "Dynamic Charging User"]] * 8 + [[1400, 0, "Dynamic Charging User"]] * 12 + [[0, 0, "Dynamic Charging User"]] * 5 + [[7000, 0, "Dynamic Charging User"]] * 10 + [[1000, 1, "Fixed Charging User"]] * 10 + [[0, 0, "Dynamic Charging User"]] * 7 + [[4000, 0, "Dynamic Charging User"]] * 10 + [[1500, 0, "Dynamic Charging User"]]
        history: list[dict[str, int | bool]] = []

        frozen_time_start = TEST_START_TIME + timedelta(minutes=180)  # Start at a fixed time for consistent testing
        frozen_time.move_to(frozen_time_start)
        
        for minute, (available_power, user_id, user_name) in enumerate(available_power_profile):
            # datetime.now needs to be mocked to simulate the waiting times for starting and stopping the car charging process. The waiting times are defined in the environment variables START_CAR_CHARGING_WAIT_TIME and STOP_CAR_CHARGING_WAIT_TIME, which are set to 7 and 15 minutes respectively in the test environment variables. So we need to simulate a time progression of at least 22 minutes to test both the starting and stopping process of the car charging.
            frozen_time.move_to(frozen_time_start + timedelta(minutes=minute))

            grid_feed_in = available_power
            consumption = 1500
            production = consumption + grid_feed_in  # Ensure that there is some excess energy available for charging, but not the full 7000 W as in the previous test with max power. This allows us to test the dynamic adjustment of the charging power based on the available excess energy.
            self._set_sonnen_battery_power(app, production, grid_feed_in, consumption)
            self._set_goe_service(app, charging_allowed=True, last_user_id=user_id, last_user_name=user_name, authenticated_user_id=user_id)

            # total energy consumed so far
            total_energy = sum([power for power, _, _ in available_power_profile[:minute + 1]])  # Total energy is the sum of available power up to the current minute
            app.energy_meter.get_total_energy_wh = Mock(return_value=total_energy + energy_meter_start)  # Mock total energy

            action = app.update_car_charging()
            history.append(
                {
                    "minute": minute,
                    "available_power": available_power,
                    "charger_action": action,
                    "user_id": user_id,
                    "user_name": user_name,
                }
            )
            
        # set car charging off at the end of the profile to test the stopping process as well
        app.goe_service.is_car_charging_complete = Mock(return_value=True)
        action = app.update_car_charging()
        history.append(
            {
                "minute": len(available_power_profile),
                "available_power": available_power_profile[len(available_power_profile) - 1][0],
                "charger_action": action,
                "user_id": available_power_profile[len(available_power_profile) - 1][1],
                "user_name": available_power_profile[len(available_power_profile) - 1][2],
            }
        )

        print("History of car charging actions:")
        for record in history:
            print(record)
                