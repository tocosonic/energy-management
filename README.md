# Energy-Management
Python application which reads energy production and consumption information and controls the heat pump for warm water, the heat pump for heating and the car charger.
Since version 1.3.0 this application is fully operational (since a couple of days). BMW's Cardata stream seems to be a little fragile in the sense that you should not try to use too many connection requests within a short time. That's why this service completely disables a retry mechanism and relies solely on the service's main loop which is executed every 60 seconds. In that loop a failed MQTT connection will be re-established.

Other than that it appeared to me that Go-E's implementation of PV surplus charging seems to be somehow unpredictable (at least the action taken by this charger when simply provided with the amount of power available at the moment was delayed and/or unpredictable by me. That's why I relied on my own implementation).

<figure class="image">
<img width="700" height="1272" alt="image" src="https://github.com/user-attachments/assets/34764bc1-085d-4254-b5b7-db221137f404" />
<p><figcaption><em>Fig. 1: Web browser view of the status. This image was created before the car charging optimization.</em></figcaption></p>
</figure>

<p />

<figure class="image">
<img width="422" height="917" alt="image" src="https://github.com/user-attachments/assets/b68d297f-1c49-458d-b7a4-714762cb505a" />
<p><figcaption><em>Fig. 2. iOS view of the status. This reflects the optimized car charging calculation.</em></figcaption></p>
</figure>

<p />

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

## Version history
- `control_relays.py` was the first version of the energy controller without supporting an electric car charger.
Now I've started to redesign everything and to support an electric car charger.
- Version 1.0.0 is finished which comes along with a status UI.
- Version 1.3.0 is the fully working version with support for BMW's Cardata MQTT streaming.
- More see https://github.com/tocosonic/energy-management/releases
