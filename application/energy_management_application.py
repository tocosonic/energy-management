import os
import logging
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

log = logging.getLogger(__name__)

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
    NON_USED_ENERGY_BUFFER: int = 1000,  # Buffer in watts to account for fluctuations in energy production and consumption. This means that the application will only turn on devices if there is at least this much excess energy available, and will only turn off devices if the energy deficit is at least this much.
    GOE_USE_PV_SURPLUS: bool = False  # Whether to use the PV surplus available power reported by the GoE API to determine if there is enough excess energy available to turn on the car charging. If set to True, the application will use the PV surplus available power reported by the GoE API instead of the minimum grid feed-in value from the Sonnen battery to determine if there is enough excess energy available to turn on the car charging. This can be useful if the car charging is prioritized over other devices and you want to use the PV surplus available power to determine if there is enough excess energy available to turn on the car charging.

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
            NON_USED_ENERGY_BUFFER = int(os.getenv("NON_USED_ENERGY_BUFFER")),
            GOE_USE_PV_SURPLUS = os.getenv("GOE_USE_PV_SURPLUS", "false").lower() == "true"
        )

    def run(self):
        sleep_time: int = 60
        """Main loop of the energy management application. This will continuously monitor the energy status, weather conditions, and Sonnen battery status, and control the devices accordingly."""
        while True:
            # Refresh the status of the Sonnen battery
            self.sonnen_battery_service.refresh_status()

            self.update_heatpump(self.heating_heatpump_service, self.control_structure.START_HEATING_WAIT_TIME, self.control_structure.STOP_HEATING_WAIT_TIME)
            self.update_heatpump(self.warm_water_heatpump_service, self.control_structure.START_WW_WAIT_TIME, self.control_structure.STOP_WW_WAIT_TIME)

            self.update_car_charging()
            sleep(sleep_time)  # Sleep for 60 seconds before checking again
    
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
            close_to_sunset = self.weather_service.is_close_to_sunset()
            if not device.is_on() and not close_to_sunset:
                log.debug(f"{device.name} is currently off, but there is enough excess energy available to turn it on. Minimum grid feed-in in the last {start_wait_time} minutes: {min_power} W, available power for the device after buffer: {available_power} W, energy consumption of the device: {device.energy_consumption} W")
                device.turn_on()
            elif close_to_sunset:
                log.debug(f"{device.name} is currently on or off - but it is close to sunset. Not turning it on to avoid unnecessary energy consumption.")
                return HeatpumpAction.NO_ACTION
            else:
                log.debug(f"{device.name} is currently on and there is enough excess energy available to keep it turned on. Minimum grid feed-in in the last {start_wait_time} minutes: {min_power} W, available power for the device after buffer: {available_power} W, energy consumption of the device: {device.energy_consumption} W")
                
            return self.db_service.create_heatpump_action(device.get_id(), device.name, HeatpumpAction.HEATPUMP_ON)
        else:
            log.debug(f"Not enough excess energy available to turn on or keep on {device.name}. Minimum grid feed-in in the last {start_wait_time} minutes: {min_power} W, available power for the device after buffer: {available_power} W, energy consumption of the device: {device.energy_consumption} W")
            if device.is_on():
                log.debug(f"Turning off {device.name} due to insufficient excess energy. Minimum grid feed-in in the last {stop_wait_time} minutes: {self.sonnen_battery_service.get_grid_feed_in_minimum(stop_wait_time)} W, energy consumption of the device: {device.energy_consumption} W")
                
                current_action = self.db_service.get_heatpump_action_by_id(device.get_id())
                if current_action in [HeatpumpAction.REQUEST_HEATPUMP_OFF, HeatpumpAction.HEATPUMP_ON, HeatpumpAction.REQUEST_HEATPUMP_ON]:
                    if current_action != HeatpumpAction.REQUEST_HEATPUMP_OFF:
                        self.db_service.create_heatpump_action(device.get_id(), device.name, HeatpumpAction.REQUEST_HEATPUMP_OFF)

                    stop_time = self.db_service.get_heatpump_action_timestamp_by_heatpump_action(device.get_id(), HeatpumpAction.REQUEST_HEATPUMP_OFF)
                    if stop_time is not None:
                        delta = datetime.now() - stop_time
                        elapsed_time = int(delta.total_seconds() / 60)
                        log.debug(f"Time since requesting to stop the heatpump {device.name}: {delta.total_seconds() / 60:.2f} minutes")
                        if elapsed_time >= stop_wait_time:
                            log.info(f"Stop wait time of {elapsed_time} minutes has passed since the last request to turn off {device.name}. Proceeding to turn off the device.")
                            device.turn_off()
                            return self.db_service.create_heatpump_action(device.get_id(), device.name, HeatpumpAction.HEATPUMP_OFF)
                            
                        return HeatpumpAction.REQUEST_HEATPUMP_OFF
                    else:
                        log.debug(f"No previous request to turn off {device.name} found.")
                        return HeatpumpAction.REQUEST_HEATPUMP_OFF
                else:
                    log.debug(f"Current action for {device.name} is {current_action}, so no need to request to turn off the device now.")
                    return HeatpumpAction.NO_ACTION
                
            log.debug(f"{device.name} is currently off, so no need to turn it off due to insufficient excess energy.")
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
        
        log.debug(f"User ID of the current action: {current_action_user}, ID of the authenticated user: {authenticated_user}")
        
        if current_action_user != None and authenticated_user != None and current_action_user != authenticated_user:
            log.info(f"Authenticated user for GoE API has changed from user ID {current_action_user} to user ID {authenticated_user}. Processing user change.")
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

        if self.goe_service.is_car_charging_allowed() or self.goe_service.is_car_charging() or self.goe_service.is_car_charging_complete() or self.db_service.get_goe_status() in [ChargerAction.REQUEST_STOP_CHARGING, ChargerAction.REQUEST_DYNAMIC_CHARGING]:
            log.debug(f"Car charging is currently allowed or the car is charging or charging was completed.")
        
            if self.goe_service.is_car_charging_complete():
                log.debug(f"Car charging was completed.")
                return self.process_charging_finished()
            elif self.goe_service.is_dynamic_charging_user() and not self.control_structure.GOE_USE_PV_SURPLUS:
                log.debug(f"The last authenticated user is the dynamic charging user. PV surplus usage is disabled.")
                
                # min_power already takes the charging-wait-time into account, because the method get_grid_feed_in_minimum looks back for the specified time to determine the minimum grid feed-in value. So we can directly use the returned minimum grid feed-in value to determine if there is enough excess energy available to turn on the car charging or if we need to turn off the car charging due to insufficient excess energy.
                min_power = self.sonnen_battery_service.get_grid_feed_in_minimum(2) # self.control_structure.START_CAR_CHARGING_WAIT_TIME
                consumed_power = self.goe_service.get_current_charging_power()
                battery_feed_in = self.sonnen_battery_service.get_battery_feed()
                battery_discharge = -battery_feed_in if battery_feed_in < 0 else 0
                
                if battery_discharge > 0:
                    # allow 250 W discharging energy
                    battery_discharge = battery_discharge - 250
                
                available_power = min_power - self.control_structure.NON_USED_ENERGY_BUFFER + consumed_power - battery_discharge
                log.debug(f"Minimum grid feed-in: {min_power} W, current car charging power: {consumed_power} W, buffer power: {self.control_structure.NON_USED_ENERGY_BUFFER} W, battery discharge: {battery_discharge} W, available power for car charging after buffer: {available_power} W")
                if available_power >= self.goe_service.MINIMUM_ENERGY_CONSUMPTION:
                    if self.db_service.is_goe_action(ChargerAction.DYNAMIC_CHARGING):
                        log.debug(f"Dynamic charging is already active, no need to request to start dynamic charging again.")
                        self.goe_service.set_charging_power(available_power)
                        return ChargerAction.DYNAMIC_CHARGING
                    else:
                        if self.goe_service.set_charging_power(available_power):
                            log.info(f"Car charging power set to {available_power} W")
                            # create new charging session
                            if self.db_service.is_goe_action(ChargerAction.REQUEST_STOP_CHARGING):
                                log.debug(f"Charging session for dynamic charging already exists, no need to create a new one. Setting back to dynamic charging action with the existing session ID.")
                                session_id = self.db_service.get_goe_action_session_id_by_charger_action(ChargerAction.REQUEST_STOP_CHARGING)
                                return self.db_service.create_goe_action(ChargerAction.DYNAMIC_CHARGING, session_id, current_user)
                            else:
                                session_id = self.create_car_charging_report_entry_start()
                                log.debug(f"Created new charging session with ID {session_id} for dynamic charging.")
                                return self.db_service.create_goe_action(ChargerAction.DYNAMIC_CHARGING, session_id, current_user)
                        else:
                            log.warning(f"Failed to set car charging power to {available_power} W, will keep retrying.")
                            return self.db_service.create_goe_action(ChargerAction.REQUEST_DYNAMIC_CHARGING, current_user)
                else:
                    log.debug(f"Not enough excess energy available to turn on car charging. Available power for car charging after buffer: {available_power} W, current car charging power: {self.goe_service.get_configured_charging_power()} W")
                    # wait x minutes before switching off the car charging to make sure that the energy status is stable and there is actually not enough excess energy available. This is to avoid rapidly turning on and off the car charging due to fluctuations in energy production and consumption.
                    
                    current_goe_action = self.db_service.get_goe_action()
                    if current_goe_action in [ChargerAction.DYNAMIC_CHARGING, ChargerAction.REQUEST_DYNAMIC_CHARGING, ChargerAction.REQUEST_STOP_CHARGING]:
                        log.debug(f"Car charging is currently active, checking if we need to request to stop the car charging due to insufficient excess energy.")
                        session_id = self.db_service.get_goe_action_session_id()
                        log.debug(f"Session ID for charging session: {session_id}")
                        if current_goe_action != ChargerAction.REQUEST_STOP_CHARGING:
                            self.db_service.create_goe_action(ChargerAction.REQUEST_STOP_CHARGING, session_id, current_user)

                        stop_charging_time = self.db_service.get_goe_action_timestamp_by_charger_action(ChargerAction.REQUEST_STOP_CHARGING)
                        if stop_charging_time is not None:
                            delta = datetime.now() - stop_charging_time
                            log.debug(f"Time since requesting to stop dynamic charging: {delta.total_seconds() / 60:.2f} minutes")
                            
                            elapsed_time = int(delta.total_seconds() / 60)
                            if elapsed_time >= self.control_structure.STOP_CAR_CHARGING_WAIT_TIME:
                                log.debug("Now it's time to stop charging")
                                if self.goe_service.set_charging_power(0):
                                    log.debug("Car charging stopped")
                                    return self.process_charging_finished()
                                else:
                                    log.warning(f"Failed to stop car charging, will retry in {self.control_structure.STOP_CAR_CHARGING_WAIT_TIME} minutes.")

                        log.debug(f"Waiting {self.control_structure.STOP_CAR_CHARGING_WAIT_TIME - elapsed_time:.2f} more minutes before stopping the car charging to make sure that the energy status is stable.")
                        return ChargerAction.REQUEST_STOP_CHARGING
                    else:
                        log.debug(f"Car charging is currently not active, no need to request to stop the car charging due to insufficient excess energy.")
                        return ChargerAction.NO_ACTION
                
            else:
                log.debug(f"The last authenticated user is the fixed charging user.")
                # If the last authenticated user is the fixed charging user, we will turn on the car charging with max. power and disable discharging of the battery.
                # TODO check the size of tpa (1/120 of the loaded energy?)
                if self.goe_service.get_total_power_average() > 5:
                    # Only turn off the battery if the charger is actually charging with a significant amount of power. 
                    log.info(f"Car is charging with significant power ({self.goe_service.get_total_power_average()} W), turning off battery discharge to prioritize car charging.")
                    self.sonnen_battery_service.set_disable_discharge()
                else:
                    # Turn on the battery discharge if the charger is not charging with significant power.
                    log.debug(f"Car is not charging with significant power ({self.goe_service.get_total_power_average()} W), enabling battery discharge.")
                    self.sonnen_battery_service.set_enable_discharge()

                if self.goe_service.is_car_charging() or self.goe_service.is_car_charging_allowed():
                    if self.goe_service.set_max_charging_power():
                        log.info(f"Car charging set to max power.")
                        # creae new charging session, if not already exists...
                        session_id = self.db_service.get_goe_action_session_id_by_charger_action(ChargerAction.MAX_CHARGING)
                        if session_id is None:
                            session_id = self.create_car_charging_report_entry_start()
                            self.db_service.create_goe_action(ChargerAction.MAX_CHARGING, session_id, current_user)
                        return ChargerAction.MAX_CHARGING
                
                log.warning(f"This code should not be reached: requesting max charging but setting max charging was not successful.")
                self.db_service.create_goe_action(ChargerAction.REQUEST_MAX_CHARGING, user_id=current_user)
                return ChargerAction.REQUEST_MAX_CHARGING
                
        else:
            log.debug(f"Car charging is currently not allowed and the car is not charging.")
            self.sonnen_battery_service.set_enable_discharge()
            if self.db_service.get_goe_action() in [ChargerAction.MAX_CHARGING, ChargerAction.DYNAMIC_CHARGING, ChargerAction.REQUEST_STOP_CHARGING]:
                return self.process_charging_finished()
            
            return self.db_service.create_goe_action(ChargerAction.NO_ACTION, user_id=current_user)
    
    def process_charging_finished(self) -> ChargerAction:
        """Process the event of car charging being finished. This will be triggered when the GoE API indicates that the car charging was completed. The method will turn on the battery discharge to allow the battery to provide energy for home consumption, and will create a new entry in the car charging report with the end time, the energy meter value at the end of the charging session, and the calculated energy consumed during the charging session."""
        log.info(f"Car charging was completed, processing charging finished event.")
        self.sonnen_battery_service.set_enable_discharge()
        session_id = self.db_service.get_goe_action_session_id()
        if session_id is not None:
            self.create_car_charging_report_entry_end(session_id)
            return self.db_service.create_goe_action(ChargerAction.CHARGING_STOPPED, force=True)
        else:
            log.debug(f"No active charging session found.")
            return self.db_service.create_goe_action(ChargerAction.NO_ACTION, force=True)
        
    def create_car_charging_report_entry_start(self) -> int:
        """Create a new entry in the car charging report with the start time and the energy meter value at the start of the charging session.
        Returns:
            The session ID of the created car charging report entry.
        """
        user, user_name = self.goe_service.get_last_user_with_name()
        current_meter_value = self.energy_meter.get_total_energy_wh()
        log.debug(f"Creating car charging report entry with user {user_name} (ID: {user}) and energy meter value {current_meter_value} Wh at the start of the charging session.")
        return self.db_service.create_car_charging_entry(self.goe_service.CHARGER_SN, self.goe_service.CHARGER_NAME, user, user_name, current_meter_value)
    
    def create_car_charging_report_entry_end(self, session_id: int):
        """Update the car charging report entry with the end time, the energy meter value at the end of the charging session, and the calculated energy consumed during the charging session.
        Args:
            session_id: The session ID of the car charging report entry to be updated.
        """
        current_meter_value = self.energy_meter.get_total_energy_wh()
        self.db_service.end_car_charging_entry(session_id, current_meter_value)
        