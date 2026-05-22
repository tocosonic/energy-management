# Energy-Management
Python application which reads energy production and consumption information and controls the heat pump for warm water, the heat pump for heating and the car charger.

## Supported gears
- RaspberryPI relay board
- Sonnen battery
- Weishaupt warm water heatpump (via SGready)
- Panasonic J-series (via SGready)
- Go-E Pro charger

## Version history
- `control_relays.py` was the first version of the energy controller without supporting an electric car charger.
Now I've started to redesign everything and to support an electric car charger.
- Version 1.0.0 is finished which comes along with a status UI.
