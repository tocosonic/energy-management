#!/home/hinkelm/.env/bin/python
# main.py
import argparse
from nicegui import ui
from datetime import datetime
import os
from time import sleep
import RPi.GPIO as GPIO

from dotenv import load_dotenv

from application.energy_management_application import EnergyManagementApplication
from application.energy_management_ui import EnergyManagementUI
from services.goe_service import GoEService
from services.sonnen_battery_service import SonnenBatteryService
from services.wago_energy_meter import WagoEnergyMeter
from services.weather_service import WeatherService
from services.sgready_device_service import SGReadyDeviceService
from services.database_service import DBService

def main(bypass_run: bool = False, start_ui: bool = False):
    """
    Main function to initialize the energy management application and run it.
    Installation as service:
    1. Create a systemd service file at `/etc/systemd/system/energy-management.service` with the following content:
    
        [Unit]
        Description=Energy Management Application
        After=network.target
        
        [Service]
        ExecStart=/usr/bin/python3 /path/to/your/main.py
        Restart=always
        RestartSec=5
        User=your_user
        Group=your_group
        EnvironmentFile=/path/to/your/.env
        
        [Install]
        WantedBy=multi-user.target
        
    2. Reload systemd to recognize the new service:
        
        sudo systemctl daemon-reload
        
    3. Enable the service to start on boot:
    
        sudo systemctl enable energy-management.service
    
    4. Start the service:
    
        sudo systemctl start energy-management.service
        
    5. Check the status of the service:
    
        sudo systemctl status energy-management.service
        
    6. View logs for the service:
    
        sudo journalctl -u energy-management.service -f
    
    """
    
    if start_ui:
        print("Starting UI instance")
        appUI = EnergyManagementUI()
        appUI.run()
    elif not bypass_run:
        app = EnergyManagementApplication()
        app.run()
    else:
        print("Bypassing EnergyManagementApplication.run().")
    
        app = EnergyManagementApplication()
    
        # this code is for testing purposes and will be removed in the future, as we want to run the application as a service without any output to the console
        load_dotenv()  # Load environment variables from .env file

        print(f"Sunrise and sunset times: {app.weather_service.sunrise_sunset}")
        sunset = app.weather_service.sunrise_sunset[1]
        sunrise = app.weather_service.sunrise_sunset[0]
        sunset_time = datetime.fromtimestamp(sunset)
        sunrise_time = datetime.fromtimestamp(sunrise)
        print(f"Sunset time: {sunset_time}")
        print(f"Sunrise time: {sunrise_time}")

        em = WagoEnergyMeter(port=os.getenv("ENERGY_METER_PORT"), slave_id=int(os.getenv("ENERGY_METER_SLAVE_ID")), baudrate=int(os.getenv("ENERGY_METER_BAUDRATE")))
        total_energy = em.get_total_energy_kwh()
        print(f"Total energy: {total_energy} KWh")
        
        current_power = em.get_current_power_kw()
        print(f"Current power: {current_power} kW")

        # # Initialize services
        # db_service = DBService(db_path=os.getenv("DATABASE_PATH"))
        # weather_service = WeatherService(api_key=os.getenv("OPENWEATHER_API_KEY"), latitude=os.getenv("OPENWEATHER_LAT"), longitude=os.getenv("OPENWEATHER_LON"))
        # sonnen_battery_service = SonnenBatteryService(db_service, host=os.getenv("SONNEN_BATTERY_HOST"), port=os.getenv("SONNEN_BATTERY_PORT"), api_key=os.getenv("SONNEN_BATTERY_API_KEY"))
        # warm_water_heatpump_service = SGReadyDeviceService(db_service, int(os.getenv("RELAY_PIN_WW")), "Weishaupt Warm Water Heat Pump", int(os.getenv("WW_ENERGY_CONSUMPTION")))
        # heating_heatpump_service1 = SGReadyDeviceService(db_service, int(os.getenv("RELAY_PIN_HEATING1")), "Panasonic Heating Heat Pump 1", int(os.getenv("HEATING1_ENERGY_CONSUMPTION")))
        # heating_heatpump_service2 = SGReadyDeviceService(db_service, int(os.getenv("RELAY_PIN_HEATING2")), "Panasonic Heating Heat Pump 2", int(os.getenv("HEATING2_ENERGY_CONSUMPTION")))
        # goe_service = GoEService(host=os.getenv("GOE_HOST"), api_key=os.getenv("GOE_API_KEY"), fixed_charging_user=int(os.getenv("GOE_FIXED_CHARGING_USER")), dynamic_charging_user=int(os.getenv("GOE_DYNAMIC_CHARGING_USER")))

        # relay_test = SGReadyDeviceService(db_service, 16, "Test Relay")
        # print(f"Initial status of relay on pin 16: {'ON' if relay_test.is_on() else 'OFF'}")
        # relay_test.turn_on()
        # print(f"Status of relay on pin 16 after turning on: {'ON' if relay_test.is_on() else 'OFF'}")
        # # relay_test.turn_off()
        # # print(f"Status of relay on pin 16 after turning off: {'ON' if relay_test.is_on() else 'OFF'}")


        # # Example usage of services
        # # if weather_service.is_close_to_sunset():
        # #     print("It's close to sunset. Energy production will drop soon.")
        # # else:
        # #     print("It's not close to sunset. Energy production will continue for a longer time.")

        # battery_status = sonnen_battery_service.get_battery_status()
        # print(f"Sonnen battery status: {battery_status}")
        # print(f"Energy consumption: {sonnen_battery_service.get_energy_consumption()}")
        # print(f"Energy production: {sonnen_battery_service.get_energy_production()}")
        # print(f"Grid feed: {sonnen_battery_service.get_grid_feed()}")
        # print(f"Battery feed: {sonnen_battery_service.get_battery_feed()}")
        # print(f"Battery level: {sonnen_battery_service.get_battery_level()}%")
        # print(f"Weishaupt Warm Water Heat Pump status: {'ON' if warm_water_heatpump_service.is_on() else 'OFF'}")
        # print(f"Panasonic Heating Heat Pump 1 status: {'ON' if heating_heatpump_service1.is_on() else 'OFF'}")
        # print(f"Panasonic Heating Heat Pump 2 status: {'ON' if heating_heatpump_service2.is_on() else 'OFF'}")
        # print(f"Last update timestamp for Weishaupt Warm Water Heat Pump: {warm_water_heatpump_service.get_updated_timestamp()}")
        
        # print(f"Last user from GoE: {goe_service.get_last_user()}")
        # print(f"Car status from GoE: {goe_service.get_car_status()}")
        # print(f"Is car charging allowed from GoE: {goe_service.is_car_charging_allowed()}")
        # print(f"Error from GoE: {goe_service.get_error()}")
        
        # # print(f"Number of phases: {goe_service._get_phases()}")
        # # print(f"Is car charging: {goe_service.is_car_charging()}")
        # # print(f"Is car charging allowed: {goe_service.is_car_charging_allowed()}")
        # # print(f"Current charging power: {goe_service.get_charging_power()} W")

        # # goe_service.set_charging_power(1000)
        # # goe_service.set_max_charging_power()

        # print(f"Current charging power: {goe_service.get_configured_charging_power()} W")
        
        # print(f"Minimum grid feed-in in the last 30 minutes: {sonnen_battery_service.get_grid_feed_in_minimum(30)} W")
        
        
        
        # # sonnen_battery_service.set_disable_discharge()
        # # sonnen_battery_service.refresh_status()
        # # print(f"Battery feed after disabling discharge: {sonnen_battery_service.get_battery_feed()}")
        
        # # sleep(30)  # Wait for 30 seconds before enabling discharge again
        
        # # sonnen_battery_service.set_enable_discharge()
        # # sonnen_battery_service.refresh_status()
        # # print(f"Battery feed after enabling discharge: {sonnen_battery_service.get_battery_feed()}")

if __name__ in {"__main__", "__mp_main__"}:
    parser = argparse.ArgumentParser(description="Energy management entrypoint")
    parser.add_argument(
        "--bypass-run",
        action="store_true",
        help="Skip calling EnergyManagementApplication.run()",
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Start the user interface (not implemented yet)",
    )
    args = parser.parse_args()
    main(bypass_run=args.bypass_run, start_ui=args.ui)
