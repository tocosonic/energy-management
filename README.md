# Energy-Management
Python application which reads energy production and consumption information and controls the heat pump for warm water, the heat pump for heating and the car charger.
Since version 1.3.0 this application is fully operational (since a couple of days). BMW's Cardata stream seems to be a little fragile in the sense that you should not try to use too many connection requests within a short time. That's why this service completely disables a retry mechanism and relies solely on the service's main loop which is executed every 60 seconds. In that loop a failed MQTT connection will be re-established.

Other than that it appeared to me that Go-E's implementation of PV surplus charging seems to be somehow unpredictable (at least the action taken by this charger when simply provided with the amount of power available at the moment was delayed and/or unpredictable by me. That's why I relied on my own implementation).

<figure class="image">
<img width="793" height="1365" alt="image" src="https://github.com/user-attachments/assets/2c013e49-cdfa-4e32-b163-fbc5a825ee10" />
<p><figcaption><em>Fig. 1: Web browser view of the status. This page was installed as web app in Windows 11.</em></figcaption></p>
</figure>

<br />

<figure class="image">
<img width="422" height="917" alt="image" src="https://github.com/user-attachments/assets/4b2ec406-9366-4cfe-889c-bc6b27297056" />
<p><figcaption><em>Fig. 2. iOS view of the status. This page was installed as shortcut on the home screen.</em></figcaption></p>
</figure>

<br />

## Supported gears
- RaspberryPI relay board
- Sonnen battery (via local API)
- Weishaupt warm water heatpump (via SGready)
- Panasonic J-series (via SGready)
- Go-E Pro charger (via local API)
- BMW Cardata Service via MQTT

## Other gears

It's rather easy to adapt this service to your own environment, provided that your equipment supports an API and provides the required data.
For that you can simply implement your own service class and replace the default service by your custom service.

## Installation

1. Install dependencies into a virtual environment

    ~~~bash
    python3 -m venv venv
    source venv/bin/activate

    pip install -r requirements.txt
    ~~~

2. Configuration of the Service
You need a `.env` file to configure the service. Create a `.env` file in the same directory as your main.py with the following content:

    ~~~env
    RELAY_PIN_WW=5
    RELAY_PIN_HEATING1=6
    RELAY_PIN_HEATING2=13
    OPENWEATHER_API_KEY=<your_openweather_api_key>
    OPENWEATHER_LAT=<your_openweather_latitude>
    OPENWEATHER_LON=<your_openweather_longitude>
    SONNEN_BATTERY_HOST=<your_sonnen_battery_host>
    SONNEN_BATTERY_PORT=8080
    SONNEN_BATTERY_API_KEY=<your_sonnen_battery_api_key>
    GOE_HOST=<your_goe_host>
    GOE_API_KEY=<your_goe_api_key>
    GOE_FIXED_CHARGING_USER=1
    GOE_DYNAMIC_CHARGING_USER=0
    DATABASE_PATH=/home/<your_user>/projects/energy-management/em.db
    WW_ENERGY_CONSUMPTION=700
    HEATING1_ENERGY_CONSUMPTION=500
    HEATING2_ENERGY_CONSUMPTION=200
    START_WW_WAIT_TIME=5
    START_HEATING_WAIT_TIME=5
    START_CAR_CHARGING_WAIT_TIME=7
    STOP_WW_WAIT_TIME=15
    STOP_HEATING_WAIT_TIME=10
    STOP_CAR_CHARGING_WAIT_TIME=15
    NON_USED_ENERGY_BUFFER=-300
    GRID_FEED_IN_MOVING_AVERAGE_INTERVAL=10
    BATTERY_FEED_IN_MOVING_AVERAGE_INTERVAL=10
    CAR_CHARGING_MOVING_AVERAGE_INTERVAL=10
    ENERGY_METER_SLAVE_ID=1
    ENERGY_METER_PORT=/dev/ttyACM0
    ENERGY_METER_BAUDRATE=9600
    BMW_CLIENT_ID=<BMW car data client id>
    BMW_VIN=<BMW VIN>
    BMW_STREAMING_USER=<BMW car data streaming user>
    BMW_STREAMING_TOPIC=<BMW VIN>
    ~~~

3. Create a systemd service file at `/etc/systemd/system/energy-management.service` with the following content:
    ~~~env
    [Unit]
    Description=Energy Management Application
    After=network.target

    [Service]
    ExecStart=/path/to/your/main.py or /pathToUsersHome/energy-management/venv/bin/python main.py (when using a virtual environment)
    Restart=always
    RestartSec=5
    User=your_user
    Group=your_group
    EnvironmentFile=/path/to/your/.env

    [Install]
    WantedBy=multi-user.target
    ~~~    
4. Reload systemd to recognize the new service:
    
    `sudo systemctl daemon-reload`
    
5. Enable the service to start on boot:

    `sudo systemctl enable energy-management.service`

6. Start the service:

    `sudo systemctl start energy-management.service`
    
7. Check the status of the service:

    `sudo systemctl status energy-management.service`
    
8. View logs for the service:

    `sudo journalctl -u energy-management.service -f`
    

## Generating certificates

Run `./create-ssl-key.sh` to create the required keys and certificates. `root-cert.pem` and `root-key.pem` are the root key and certificate which are used to sign the server's CSR and thus create the final key and the certificate (`server-cert.pem` and `server-key.pem`). In your local operating system (e.g. Windows, iOS) you have to install and trust the server certificate. By going this way I was able to get TLS up and running on Windows 11 and iOS without getting any certificate-related warnings.

## Version history
- `control_relays.py` was the first version of the energy controller without supporting an electric car charger.
Now I've started to redesign everything and to support an electric car charger.
- Version 1.0.0 is finished which comes along with a status UI.
- Version 1.3.0 is the fully working version with support for BMW's Cardata MQTT streaming.
- More see https://github.com/tocosonic/energy-management/releases
