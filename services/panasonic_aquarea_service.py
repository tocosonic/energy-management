from datetime import datetime

from services.database_service import DBService
from services.sgready_device_service import SGReadyDeviceService

class PanasonicAquareaService(SGReadyDeviceService):
    def __init__(self, db_service: DBService, relay_pin_1: int, relay_pin_2: int, device_name: str, energy_consumption_mode_1: int = 0, energy_consumption_mode_2: int = 0):
        super().__init__(db_service, None, device_name, energy_consumption_mode_1 + energy_consumption_mode_2)
        
        self.relay_1 = SGReadyDeviceService(db_service, relay_pin_1, f"{device_name} Relay 1", energy_consumption_mode_1)
        self.relay_2 = SGReadyDeviceService(db_service, relay_pin_2, f"{device_name} Relay 2", energy_consumption_mode_2)
        
    def get_id(self) -> int:
        """Get the ID of the device, which is a combination of both relay IDs."""
        return (self.relay_1.get_id() * 100) + self.relay_2.get_id()
    
    def is_on(self) -> bool:
        return self.relay_1.is_on() or self.relay_2.is_on()
    
    def turn_on(self):
        """Turn on the heat pump to maximum by activating both relays."""
        if not self.relay_1.is_on():
            self.relay_1.turn_on()
            
        if not self.relay_2.is_on():
            self.relay_2.turn_on()
            
    def turn_off(self):
        """Turn off the heat pump by deactivating both relays."""
        if self.relay_1.is_on():
            self.relay_1.turn_off()
            
        if self.relay_2.is_on():
            self.relay_2.turn_off()

    def get_updated_timestamp(self) -> datetime:
        """Get the most recent timestamp of the last status update for either relay from the database."""
        timestamp_1 = self.relay_1.get_updated_timestamp()
        timestamp_2 = self.relay_2.get_updated_timestamp()
        
        if timestamp_1 is None:
            return timestamp_2
        if timestamp_2 is None:
            return timestamp_1
        
        return max(timestamp_1, timestamp_2)
    