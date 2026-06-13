import logging
import json
import requests
from dataclasses import dataclass

from services.database_service import DBService, EnergyStatus

log = logging.getLogger(__name__)

@dataclass(frozen=True)
class EnergyStatusWithAverageAvailablePower(EnergyStatus):
    average_available_power: int | None
    average_battery_feed_in: int | None
    average_car_charging: int | None

class SonnenBatteryService:
    def __init__(self, db_service: DBService, host: str, port: int, api_key: str, non_used_energy_buffer: int):
        self.db_service = db_service
        self.host = host
        self.port = port
        self.api_key = api_key
        self.sonnen_status: json = None
        self.NON_USED_ENERGY_BUFFER = non_used_energy_buffer
        self._query_status(update_db=False) # fetch initial status without saving to db, to have the initial status available for the first call of get_battery_status() and to avoid saving an initial empty status to the db.

    def _query_status(self, car_charging: int = None, update_db: bool = True):
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
                # keep the last status
        except Exception as e:
            # keep the last statuss
            log.error(f"Error fetching status of Sonnen battery: {e}")
            
        if update_db:
            self._save_status_to_db(car_charging)

    def _save_status_to_db(self, car_charging: int = None):
        """Save the current status of the Sonnen battery to the database."""
        if self.sonnen_status:
            self.db_service.create_energy_status(
                production=self.get_energy_production(),
                consumption=self.get_energy_consumption(),
                feed_in=self.get_grid_feed(),
                battery_feed_in=self.get_battery_feed(),
                car_charging=car_charging
            )

    # This method can be called to refresh the status of the Sonnen battery.
    # It will call the _query_status method to fetch the latest status from the API.
    def refresh_status(self, car_charging: int = None, update_db: bool = True):
        self._query_status(car_charging, update_db)

    def get_energy_status_with_available_power_time_series(self, minutes: int, moving_average_interval: int, battery_average_interval: int, car_charging_average_interval: int = 5) -> list[EnergyStatusWithAverageAvailablePower]:
        """Get a time series of energy status values with average available power for the last specified number of minutes."""
        energy_status_series = self.get_energy_status_time_series(minutes + moving_average_interval)

        feed_in_series = [entry.feed_in for entry in energy_status_series]
        battery_feed_in_series = [entry.battery_feed_in for entry in energy_status_series]

        interval = max(1, moving_average_interval)
        interval_battery = max(1, battery_average_interval)
        interval_car_charging = max(1, car_charging_average_interval)
        
        start_idx = max(0, len(energy_status_series) - minutes)
        end_idx = len(energy_status_series)

        energy_status_with_available_power_series = []
        for idx in range(start_idx, end_idx):
            energy_status = energy_status_series[idx]
            
            window_start_idx = max(0, idx - interval + 1)
            feed_in_window = feed_in_series[window_start_idx:idx + 1]
            
            battery_window_start_idx = max(0, idx - interval_battery + 1)
            battery_feed_in_window = battery_feed_in_series[battery_window_start_idx:idx + 1]

            car_charging_window_start_idx = max(0, idx - interval_car_charging + 1)
            car_charging_window = [entry.car_charging for entry in energy_status_series[car_charging_window_start_idx:idx + 1]]

            smoothed_feed_in = int(sum(feed_in_window) / len(feed_in_window)) if feed_in_window else 0
            smoothed_battery_feed_in = int(sum(battery_feed_in_window) / len(battery_feed_in_window)) if battery_feed_in_window else 0
            smoothed_car_charging = int(sum(car_charging_window) / len(car_charging_window)) if car_charging_window else 0
            adjusted_battery_feed_in = smoothed_battery_feed_in if smoothed_battery_feed_in <= 0 else int((3.0 * smoothed_battery_feed_in) / 4.0)
            average_available_power = smoothed_feed_in + smoothed_car_charging + adjusted_battery_feed_in - self.NON_USED_ENERGY_BUFFER

            energy_status_with_available_power_series.append(
                EnergyStatusWithAverageAvailablePower(
                    timestamp=energy_status.timestamp,
                    production=energy_status.production,
                    consumption=energy_status.consumption,
                    feed_in=energy_status.feed_in,
                    battery_feed_in=energy_status.battery_feed_in,
                    car_charging=energy_status.car_charging,
                    average_available_power=average_available_power,
                    average_battery_feed_in=smoothed_battery_feed_in,
                    average_car_charging=smoothed_car_charging
                )
            )

        log.debug(f"Energy status with average available power time series for the last {minutes} minutes: {[entry.average_available_power for entry in energy_status_with_available_power_series]}")
        return energy_status_with_available_power_series

    def get_energy_status_time_series(self, minutes: int) -> list[EnergyStatus]:
        """Get a time series of energy status values for the last specified number of minutes."""
        return self.db_service.get_energy_status_time_series(minutes)

    def get_grid_feed_in_minimum(self, minutes: int) -> int:
        """Get the minimum grid feed-in value for the last specified number of minutes."""
        time_series = self.get_energy_status_time_series(minutes)
        return min(entry.feed_in for entry in time_series)

    def get_grid_feed_in_average(self, minutes: int) -> int:
        """Get the average grid feed-in value in W for the last specified number of minutes."""
        time_series = self.get_energy_status_time_series(minutes)
        avg = int(sum(entry.feed_in for entry in time_series) / len(time_series) if time_series else 0)
        log.debug(f"Grid feed-in time series for the last {minutes} minutes: {[entry.feed_in for entry in time_series]}; average: {avg} W")
        return avg

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
        """Power feed-in to the battery (charging). Negative value = discharging the battery."""
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
        ret = self.sonnen_status["OperatingMode"] == "1"
        log.debug(f"Battery discharge is currently {'disabled' if ret else 'enabled'} (OperatingMode: {self.sonnen_status['OperatingMode']})")
        return ret
    
    def _set_discharge_off(self, disable: bool):
        try:
            url = f"http://{self.host}/api/v2/configurations"
            headers = {
                "Auth-Token": f"{self.api_key}",
                "Content-Type": "application/json"
            }
            if disable:
                # turn discharge off by setting the operating mode to 1
                log.info("Disabling battery discharge to prioritize car charging.")
                data = {"EM_OperatingMode": 1}
            else:
                # turn discharge on by setting the operating mode to 2 (normal mode)
                log.info("Enabling battery discharge to allow using battery energy for home consumption.")
                data = {"EM_OperatingMode": 2}
            
            response = requests.put(url, headers=headers, json=data)
            if response.status_code == 200:
                log.debug(f"Successfully set disable discharge to {disable}")
            else:
                log.error(f"Error setting disable discharge: {response.status_code} - {response.text}")
        except Exception as e:
            log.error(f"Error setting disable discharge: {e}")