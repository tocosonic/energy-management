from pymodbus.client import ModbusSerialClient
import serial.tools.list_ports
import struct

class WagoEnergyMeter:
    def __init__(self, port, slave_id=1, baudrate=9600, timeout=3):
        self.slave_id = slave_id  # The slave ID of the Wago energy meter. This may need to be adjusted based on the specific configuration of the energy meter.   
        self.client = ModbusSerialClient(method='rtu', port=port, baudrate=baudrate, timeout=timeout, parity=serial.PARITY_EVEN, stopbits=1, bytesize=8)

    def _decode_ieee754_float32_abcd(self, raw_registers) -> float:
        """Decode IEEE-754 float32 with ABCD byte order (register 0: AB, register 1: CD)."""
        raw = struct.pack(">HH", raw_registers[0], raw_registers[1])
        return round(struct.unpack(">f", raw)[0], 3)
        
    def get_total_energy_kwh(self) -> float:
        self.client.connect()
        # Read the total energy from the Wago energy meter. The register address and count may need to be adjusted based on the specific model and configuration of the energy meter.
        result = self.client.read_holding_registers(0x600c, 2, slave=self.slave_id)
        self.client.close()
        
        if result.isError():
            print(f"Error reading from Wago energy meter: {result}")
            return 0.0
        # Decode IEEE-754 float32 with ABCD byte order (register 0: AB, register 1: CD).
        return self._decode_ieee754_float32_abcd(result.registers)
    
    def get_total_energy_wh(self) -> int:
        """Get the total energy in Wh. This is calculated by multiplying the total energy in kWh by 1000 to convert to Wh."""
        total_energy_kwh = self.get_total_energy_kwh()
        return int(total_energy_kwh * 1000)
    
    def get_current_power_kw(self) -> float:
        self.client.connect()
        # Read the current power from the Wago energy meter.
        result = self.client.read_holding_registers(0x5012, 2, slave=self.slave_id)
        self.client.close()
        
        if result.isError():
            print(f"Error reading from Wago energy meter: {result}")
            return 0.0
        # Decode IEEE-754 float32 with ABCD byte order (register 0: AB, register 1: CD).
        return self._decode_ieee754_float32_abcd(result.registers)
    
    def get_current_power_w(self) -> int:
        """Get the current power in W. This is calculated by multiplying the current power in kW by 1000 to convert to W."""
        current_power_kw = self.get_current_power_kw()
        return int(current_power_kw * 1000)
    