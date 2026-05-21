import os

from dataclasses import dataclass
from time import sleep
from datetime import datetime, timedelta
from dotenv import load_dotenv
from services.database_service import DBService
from services.database_service import ChargerAction, HeatpumpAction
from services.goe_service import GoEService
from services.sonnen_battery_service import SonnenBatteryService
from services.weather_service import WeatherService
from services.sgready_device_service import SGReadyDeviceService
from services.panasonic_aquarea_service import PanasonicAquareaService
from services.wago_energy_meter import WagoEnergyMeter

@dataclass(frozen=True)
class ControlStructure:
    """Data class for defining control structures for the energy management application.
    This can be used to define rules for when to turn on or off certain devices based on the current energy status, weather conditions, and Sonnen battery status.
    """
    START_WW_WAIT_TIME: int = 5
    START_HEATING_WAIT_TIME: int = 5
    START_CAR_CHARGING_WAIT_TIME: int = 5
    STOP_WW_WAIT_TIME: int = 15
    STOP_HEATING_WAIT_TIME: int = 10
    STOP_CAR_CHARGING_WAIT_TIME: int = 15
    NON_USED_ENERGY_BUFFER: int = 1000  # Buffer in watts to account for fluctuations in energy production and consumption. This means that the application will only turn on devices if there is at least this much excess energy available, and will only turn off devices if the energy deficit is at least this much.

class EnergyManagementApplication:
    def __init__(self):
        load_dotenv()  # Load environment variables from .env file
        self.db_service = DBService(db_path=os.getenv("DATABASE_PATH"))
        self.weather_service = WeatherService(api_key=os.getenv("OPENWEATHER_API_KEY"), latitude=os.getenv("OPENWEATHER_LAT"), longitude=os.getenv("OPENWEATHER_LON"))
        self.sonnen_battery_service = SonnenBatteryService(self.db_service, host=os.getenv("SONNEN_BATTERY_HOST"), port=os.getenv("SONNEN_BATTERY_PORT"), api_key=os.getenv("SONNEN_BATTERY_API_KEY"))
        self.warm_water_heatpump_service = SGReadyDeviceService(self.db_service, int(os.getenv("RELAY_PIN_WW")), "Weishaupt Warm Water Heatpump", int(os.getenv("WW_ENERGY_CONSUMPTION")))
        self.heating_heatpump_service = PanasonicAquareaService(self.db_service, int(os.getenv("RELAY_PIN_HEATING1")), int(os.getenv("RELAY_PIN_HEATING2")), "Panasonic Heating Heatpump", int(os.getenv("HEATING1_ENERGY_CONSUMPTION")), int(os.getenv("HEATING2_ENERGY_CONSUMPTION")))
        self.goe_service = GoEService(host=os.getenv("GOE_HOST"), api_key=os.getenv("GOE_API_KEY"), fixed_charging_user=int(os.getenv("GOE_FIXED_CHARGING_USER")), dynamic_charging_user=int(os.getenv("GOE_DYNAMIC_CHARGING_USER")))
        self.energy_meter = WagoEnergyMeter(port=os.getenv("ENERGY_METER_PORT"), slave_id=int(os.getenv("ENERGY_METER_SLAVE_ID")), baudrate=int(os.getenv("ENERGY_METER_BAUDRATE")))
        self._init_control_structure()

    def _init_control_structure(self):
        """Initializes the control structure for the energy management application."""
        self.control_structure = ControlStructure(
            START_WW_WAIT_TIME = int(os.getenv("START_WW_WAIT_TIME")),
            START_HEATING_WAIT_TIME = int(os.getenv("START_HEATING_WAIT_TIME")),
            START_CAR_CHARGING_WAIT_TIME = int(os.getenv("START_CAR_CHARGING_WAIT_TIME")),
            STOP_WW_WAIT_TIME = int(os.getenv("STOP_WW_WAIT_TIME")),
            STOP_HEATING_WAIT_TIME = int(os.getenv("STOP_HEATING_WAIT_TIME")),
            STOP_CAR_CHARGING_WAIT_TIME = int(os.getenv("STOP_CAR_CHARGING_WAIT_TIME")),
            NON_USED_ENERGY_BUFFER = int(os.getenv("NON_USED_ENERGY_BUFFER"))
        )

    def run(self):
        """Main loop of the energy management application. This will continuously monitor the energy status, weather conditions, and Sonnen battery status, and control the devices accordingly."""
        while True:
            # Refresh the status of the Sonnen battery
            self.sonnen_battery_service.refresh_status()

            self.update_heatpump(self.heating_heatpump_service, self.control_structure.START_HEATING_WAIT_TIME, self.control_structure.STOP_HEATING_WAIT_TIME)
            self.update_heatpump(self.warm_water_heatpump_service, self.control_structure.START_WW_WAIT_TIME, self.control_structure.STOP_WW_WAIT_TIME)

            self.update_car_charging()

            sleep(60)  # Sleep for 60 seconds before checking again
    
    ######################
    # Heatpump Section
    ######################

    def update_heatpump(self, device: SGReadyDeviceService, start_wait_time: int, stop_wait_time: int) -> HeatpumpAction:
        """
        Update the status of a heat pump based on the current energy status and the control structure.
        Returns: The heatpump action that was actually performed.
        """
        
        min_power = self.sonnen_battery_service.get_grid_feed_in_minimum(start_wait_time)
        consumed_power = device.energy_consumption if device.is_on() else 0
        available_power = min_power - self.control_structure.NON_USED_ENERGY_BUFFER + consumed_power
        if available_power >= device.energy_consumption:
            if not device.is_on():
                print(f"{device.name} is currently off, but there is enough excess energy available to turn it on. Minimum grid feed-in in the last {start_wait_time} minutes: {min_power} W, available power for the device after buffer: {available_power} W, energy consumption of the device: {device.energy_consumption} W")
                device.turn_on()
                # return self.db_service.create_heatpump_action(device.relay_pin, device.name, HeatpumpAction.HEATPUMP_ON)
            else:
                print(f"{device.name} is currently on and there is enough excess energy available to keep it turned on. Minimum grid feed-in in the last {start_wait_time} minutes: {min_power} W, available power for the device after buffer: {available_power} W, energy consumption of the device: {device.energy_consumption} W")
                # return HeatpumpAction.HEATPUMP_ON
            return self.db_service.create_heatpump_action(device.relay_pin, device.name, HeatpumpAction.HEATPUMP_ON)
        else:
            print(f"Not enough excess energy available to turn on or keep on {device.name}. Minimum grid feed-in in the last {start_wait_time} minutes: {min_power} W, available power for the device after buffer: {available_power} W, energy consumption of the device: {device.energy_consumption} W")
            if device.is_on():
                print(f"Turning off {device.name} due to insufficient excess energy. Minimum grid feed-in in the last {stop_wait_time} minutes: {self.sonnen_battery_service.get_grid_feed_in_minimum(stop_wait_time)} W, energy consumption of the device: {device.energy_consumption} W")
                
                current_action = self.db_service.get_heatpump_action_by_relay_pin(device.relay_pin)
                if current_action in [HeatpumpAction.REQUEST_HEATPUMP_OFF, HeatpumpAction.HEATPUMP_ON, HeatpumpAction.REQUEST_HEATPUMP_ON]:
                    if current_action != HeatpumpAction.REQUEST_HEATPUMP_OFF:
                        self.db_service.create_heatpump_action(device.relay_pin, device.name, HeatpumpAction.REQUEST_HEATPUMP_OFF)

                    stop_time = self.db_service.get_heatpump_action_timestamp_by_heatpump_action(device.relay_pin, HeatpumpAction.REQUEST_HEATPUMP_OFF)
                    if stop_time is not None:
                        delta = datetime.now() - stop_time
                        elapsed_time = int(delta.total_seconds() / 60)
                        print(f"Time since requesting to stop the heatpump {device.name}: {delta.total_seconds() / 60:.2f} minutes")
                        if elapsed_time >= stop_wait_time:
                            print(f">>>> Stop wait time of {elapsed_time} minutes has passed since the last request to turn off {device.name}. Proceeding to turn off the device.")
                            device.turn_off()
                            return self.db_service.create_heatpump_action(device.relay_pin, device.name, HeatpumpAction.HEATPUMP_OFF)
                            
                        return HeatpumpAction.REQUEST_HEATPUMP_OFF
                    else:
                        print(f"No previous request to turn off {device.name} found.")
                        return HeatpumpAction.REQUEST_HEATPUMP_OFF
                else:
                    print(f"Current action for {device.name} is {current_action}, so no need to request to turn off the device now.")
                    return HeatpumpAction.NO_ACTION
                
            print(f"{device.name} is currently off, so no need to turn it off due to insufficient excess energy.")
            return HeatpumpAction.NO_ACTION

    ######################
    # Car Charging Section
    ######################
            
    def check_and_process_user_change(self, current_action_user: int, authenticated_user: int):
        """
        Check if there was a change in the authenticated user for the GoE API and process it accordingly. This is relevant for
        the car charging control, because we want to apply different control rules depending on whether the fixed charging user
        or the dynamic charging user is authenticated.
        """
        
        print(f"##### User ID of the current action: {current_action_user}, ID of the authenticated user: {authenticated_user}")
        
        if current_action_user != None and authenticated_user != None and current_action_user != authenticated_user:
            print(f"Authenticated user for GoE API has changed from user ID {current_action_user} to user ID {authenticated_user}. Processing user change.")
            self.process_charging_finished()
        
    def update_car_charging(self) -> ChargerAction:
        """Update on car charging through the GoE API.
        Args:
            start_wait_time: The time in minutes to look back for the minimum grid feed-in value to determine if there is enough excess energy to turn on the car charging.
            stop_wait_time: The time in minutes to look back for the minimum grid feed-in value to determine if there is enough excess energy to turn off the car charging.
        Returns:
            The charger action that was actually performed.
        """
        current_user = self.goe_service.get_authenticated_user()
        self.check_and_process_user_change(self.db_service.get_goe_action_user_id(), current_user)

        if self.goe_service.is_car_charging_allowed() or self.goe_service.is_car_charging() or self.goe_service.is_car_charging_complete():
            print(f"Car charging is currently allowed or the car is charging or charging was completed.")
        
            if self.goe_service.is_car_charging_complete():
                print(f"Car charging was completed.")
                return self.process_charging_finished()

            elif self.goe_service.is_dynamic_charging_user():
                print(f"The last authenticated user is the dynamic charging user.")
                
                # min_power already takes the charging-wait-time into account, because the method get_grid_feed_in_minimum looks back for the specified time to determine the minimum grid feed-in value. So we can directly use the returned minimum grid feed-in value to determine if there is enough excess energy available to turn on the car charging or if we need to turn off the car charging due to insufficient excess energy.
                min_power = self.sonnen_battery_service.get_grid_feed_in_minimum(self.control_structure.START_CAR_CHARGING_WAIT_TIME)
                consumed_power = self.goe_service.get_current_charging_power()
                available_power = min_power - self.control_structure.NON_USED_ENERGY_BUFFER + consumed_power
                print(f"Minimum grid feed-in: {min_power} W, available power for car charging after buffer: {available_power} W, current car charging power: {self.goe_service.get_configured_charging_power()} W")
                if available_power >= self.goe_service.MINIMUM_ENERGY_CONSUMPTION:
                    if self.db_service.is_goe_action(ChargerAction.DYNAMIC_CHARGING):
                        print(f"Dynamic charging is already active, no need to request to start dynamic charging again.")
                        # TODO optionally: wait some time before changing the charging power
                        self.goe_service.set_charging_power(available_power)
                        return ChargerAction.DYNAMIC_CHARGING
                    else:
                        if self.goe_service.set_charging_power(available_power):
                            print(">>> Car charging power set to", available_power, "W")
                            # create new charging session
                            session_id = self.create_car_charging_report_entry_start()
                            return self.db_service.create_goe_action(ChargerAction.DYNAMIC_CHARGING, session_id, current_user)
                        else:
                            print(f"!!! Failed to set car charging power to {available_power} W, will retry in {self.control_structure.START_CAR_CHARGING_WAIT_TIME} minutes.")
                            return self.db_service.create_goe_action(ChargerAction.REQUEST_DYNAMIC_CHARGING, current_user)
                else:
                    print(f"Not enough excess energy available to turn on car charging. Available power for car charging after buffer: {available_power} W, current car charging power: {self.goe_service.get_configured_charging_power()} W")
                    # wait x minutes before switching off the car charging to make sure that the energy status is stable and there is actually not enough excess energy available. This is to avoid rapidly turning on and off the car charging due to fluctuations in energy production and consumption.
                    
                    current_goe_action = self.db_service.get_goe_action()
                    if current_goe_action in [ChargerAction.DYNAMIC_CHARGING, ChargerAction.REQUEST_DYNAMIC_CHARGING, ChargerAction.REQUEST_STOP_CHARGING]:
                        print(f"Car charging is currently active, checking if we need to request to stop the car charging due to insufficient excess energy.")
                        session_id = self.db_service.get_goe_action_session_id()
                        print(f">>> Session ID for charging session: {session_id}")
                        if current_goe_action != ChargerAction.REQUEST_STOP_CHARGING:
                            self.db_service.create_goe_action(ChargerAction.REQUEST_STOP_CHARGING, session_id, current_user)

                        stop_charging_time = self.db_service.get_goe_action_timestamp_by_charger_action(ChargerAction.REQUEST_STOP_CHARGING)
                        if stop_charging_time is not None:
                            delta = datetime.now() - stop_charging_time
                            print(f"Time since requesting to stop dynamic charging: {delta.total_seconds() / 60:.2f} minutes")
                            
                            elapsed_time = int(delta.total_seconds() / 60)
                            if elapsed_time >= self.control_structure.STOP_CAR_CHARGING_WAIT_TIME:
                                print(">>>> Now it's time to stop charging")
                                if self.goe_service.set_charging_power(0):
                                    print(">>> Car charging stopped")
                                    return self.process_charging_finished()
                                else:
                                    print(f"Failed to stop car charging, will retry in {self.control_structure.STOP_CAR_CHARGING_WAIT_TIME} minutes.")

                        print(f"Waiting {self.control_structure.STOP_CAR_CHARGING_WAIT_TIME - elapsed_time:.2f} more minutes before stopping the car charging to make sure that the energy status is stable.")
                        return ChargerAction.REQUEST_STOP_CHARGING
                    else:
                        print(f"Car charging is currently not active, no need to request to stop the car charging due to insufficient excess energy.")
                        return ChargerAction.NO_ACTION
                
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
                        # creae new charging session, if not already exists...
                        session_id = self.db_service.get_goe_action_session_id_by_charger_action(ChargerAction.MAX_CHARGING)
                        if session_id is None:
                            session_id = self.create_car_charging_report_entry_start()
                            self.db_service.create_goe_action(ChargerAction.MAX_CHARGING, session_id, current_user)
                        return ChargerAction.MAX_CHARGING
                
                print(f"This code should not be reached: requesting max charging but setting max charging was not successful.")
                self.db_service.create_goe_action(ChargerAction.REQUEST_MAX_CHARGING, user_id=current_user)
                return ChargerAction.REQUEST_MAX_CHARGING
                
        else:
            print(f"Car charging is currently not allowed and the car is not charging.")
            self.sonnen_battery_service.set_enable_discharge()
            if self.db_service.get_goe_action() in [ChargerAction.MAX_CHARGING, ChargerAction.DYNAMIC_CHARGING, ChargerAction.REQUEST_STOP_CHARGING]:
                return self.process_charging_finished()
            
            return self.db_service.create_goe_action(ChargerAction.NO_ACTION, user_id=current_user)
    
    def process_charging_finished(self) -> ChargerAction:
        """Process the event of car charging being finished. This will be triggered when the GoE API indicates that the car charging was completed. The method will turn on the battery discharge to allow the battery to provide energy for home consumption, and will create a new entry in the car charging report with the end time, the energy meter value at the end of the charging session, and the calculated energy consumed during the charging session."""
        print(f"Car charging was completed, processing charging finished event.")
        self.sonnen_battery_service.set_enable_discharge()
        session_id = self.db_service.get_goe_action_session_id()
        if session_id is not None:
            self.create_car_charging_report_entry_end(session_id)
            self.db_service.create_goe_action(ChargerAction.CHARGING_STOPPED)
        return ChargerAction.CHARGING_STOPPED
        
    def create_car_charging_report_entry_start(self) -> int:
        """Create a new entry in the car charging report with the start time and the energy meter value at the start of the charging session.
        Returns:
            The session ID of the created car charging report entry.
        """
        user, user_name = self.goe_service.get_last_user_with_name()
        current_meter_value = self.energy_meter.get_total_energy_wh()
        print(f"Creating car charging report entry with user {user_name} (ID: {user}) and energy meter value {current_meter_value} Wh at the start of the charging session.")
        return self.db_service.create_car_charging_entry(self.goe_service.CHARGER_SN, self.goe_service.CHARGER_NAME, user, user_name, current_meter_value)
    
    def create_car_charging_report_entry_end(self, session_id: int):
        """Update the car charging report entry with the end time, the energy meter value at the end of the charging session, and the calculated energy consumed during the charging session.
        Args:
            session_id: The session ID of the car charging report entry to be updated.
        """
        current_meter_value = self.energy_meter.get_total_energy_wh()
        self.db_service.end_car_charging_entry(session_id, current_meter_value)
        