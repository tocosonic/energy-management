#!/usr/bin/python
# -*- coding:UTF-8 -*-
# install to crontab by:
#   crontab -e
#   * * * * * /usr/bin/python /home/pi/projects/sgready/control_relays.py >> status.log 2>&1

import os
import requests
import json
import time
from time import mktime
import RPi.GPIO as GPIO
from dotenv import load_dotenv

RELAY_ON = 0
RELAY_OFF = 1
IDX_WW = 0
IDX_HEATING1 = 1
IDX_HEATING2 = 2
IDX_WW_START = 0
IDX_HEATING_START = 1
IDX_WW_END = 2
IDX_HEATING_END = 3
IDX_SUNRISE = 0
IDX_SUNSET = 1
RELAY_RANGE = 3
RELAY_PIN = [5, 6, 13, 16, 19, 20, 21, 26]

load_dotenv()

def create_file(fd):
  for i in range(8):
    fd.write(str(f'Relay{i}=1\n'))
  fd.seek(0)

def open_file(filename):
  try:
    fd = open(filename, "r")
  except IOError:
    fd = open(filename, "w+")
    create_file(fd)
  return fd

def start_ww_and_heating(relay_status, control_countdown):
  start_ww(relay_status=relay_status, control_countdown=control_countdown)  
  
  if control_countdown[IDX_HEATING_START] <= 0:
    relay_status[IDX_HEATING1] = RELAY_ON
    relay_status[IDX_HEATING2] = RELAY_ON
    print("START Heating")
  else:
    control_countdown[IDX_HEATING_START] = control_countdown[IDX_HEATING_START] - 1
    print(f'Waiting {control_countdown[IDX_HEATING_START]} minutes to start Heating')
  control_countdown[IDX_HEATING_END] = CONTROL_END_HEATING_COUNTDOWN_DEFAULT

def start_ww(relay_status, control_countdown):
  if control_countdown[IDX_WW_START] <= 0:
    relay_status[IDX_WW] = RELAY_ON
    print("START Warm Water")
  else:
    control_countdown[IDX_WW_START] = control_countdown[IDX_WW_START] - 1
    print(f'Waiting {control_countdown[IDX_WW_START]} minutes to start Warm Water')
  control_countdown[IDX_WW_END] = CONTROL_END_WW_COUNTDOWN_DEFAULT

def continue_ww_and_heating(relay_status, control_countdown):
  print("Continue Warm Water and Heating")
  control_countdown[IDX_WW_END] = CONTROL_END_WW_COUNTDOWN_DEFAULT
  control_countdown[IDX_HEATING_END] = CONTROL_END_HEATING_COUNTDOWN_DEFAULT

def stop_ww_and_heating(relay_status, control_countdown):
  # wenn auf GO, dann erst dann stoppen, wenn x Minuten lang nicht mehr genügend Energie erzeugt wird
  if control_countdown[IDX_WW_END] <= 0:
    relay_status[IDX_WW] = RELAY_OFF
    print("STOP Warm Water")
  else:
    if is_before_or_after_sunset(sunrise_sunset):
      #shortly before sunset speed-up with shutting-down extra warm water or heating
      control_countdown[IDX_WW_END] = control_countdown[IDX_WW_END] - 3
    else:
      control_countdown[IDX_WW_END] = control_countdown[IDX_WW_END] - 1
    print(f'Waiting {control_countdown[IDX_WW_END]} minutes to stop Warm Water')
  control_countdown[IDX_WW_START] = CONTROL_START_WW_COUNTDOWN_DEFAULT
  
  if control_countdown[IDX_HEATING_END] <= 0:
    relay_status[IDX_HEATING1] = RELAY_OFF
    relay_status[IDX_HEATING2] = RELAY_OFF
    print("STOP Heating")
  else:
    if is_before_or_after_sunset(sunrise_sunset):
      #shortly before sunset speed-up with shutting-down extra warm water or heating
      control_countdown[IDX_HEATING_END] = control_countdown[IDX_HEATING_END] - 3
    else:
      control_countdown[IDX_HEATING_END] = control_countdown[IDX_HEATING_END] - 1
    print(f'Waiting {control_countdown[IDX_HEATING_END]} minutes to stop Heating')
  control_countdown[IDX_HEATING_START] = CONTROL_START_HEATING_COUNTDOWN_DEFAULT

#Query Sunrise and Sunset
def get_sunrise_sunset(sr_ss):
  try:
    api_key=os.getenv("OPENWHETHER_API_KEY")
    lat=os.getenv("OPENWHETHER_LAT")
    lon=os.getenv("OPENWHETHER_LON")
    URL = "http://api.openweathermap.org/data/2.5/weather"
    
    params = {
      "lat": lat,
      "lon": lon,
      "APPID": api_key,
      "units": "metric"
    }
    
    response = requests.get(URL, params=params)
    weather = response.json()
    #print(weather)
    sunrise = weather["sys"]["sunrise"]
    sunset = weather["sys"]["sunset"]
    sr_ss[IDX_SUNRISE] = sunrise
    sr_ss[IDX_SUNSET] = sunset
  except:
    print("Exception while calling openweathermap")
    
  return sr_ss

#Checks if the current time is within 90 minutes of sunset
def is_before_or_after_sunset(sr_ss):
  if sr_ss[IDX_SUNSET] > 0.0:
    #90 minutes * 60 seconds
    BEFORE_SUNSET_THRESHOLD = 90 * 60
    current_time = time.localtime()
    sunset = time.localtime(sr_ss[IDX_SUNSET])
    diff = mktime(sunset) - mktime(current_time)
    if diff <= BEFORE_SUNSET_THRESHOLD:
      return True
    else:
      return False
  else:
    return False

sunrise_sunset = [0.0, 0.0]
sunrise_sunset = get_sunrise_sunset(sunrise_sunset)

# high (1) == off
relay_status = [RELAY_OFF, RELAY_OFF, RELAY_OFF, RELAY_OFF, RELAY_OFF, RELAY_OFF, RELAY_OFF, RELAY_OFF, RELAY_OFF]

CONTROL_START_WW_COUNTDOWN_DEFAULT = 5
CONTROL_START_HEATING_COUNTDOWN_DEFAULT = 5
CONTROL_END_WW_COUNTDOWN_DEFAULT = 15
CONTROL_END_HEATING_COUNTDOWN_DEFAULT = 10

# 0 + 1: start
# 2 + 3: end
control_countdown = [CONTROL_START_WW_COUNTDOWN_DEFAULT, CONTROL_START_HEATING_COUNTDOWN_DEFAULT, CONTROL_END_WW_COUNTDOWN_DEFAULT, CONTROL_END_HEATING_COUNTDOWN_DEFAULT]

STATUS_FILE = os.getenv("STATUS_FILE")
CONTROL_FILE = os.getenv("CONTROL_FILE")

#read the relay status from file
fd = open_file(STATUS_FILE)
for i in range(RELAY_RANGE):
  line = fd.readline()
  print(line)
  relay_status[i] = int(line[7]) 
  
fd.close()

#read the coundown values from file
fd = open_file(CONTROL_FILE)
for i in range(4):
  line = fd.readline()
  print(f'countdown #{i} = {line}')
  control_countdown[i] = int(line)

fd.close()

# relay_value = 0

#GPIO init
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

for i in range(RELAY_RANGE):
  GPIO.setup(RELAY_PIN[i], GPIO.OUT)
  GPIO.output(RELAY_PIN[i], relay_status[i])
  print(f'Current relay {RELAY_PIN[i]} value = {relay_status[i]}')

GRID_FEED_THRESHOLD_WATER = 700
GRID_FEED_THRESHOLD_HEATING = 3000
GRID_FEED_ACCEPTED_VARIANCE = 300
WW_HEATPUMP_CONSUMPTION = 900
PRODUCTION_BACKUP = 2000
API_URL = os.getenv("SONNEN_STATUS_URL")
response = requests.get(API_URL)

sonnen = response.json()
#print(sonnen)

e_production = sonnen["Production_W"]
e_consumption = sonnen["Consumption_W"]
e_grid_feed = sonnen["GridFeedIn_W"]
e_battery_feed = -sonnen["Pac_total_W"]
e_battery_charge = sonnen["USOC"]

print(f'Erzeugung: {e_production} Watt')
print(f'Verbrauch: {e_consumption} Watt')
print(f'Batteriespeisung: {e_battery_feed} Watt')
print(f'Netzeinspeisung: {e_grid_feed} Watt')
print(f'Batteriefüllstand: {e_battery_charge}')

#ggf. anhand der Einspeisung entscheiden (z.B. Einspeisung > 1 kW)
#mind. 15 Minuten laufen lassen
#starten, wenn das Kriterium für mind. 5 Minuten erfüllt ist

if e_grid_feed > GRID_FEED_THRESHOLD_HEATING:
  print("start warm water and heating")
  start_ww_and_heating(relay_status=relay_status, control_countdown=control_countdown)
  
elif e_grid_feed > GRID_FEED_THRESHOLD_WATER:
  print("start warm water")
  start_ww(relay_status=relay_status, control_countdown=control_countdown)
  
elif relay_status[IDX_WW] == RELAY_ON and e_production > e_consumption + PRODUCTION_BACKUP:
#elif relay_status[i] == 0 and e_grid_feed > (grid_feed_threshold - grid_feed_accepted_variance - ww_heatpump_consumption):
  print("continue warm water and heating 1")
  continue_ww_and_heating(relay_status=relay_status, control_countdown=control_countdown)

elif relay_status[IDX_WW] == RELAY_ON and e_battery_feed > -100 and (e_battery_feed < 200 or e_battery_charge > 80) and e_production > (e_consumption + 300):
  # warum battery_feed < 200 => weil dann die Batterie voll ist, sonst wird die Batterieeinspeisung bevorzugt (siehe GOon1)
  print("continue warm water and heating 2")
  continue_ww_and_heating(relay_status=relay_status, control_countdown=control_countdown)

else:
  print("stop warm water and heating")
  stop_ww_and_heating(relay_status=relay_status, control_countdown=control_countdown)

#Set countdowns to default values if ww/heating is on or off respectively
if relay_status[IDX_WW] == RELAY_ON:
  control_countdown[IDX_WW_START] = CONTROL_START_WW_COUNTDOWN_DEFAULT
elif relay_status[IDX_WW] == RELAY_OFF:
  control_countdown[IDX_WW_END] = CONTROL_END_WW_COUNTDOWN_DEFAULT

if relay_status[IDX_HEATING1] == RELAY_ON:
  control_countdown[IDX_HEATING_START] = CONTROL_START_HEATING_COUNTDOWN_DEFAULT
elif relay_status[IDX_HEATING1] == RELAY_OFF:
  control_countdown[IDX_HEATING_END] = CONTROL_END_HEATING_COUNTDOWN_DEFAULT

#update relays
for i in range(RELAY_RANGE):
  GPIO.output(RELAY_PIN[i], relay_status[i])

#update status file
fd = open(STATUS_FILE, "r+b")
for i in range(RELAY_RANGE):
  fd.seek(7, 1)
  fd.write(str(relay_status[i]).encode("ascii"))
  fd.seek(1, 1)
fd.close()

#update control file
fd = open(CONTROL_FILE, "r+")
old = fd.read()
# print(f'old lines = \n{old}')
fd.seek(0)

for i in range(4):
  print(f'new line: {control_countdown[i]}')
  fd.write(str(control_countdown[i]))
  fd.write("\n")
fd.close()
