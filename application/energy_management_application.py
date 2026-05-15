import os

from dataclasses import dataclass
from time import sleep
from datetime import datetime, timedelta
from dotenv import load_dotenv
from services.database_service import DBService
from services.database_service import ChargerAction
from services.goe_service import GoEService
from services.sonnen_battery_service import SonnenBatteryService
from services.weather_service import WeatherService
from services.sgready_device_service import SGReadyDeviceService

@dataclass(frozen=True)
class ControlStructure:
    """Data class for defining control structures for the energy management application.
    This can be used to define rules for when to turn on or off certain devices based on the current energy status, weather conditions, and Sonnen battery status.
    """
    START_WW_WAIT_TIME: int = 5
    START_HEATING1_WAIT_TIME: int = 5
    START_HEATING2_WAIT_TIME: int = 5
    START_CAR_CHARGING_WAIT_TIME: int = 5
    STOP_WW_WAIT_TIME: int = 15
    STOP_HEATING1_WAIT_TIME: int = 10
    STOP_HEATING2_WAIT_TIME: int = 5
    STOP_CAR_CHARGING_WAIT_TIME: int = 15
    NON_USED_ENERGY_BUFFER: int = 1000  # Buffer in watts to account for fluctuations in energy production and consumption. This means that the application will only turn on devices if there is at least this much excess energy available, and will only turn off devices if the energy deficit is at least this much.

class EnergyManagementApplication:
    def __init__(self):
        load_dotenv()  # Load environment variables from .env file
        self.db_service = DBService(db_path=os.getenv("DATABASE_PATH"))
        self.weather_service = WeatherService(api_key=os.getenv("OPENWEATHER_API_KEY"), latitude=os.getenv("OPENWEATHER_LAT"), longitude=os.getenv("OPENWEATHER_LON"))
        self.sonnen_battery_service = SonnenBatteryService(self.db_service, host=os.getenv("SONNEN_BATTERY_HOST"), port=os.getenv("SONNEN_BATTERY_PORT"), api_key=os.getenv("SONNEN_BATTERY_API_KEY"))
        self.warm_water_heatpump_service = SGReadyDeviceService(self.db_service, int(os.getenv("RELAY_PIN_WW")), "Weishaupt Warm Water Heat Pump", int(os.getenv("WW_ENERGY_CONSUMPTION")))
        self.heating_heatpump_service1 = SGReadyDeviceService(self.db_service, int(os.getenv("RELAY_PIN_HEATING1")), "Panasonic Heating Heat Pump 1", int(os.getenv("HEATING1_ENERGY_CONSUMPTION")))
        self.heating_heatpump_service2 = SGReadyDeviceService(self.db_service, int(os.getenv("RELAY_PIN_HEATING2")), "Panasonic Heating Heat Pump 2", int(os.getenv("HEATING2_ENERGY_CONSUMPTION")))
        self.goe_service = GoEService(host=os.getenv("GOE_HOST"), api_key=os.getenv("GOE_API_KEY"), fixed_charging_user=int(os.getenv("GOE_FIXED_CHARGING_USER")), dynamic_charging_user=int(os.getenv("GOE_DYNAMIC_CHARGING_USER")))
        self._init_control_structure()

    def _init_control_structure(self):
        """Initializes the control structure for the energy management application."""
        self.control_structure = ControlStructure(
            START_WW_WAIT_TIME = int(os.getenv("START_WW_WAIT_TIME")),
            START_HEATING1_WAIT_TIME = int(os.getenv("START_HEATING1_WAIT_TIME")),
            START_HEATING2_WAIT_TIME = int(os.getenv("START_HEATING2_WAIT_TIME")),
            START_CAR_CHARGING_WAIT_TIME = int(os.getenv("START_CAR_CHARGING_WAIT_TIME")),
            STOP_WW_WAIT_TIME = int(os.getenv("STOP_WW_WAIT_TIME")),
            STOP_HEATING1_WAIT_TIME = int(os.getenv("STOP_HEATING1_WAIT_TIME")),
            STOP_HEATING2_WAIT_TIME = int(os.getenv("STOP_HEATING2_WAIT_TIME")),
            STOP_CAR_CHARGING_WAIT_TIME = int(os.getenv("STOP_CAR_CHARGING_WAIT_TIME")),
            NON_USED_ENERGY_BUFFER = int(os.getenv("NON_USED_ENERGY_BUFFER"))
        )

    def run(self):
        """Main loop of the energy management application. This will continuously monitor the energy status, weather conditions, and Sonnen battery status, and control the devices accordingly."""
        while True:
            # Refresh the status of the Sonnen battery
            self.sonnen_battery_service.refresh_status()

            # Turn on devices if there is enough excess energy available, starting with the most important device (warm water heat pump) and then the heating heat pumps. The car charging will be turned on if there is enough excess energy available after turning on the heat pumps.
            # WW heatpump
            if not self.turn_on_heatpump(self.warm_water_heatpump_service, self.control_structure.START_WW_WAIT_TIME):
                # Heating 1
                if not self.turn_on_heatpump(self.heating_heatpump_service1, self.control_structure.START_HEATING1_WAIT_TIME):
                    # Heating 2
                    self.turn_on_heatpump(self.heating_heatpump_service2, self.control_structure.START_HEATING2_WAIT_TIME)

            self.update_car_charging(self.control_structure.START_CAR_CHARGING_WAIT_TIME, self.control_structure.STOP_CAR_CHARGING_WAIT_TIME)

            # Check whether or no the heatpumps need to be turned off due to insufficient excess energy. We will only turn off the heat pumps if they are currently on and there is not enough excess energy available for at least the specified stop wait time.
            if self.warm_water_heatpump_service.is_on() and self.sonnen_battery_service.get_grid_feed_in_minimum(self.control_structure.STOP_WW_WAIT_TIME) + self.control_structure.NON_USED_ENERGY_BUFFER < self.warm_water_heatpump_service.energy_consumption:
                print(f"Turning off {self.warm_water_heatpump_service.device_name} due to insufficient excess energy. Minimum grid feed-in in the last {self.control_structure.STOP_WW_WAIT_TIME} minutes: {self.sonnen_battery_service.get_grid_feed_in_minimum(self.control_structure.STOP_WW_WAIT_TIME)} W, energy consumption of the device: {self.warm_water_heatpump_service.energy_consumption} W")
                self.warm_water_heatpump_service.turn_off()
            if self.heating_heatpump_service1.is_on() and self.sonnen_battery_service.get_grid_feed_in_minimum(self.control_structure.STOP_HEATING1_WAIT_TIME) + self.control_structure.NON_USED_ENERGY_BUFFER < self.heating_heatpump_service1.energy_consumption:
                print(f"Turning off {self.heating_heatpump_service1.device_name} due to insufficient excess energy. Minimum grid feed-in in the last {self.control_structure.STOP_HEATING1_WAIT_TIME} minutes: {self.sonnen_battery_service.get_grid_feed_in_minimum(self.control_structure.STOP_HEATING1_WAIT_TIME)} W, energy consumption of the device: {self.heating_heatpump_service1.energy_consumption} W")
                self.heating_heatpump_service1.turn_off()
            if self.heating_heatpump_service2.is_on() and self.sonnen_battery_service.get_grid_feed_in_minimum(self.control_structure.STOP_HEATING2_WAIT_TIME) + self.control_structure.NON_USED_ENERGY_BUFFER < self.heating_heatpump_service2.energy_consumption:
                print(f"Turning off {self.heating_heatpump_service2.device_name} due to insufficient excess energy. Minimum grid feed-in in the last {self.control_structure.STOP_HEATING2_WAIT_TIME} minutes: {self.sonnen_battery_service.get_grid_feed_in_minimum(self.control_structure.STOP_HEATING2_WAIT_TIME)} W, energy consumption of the device: {self.heating_heatpump_service2.energy_consumption} W")
                self.heating_heatpump_service2.turn_off()

            sleep(60)  # Sleep for 60 seconds before checking again
    
    def turn_on_heatpump(self, device: SGReadyDeviceService, wait_time: int) -> bool:
        """
        Turn on a heat pump.
        Args:
            device: The SGReadyDeviceService instance representing the heat pump to be turned on.
            wait_time: The time in minutes to look back for the minimum grid feed-in value to determine if there is enough excess energy to turn on the device.
        Returns:
            True if the device was turned on, False otherwise.
        """
        if not device.is_on:
            min = self.sonnen_battery_service.get_grid_feed_in_minimum(wait_time)
            if min - self.control_structure.NON_USED_ENERGY_BUFFER >= device.energy_consumption:
                print(f"Turning on {device.device_name}. Minimum grid feed-in in the last {wait_time} minutes: {min} W, energy consumption of the device: {device.energy_consumption} W")
                device.turn_on()
                return True
        
        print(f"Not turning on {device.device_name}. Minimum grid feed-in in the last {wait_time} minutes: {self.sonnen_battery_service.get_grid_feed_in_minimum(wait_time)} W, energy consumption of the device: {device.energy_consumption} W")
        return False
        
    def update_car_charging(self, start_wait_time: int, stop_wait_time: int) -> ChargerAction:
        """Update on car charging through the GoE API.
        Args:
            start_wait_time: The time in minutes to look back for the minimum grid feed-in value to determine if there is enough excess energy to turn on the car charging.
            stop_wait_time: The time in minutes to look back for the minimum grid feed-in value to determine if there is enough excess energy to turn off the car charging.
        Returns:
            The charger action that was actually performed.
        """
        if self.goe_service.is_car_charging_allowed() or self.goe_service.is_car_charging() or self.goe_service.is_car_charging_complete():
            print(f"Car charging is currently allowed or the car is charging or charging was completed.")
        
            if self.goe_service.is_car_charging_complete():
                print(f"Car charging was completed.")
                # Turn on the battery discharge if the charger is not charging with significant power.
                self.sonnen_battery_service.set_enable_discharge()
                self.db_service.create_goe_action(ChargerAction.CHARGING_STOPPED)
                return ChargerAction.CHARGING_STOPPED
            elif self.goe_service.is_dynamic_charging_user():
                print(f"The last authenticated user is the dynamic charging user.")
                
                min_power = self.sonnen_battery_service.get_grid_feed_in_minimum(self.control_structure.START_CAR_CHARGING_WAIT_TIME)
                available_power = min_power - self.control_structure.NON_USED_ENERGY_BUFFER + self.goe_service.get_current_charging_power()
                print(f"Minimum grid feed-in in the last {self.control_structure.START_CAR_CHARGING_WAIT_TIME} minutes: {min_power} W, available power for car charging after buffer: {available_power} W, current car charging power: {self.goe_service.get_configured_charging_power()} W")
                if available_power >= self.goe_service.MINIMUM_ENERGY_CONSUMPTION:
                    # wait x minutes before changing the car charging power to make sure that the energy status is stable and there is actually enough excess energy available for car charging. This is to avoid rapidly turning on and off the car charging due to fluctuations in energy production and consumption.
                    self.db_service.create_goe_action(ChargerAction.REQUEST_DYNAMIC_CHARGING)

                    charging_request_time = self.db_service.get_goe_action_timestamp(ChargerAction.REQUEST_DYNAMIC_CHARGING)
                    if charging_request_time is not None:
                        time_since_action = (datetime.now() - charging_request_time).total_seconds() / 60
                        if time_since_action >= self.control_structure.START_CAR_CHARGING_WAIT_TIME:
                            if self.goe_service.set_charging_power(available_power):
                                self.db_service.create_goe_action(ChargerAction.DYNAMIC_CHARGING)
                                return ChargerAction.DYNAMIC_CHARGING

                    print(f"Waiting {self.control_structure.START_CAR_CHARGING_WAIT_TIME - time_since_action:.2f} more minutes before setting the car charging power to {available_power} W to make sure that the energy status is stable.")
                    return ChargerAction.REQUEST_DYNAMIC_CHARGING
                else:
                    print(f"Not enough excess energy available to turn on car charging. Available power for car charging after buffer: {available_power} W, current car charging power: {self.goe_service.get_configured_charging_power()} W")
                    # wait x minutes before switching off the car charging to make sure that the energy status is stable and there is actually not enough excess energy available. This is to avoid rapidly turning on and off the car charging due to fluctuations in energy production and consumption.
                    self.db_service.create_goe_action(ChargerAction.REQUEST_STOP_CHARGING)

                    stop_charging_time = self.db_service.get_goe_action_timestamp(ChargerAction.REQUEST_STOP_CHARGING)
                    if stop_charging_time is not None:
                        time_since_action = (datetime.now() - stop_charging_time).total_seconds() / 60
                        if time_since_action >= self.control_structure.STOP_CAR_CHARGING_WAIT_TIME:
                            if self.goe_service.set_charging_power(0):
                                self.db_service.create_goe_action(ChargerAction.CHARGING_STOPPED)
                                return ChargerAction.CHARGING_STOPPED

                    print(f"Waiting {self.control_structure.STOP_CAR_CHARGING_WAIT_TIME - time_since_action:.2f} more minutes before stopping the car charging to make sure that the energy status is stable.")
                    return ChargerAction.REQUEST_STOP_CHARGING
                
                # If the last authenticated user is the dynamic charging user, we will control the car charging based on the current energy status and the control structure.
                # if self.goe_service.is_car_charging_allowed():
                #     # return self.turn_on_heatpump(self.goe_service, start_wait_time)
                # else:
                #     # Check if we need to turn off the car charging due to insufficient excess energy. We will only turn off the car charging if it is currently on and there is not enough excess energy available for at least the specified stop wait time.
                #     if self.goe_service.is_car_charging() and self.sonnen_battery_service.get_grid_feed_in_minimum(stop_wait_time) + self.control_structure.NON_USED_ENERGY_BUFFER < self.goe_service.energy_consumption:
                #         self.goe_service.turn_off()
                #         return True
            else:
                print(f"The last authenticated user is the fixed charging user.")
                # If the last authenticated user is the fixed charging user, we will turn on the car charging with max. power and disable discharging of the battery.
                # TODO check the size of tpa (1/120 of the loaded energy?)
                if self.goe_service.get_total_power_average() > 5:
                    # Only turn off the battery if the charger is actually charging with a significant amount of power. 
                    print(f"Car is charging with significant power ({self.goe_service.get_total_power_average()} W), turning off battery discharge to prioritize car charging.")
                    self.sonnen_battery_service.set_disable_discharge()
                else:
                    # Turn on the battery discharge if the charger is not charging with significant power.
                    print(f"Car is not charging with significant power ({self.goe_service.get_total_power_average()} W), enabling battery discharge.")
                    self.sonnen_battery_service.set_enable_discharge()

                if self.goe_service.is_car_charging() or self.goe_service.is_car_charging_allowed():
                    if self.goe_service.set_max_charging_power():
                        print(f"Car charging set to max power.")
                        self.db_service.create_goe_action(ChargerAction.MAX_CHARGING)
                        return ChargerAction.MAX_CHARGING
                
                print(f"This code should not be reached: requesting max charging but setting max charging was not successful.")
                self.db_service.create_goe_action(ChargerAction.REQUEST_MAX_CHARGING)
                return ChargerAction.REQUEST_MAX_CHARGING
                
        else:
            print(f"Car charging is currently not allowed and the car is not charging.")
            self.sonnen_battery_service.set_enable_discharge()
            self.db_service.create_goe_action(ChargerAction.NO_ACTION)
            return ChargerAction.NO_ACTION
    