import RPi.GPIO as GPIO

# This class is responsible for controlling the relays connected to the Raspberry Pi.
# It provides methods to get the status of a relay, turn it on, and turn it off.
# Instances of this class reflect the warm water as well as the heating heat pump.
class SGReadyDeviceService:
    def __init__(self, relay_pin: int):
        self.relay_pin = relay_pin
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        
    def get_status(self):
        GPIO.setup(self.relay_pin, GPIO.IN)
        return GPIO.input(self.relay_pin)

    def turn_on(self):
        GPIO.setup(self.relay_pin, GPIO.OUT)
        GPIO.output(self.relay_pin, GPIO.LOW)

    def turn_off(self):
        GPIO.setup(self.relay_pin, GPIO.OUT)
        GPIO.output(self.relay_pin, GPIO.HIGH)