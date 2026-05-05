# main.py
import os
import RPi.GPIO as GPIO

from dotenv import load_dotenv
from services.sonnen_battery_service import SonnenBatteryService
from services.weather_service import WeatherService
from services.sgready_device_service import SGReadyDeviceService

def main():
    load_dotenv()  # Load environment variables from .env file

    # Initialize services
    weather_service = WeatherService(api_key=os.getenv("OPENWEATHER_API_KEY"), latitude=os.getenv("OPENWEATHER_LAT"), longitude=os.getenv("OPENWEATHER_LON"))
    sonnen_battery_service = SonnenBatteryService(host=os.getenv("SONNEN_BATTERY_HOST"), port=os.getenv("SONNEN_BATTERY_PORT"), api_key=os.getenv("SONNEN_BATTERY_API_KEY"))
    warm_water_heatpump_service = SGReadyDeviceService(int(os.getenv("RELAY_PIN_WW")))
    heating_heatpump_service1 = SGReadyDeviceService(int(os.getenv("RELAY_PIN_HEATING1")))
    heating_heatpump_service2 = SGReadyDeviceService(int(os.getenv("RELAY_PIN_HEATING2")))

    # Example usage of services
    if weather_service.is_close_to_sunset():
        print("It's close to sunset. Energy production will drop soon.")
    else:
        print("It's not close to sunset. Energy production will continue for a longer time.")
    
    battery_status = sonnen_battery_service.get_battery_status()
    print(f"Sonnen battery status: {battery_status}")
    print(f"Energy consumption: {sonnen_battery_service.get_energy_consumption()}")
    print(f"Energy production: {sonnen_battery_service.get_energy_production()}")
    print(f"Grid feed: {sonnen_battery_service.get_grid_feed()}")
    print(f"Battery feed: {sonnen_battery_service.get_battery_feed()}")
    print(f"Battery level: {sonnen_battery_service.get_battery_level()}%")
    print(f"Warm water heat pump status: {'ON' if warm_water_heatpump_service.get_status() == GPIO.LOW else 'OFF'}")
    print(f"Heating heat pump 1 status: {'ON' if heating_heatpump_service1.get_status() == GPIO.LOW else 'OFF'}")
    print(f"Heating heat pump 2 status: {'ON' if heating_heatpump_service2.get_status() == GPIO.LOW else 'OFF'}")
if __name__ == "__main__":
    main()
