"""Integration tests for the energy management application.

This test suite mocks all HTTP calls (GoE charger API, Sonnen battery API, weather API)
while using a real SQLite test database for data persistence testing.
"""

import pytest
import os
import tempfile
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

from application.energy_management_application import EnergyManagementApplication, ControlStructure
from services.database_service import ChargerAction
from services.goe_service import CarStatus


@pytest.fixture
def test_db_path():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    # Cleanup
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def mock_env_vars(test_db_path):
    """Mock environment variables with test values."""
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
        "DATABASE_PATH": test_db_path,
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
    return env_vars


@pytest.fixture
def mock_goe_service_response():
    """Mock response data for GoE charger API."""
    return {
        "sse": "901234567",  # Serial number
        "fna": "GoE Charger",  # Charger name
        "car": 1,  # Car status (IDLE)
        "alw": True,  # Charging allowed
        "amp": 10,  # Current in amperes
        "psm": 2,  # Phase mode (3-phase)
        "err": 0,  # No error
        "tpa": 7500.0,  # Total power average
        "lrc": 0,  # Last registered card ID
    }


@pytest.fixture
def mock_sonnen_response():
    """Mock response data for Sonnen battery API."""
    return {
        "Consumption_W": 2000,
        "Production_W": 5000,
        "GridFeedIn_W": 3000,
        "SoC": 80,
        "SystemStatus": 1,
    }


@pytest.fixture
def mock_weather_response():
    """Mock response data for weather API."""
    return {
        # Simulate sunrise 12 hours ago and sunset 2 hours from now
        "sys": {
            "sunrise": int((datetime.now() - timedelta(hours=12)).timestamp()),
            "sunset": int((datetime.now() + timedelta(hours=2)).timestamp()),
        }
    }


@pytest.fixture
def app_with_mocks(mock_env_vars, mock_goe_service_response, mock_sonnen_response, mock_weather_response):
    """Create an EnergyManagementApplication instance with all HTTP calls mocked."""
    with patch.dict(os.environ, mock_env_vars), \
         patch('requests.get') as mock_get, \
         patch('requests.put') as mock_put, \
         patch('services.wago_energy_meter.ModbusSerialClient') as mock_modbus, \
         patch('services.sgready_device_service.GPIO') as mock_gpio:
        
        # Setup mock HTTP responses
        def mock_get_handler(url, **kwargs):
            response = Mock()
            response.status_code = 200
            
            # Route to appropriate mock data
            if "openweathermap.org" in url:
                response.json.return_value = mock_weather_response
            elif "gocharger" in url or "goe" in url.lower():
                filter_param = kwargs.get('params', {}).get('filter') if 'params' in kwargs else None
                if filter_param and filter_param in mock_goe_service_response:
                    response.json.return_value = {filter_param: mock_goe_service_response[filter_param]}
                else:
                    response.json.return_value = mock_goe_service_response
            else:  # Sonnen battery
                response.json.return_value = mock_sonnen_response
            
            return response
        
        mock_get.side_effect = mock_get_handler
        
        def mock_put_handler(url, **kwargs):
            response = Mock()
            response.status_code = 200
            response.json.return_value = {"status": "ok"}
            return response
        
        mock_put.side_effect = mock_put_handler
        
        # Setup Modbus mock
        mock_client = Mock()
        mock_client.connect.return_value = True
        mock_client.read_holding_registers.return_value = Mock(
            isError=Mock(return_value=False),
            registers=[0x4370, 0x0000]  # Example 32-bit float for total power
        )
        mock_modbus.return_value = mock_client
        
        # Setup GPIO mock
        mock_gpio.setmode = Mock()
        mock_gpio.setup = Mock()
        mock_gpio.output = Mock()
        
        app = EnergyManagementApplication()
        app.energy_meter.client = mock_client
        
        yield app


class TestEnergyManagementApplicationInitialization:
    """Test application initialization and service setup."""
    
    def test_application_initializes_successfully(self, app_with_mocks):
        """Test that the application initializes without errors."""
        assert app_with_mocks is not None
        assert app_with_mocks.db_service is not None
        assert app_with_mocks.goe_service is not None
        assert app_with_mocks.sonnen_battery_service is not None
        assert app_with_mocks.weather_service is not None
    
    def test_control_structure_initialized(self, app_with_mocks):
        """Test that control structure is initialized with correct values."""
        assert app_with_mocks.control_structure is not None
        assert app_with_mocks.control_structure.START_WW_WAIT_TIME == 5
        assert app_with_mocks.control_structure.START_CAR_CHARGING_WAIT_TIME == 7
        assert app_with_mocks.control_structure.STOP_CAR_CHARGING_WAIT_TIME == 15
        assert app_with_mocks.control_structure.NON_USED_ENERGY_BUFFER == 500
    
    def test_goe_service_initialized_with_correct_values(self, app_with_mocks, mock_goe_service_response):
        """Test that GoE service has correct charger info."""
        assert app_with_mocks.goe_service.CHARGER_SN == mock_goe_service_response["sse"]
        assert app_with_mocks.goe_service.CHARGER_NAME == mock_goe_service_response["fna"]


class TestCarChargingReportEntry:
    """Test car charging report creation and management."""
    
    def test_create_car_charging_report_entry_start(self, app_with_mocks):
        """Test creating a new car charging report entry."""
        session_id = app_with_mocks.create_car_charging_report_entry_start()
        
        assert isinstance(session_id, int)
        assert session_id > 0
    
    def test_create_and_end_car_charging_report_entry(self, app_with_mocks):
        """Test creating and ending a car charging report entry."""
        # Create entry
        session_id = app_with_mocks.create_car_charging_report_entry_start()
        
        # End entry
        app_with_mocks.create_car_charging_report_entry_end(session_id)
        
        # Verify data in database
        conn = __import__('sqlite3').connect(app_with_mocks.db_service.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT id, start_time, end_time FROM car_charging_report WHERE id = ?', (session_id,))
        result = cursor.fetchone()
        conn.close()
        
        assert result is not None
        assert result[0] == session_id
        assert result[1] is not None  # start_time
        assert result[2] is not None  # end_time


class TestGoEServiceIntegration:
    """Test integration with GoE charger API."""
    
    def test_get_last_user_with_name(self, app_with_mocks):
        """Test retrieving last user with name."""
        user_id, user_name = app_with_mocks.goe_service.get_last_user_with_name()
        
        assert isinstance(user_id, int)
        assert isinstance(user_name, str)
        assert user_id == 2  # From mock (dynamic charging user)
        assert user_name == "Dynamic Charging User"
    
    def test_get_car_status(self, app_with_mocks):
        """Test retrieving car status."""
        status = app_with_mocks.goe_service.get_car_status()
        
        assert isinstance(status, CarStatus)
        assert status == CarStatus.IDLE
    
    def test_get_charging_current(self, app_with_mocks):
        """Test retrieving charging current."""
        current = app_with_mocks.goe_service.get_charging_current()
        
        assert isinstance(current, int)
        assert current == 10
    
    def test_get_total_power_average(self, app_with_mocks):
        """Test retrieving total power average."""
        power = app_with_mocks.goe_service.get_total_power_average()
        
        assert isinstance(power, int)
        assert power == 7500


class TestSonnenBatteryIntegration:
    """Test integration with Sonnen battery API."""
    
    def test_sonnen_status_refresh(self, app_with_mocks, mock_sonnen_response):
        """Test refreshing Sonnen battery status."""
        app_with_mocks.sonnen_battery_service.refresh_status()
        
        assert app_with_mocks.sonnen_battery_service.sonnen_status is not None
        assert app_with_mocks.sonnen_battery_service.get_energy_production() == mock_sonnen_response["Production_W"]
        assert app_with_mocks.sonnen_battery_service.get_energy_consumption() == mock_sonnen_response["Consumption_W"]
    
    def test_energy_status_saved_to_database(self, app_with_mocks):
        """Test that energy status is saved to the database when battery status is refreshed."""
        app_with_mocks.sonnen_battery_service.refresh_status()
        
        # Retrieve energy status from database
        energy_statuses = app_with_mocks.db_service.get_energy_status_time_series(10)
        
        assert len(energy_statuses) > 0
        assert energy_statuses[-1].production > 0
        assert energy_statuses[-1].consumption > 0


class TestDatabasePersistence:
    """Test database persistence and data integrity."""
    
    def test_database_created(self, app_with_mocks):
        """Test that the test database is created."""
        assert os.path.exists(app_with_mocks.db_service.db_path)
    
    def test_charger_action_creation(self, app_with_mocks):
        """Test creating a charger action in the database."""
        action = app_with_mocks.db_service.create_goe_action(ChargerAction.REQUEST_DYNAMIC_CHARGING)
        
        assert action is not None
    
    def test_charger_action_with_session_id(self, app_with_mocks):
        """Test creating a charger action with session ID."""
        session_id = 123
        action = app_with_mocks.db_service.create_goe_action(ChargerAction.DYNAMIC_CHARGING, session_id)
        
        assert action is not None
    
    def test_energy_status_time_series(self, app_with_mocks):
        """Test retrieving energy status time series from database."""
        # Add some test data
        app_with_mocks.db_service.create_energy_status(production=5000, consumption=2000, feed_in=3000)
        app_with_mocks.db_service.create_energy_status(production=5500, consumption=2100, feed_in=3400)
        
        # Retrieve time series
        energy_statuses = app_with_mocks.db_service.get_energy_status_time_series(60)
        
        assert len(energy_statuses) >= 2
        assert all(isinstance(e.timestamp, datetime) for e in energy_statuses)
        assert all(isinstance(e.production, int) for e in energy_statuses)


class TestUpdateCarCharging:
    """Test car charging update logic."""
    
    def test_update_car_charging_no_action_not_allowed(self, app_with_mocks):
        """Test update_car_charging when charging is not allowed."""
        with patch.object(app_with_mocks.goe_service, 'is_car_charging_allowed', return_value=False), \
             patch.object(app_with_mocks.goe_service, 'is_car_charging', return_value=False), \
             patch.object(app_with_mocks.goe_service, 'is_car_charging_complete', return_value=False):
            
            action = app_with_mocks.update_car_charging(5, 15)
            
            assert action == ChargerAction.NO_ACTION
    
    def test_update_car_charging_fixed_user_max_charging(self, app_with_mocks):
        """Test car charging with fixed user (max charging)."""
        with patch.object(app_with_mocks.goe_service, 'is_car_charging_allowed', return_value=True), \
             patch.object(app_with_mocks.goe_service, 'is_car_charging', return_value=False), \
             patch.object(app_with_mocks.goe_service, 'is_car_charging_complete', return_value=False), \
             patch.object(app_with_mocks.goe_service, 'is_dynamic_charging_user', return_value=False), \
             patch.object(app_with_mocks.goe_service, 'get_last_user_with_name', return_value=(1, "Fixed Charging User")), \
             patch.object(app_with_mocks.goe_service, 'get_total_power_average', return_value=8000), \
             patch.object(app_with_mocks.goe_service, 'set_max_charging_power', return_value=True), \
             patch.object(app_with_mocks.sonnen_battery_service, 'set_disable_discharge'):
            
            action = app_with_mocks.update_car_charging(5, 15)
            
            assert action == ChargerAction.MAX_CHARGING


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
