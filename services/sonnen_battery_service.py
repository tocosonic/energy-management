import logging
import json
import requests

from services.database_service import DBService, EnergyStatus

log = logging.getLogger(__name__)

class SonnenBatteryService:
    def __init__(self, db_service: DBService, host, port, api_key):
        self.db_service = db_service
        self.host = host
        self.port = port
        self.api_key = api_key
        self.sonnen_status: json = None
        self._query_status()

    def _query_status(self):
        try:
            url = f"http://{self.host}:{self.port}/api/v1/status"
            headers = {
                "Authorization": f"Bearer {self.api_key}"
            }
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                self.sonnen_status = response.json()
            else:                
                log.error(f"Error fetching status of Sonnen battery: {response.status_code} - {response.text}")
                self.sonnen_status = None
        except Exception as e:
            log.error(f"Error fetching status of Sonnen battery: {e}")
            self.sonnen_status = None
            
        self._save_status_to_db()

    def _save_status_to_db(self):
        """Save the current status of the Sonnen battery to the database."""
        if self.sonnen_status:
            self.db_service.create_energy_status(
                production=self.get_energy_production(),
                consumption=self.get_energy_consumption(),
                feed_in=self.get_grid_feed()
            )

    # This method can be called to refresh the status of the Sonnen battery.
    # It will call the _query_status method to fetch the latest status from the API.
    def refresh_status(self):
        self._query_status()

    def get_energy_status_time_series(self, minutes: int) -> list[EnergyStatus]:
        """Get a time series of energy status values for the last specified number of minutes."""
        return self.db_service.get_energy_status_time_series(minutes)

    def get_grid_feed_in_minimum(self, minutes: int) -> int:
        """Get the minimum grid feed-in value for the last specified number of minutes."""
        time_series = self.get_energy_status_time_series(minutes)
        return min(entry.feed_in for entry in time_series)

    # Status of the Sonnen battery as JSON structure. This includes the current battery level, energy production, and energy consumption.
    def get_battery_status(self) -> json:
        return self.sonnen_status

    def get_energy_production(self) -> int:
        return self.sonnen_status["Production_W"] if self.sonnen_status else None

    def get_energy_consumption(self) -> int:
        return self.sonnen_status["Consumption_Avg"] if self.sonnen_status else None
    
    def get_grid_feed(self) -> int:
        return self.sonnen_status["GridFeedIn_W"] if self.sonnen_status else None
    
    def get_battery_feed(self) -> int:
        return -self.sonnen_status["Pac_total_W"] if self.sonnen_status else None
    
    def get_battery_level(self) -> int:
        return self.sonnen_status["USOC"] if self.sonnen_status else None
    
    def set_disable_discharge(self):
        """
        Disable discharging of the battery, which means that the battery will not provide any energy
        even if it is charged. This is useful to prevent discharging the battery when the car is charging
        with max power to avoid sucking the battery empty.
        """
        if not self.is_discharge_disabled():
            self._set_discharge_off(True)
        
    def set_enable_discharge(self):
        """Enable discharging of the battery, allowing it to provide energy for home consumption."""
        if self.is_discharge_disabled():
           self._set_discharge_off(False)
    
    def is_discharge_disabled(self) -> bool:
        """Check if discharging of the battery is currently disabled."""
        return self.sonnen_status["OperatingMode"] == 1
    
    def _set_discharge_off(self, disable: bool):
        try:
            url = f"http://{self.host}/api/v2/configurations"
            headers = {
                "Auth-Token": f"{self.api_key}",
                "Content-Type": "application/json"
            }
            if disable:
                # turn discharge off by setting the operating mode to 1
                data = {"EM_OperatingMode": 1}
            else:
                # turn discharge on by setting the operating mode to 2 (normal mode)
                data = {"EM_OperatingMode": 2}
            
            response = requests.put(url, headers=headers, json=data)
            if response.status_code == 200:
                log.debug(f"Successfully set disable discharge to {disable}")
            else:
                log.error(f"Error setting disable discharge: {response.status_code} - {response.text}")
        except Exception as e:
            log.error(f"Error setting disable discharge: {e}")