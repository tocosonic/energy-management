from datetime import datetime
import RPi.GPIO as GPIO

from services.database_service import DBService

class SGReadyDeviceService:
    """Service for controlling SG-Ready devices (e.g. heat pumps) via relays connected to the Raspberry Pi.
    The relays are active low, which means that the device is turned on when the relay is set to LOW and turned off when the relay is set to HIGH.
    Valid relay pins are: 5, 6, 13, 16, 19, 20, 21, and 26.
    Energy consumption can be specified in watts; defaults to 0.
    """
    
    def __init__(self, db_service: DBService, relay_pin: int, name: str, energy_consumption: int = 0):
        self.db_service = db_service
        self.relay_pin = relay_pin
        self.name = name
        self.energy_consumption = energy_consumption
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.relay_pin, GPIO.OUT)
        GPIO.setwarnings(False)
        self._init_db_entry()

    def _init_db_entry(self):
        """Initialize the database entry for this device if it doesn't exist."""
        self.db_service.create_relay_status(id=self.relay_pin, device_name=self.name, is_on=self.is_on())
        
    def is_on(self) -> bool:
        """Get the current status of the device by reading the relay state.
        Returns:
            True if the device is on and False if the device is off."""
        return GPIO.input(self.relay_pin) == GPIO.LOW

    def get_updated_timestamp(self) -> datetime:
        """Get the timestamp of the last status update for this device from the database."""
        return self.db_service.get_updated_relay_timestamp(self.relay_pin)

    def turn_on(self):
        """Turn on the device by setting the relay to LOW (active low)."""
        GPIO.output(self.relay_pin, GPIO.LOW)
        self.db_service.update_relay_status(id=self.relay_pin, is_on=True)

    def turn_off(self):
        """Turn off the device by setting the relay to HIGH (active low)."""
        GPIO.output(self.relay_pin, GPIO.HIGH)
        self.db_service.update_relay_status(id=self.relay_pin, is_on=False)