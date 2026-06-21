# Energy-Management
Python application which reads energy production and consumption information and controls the heat pump for warm water, the heat pump for heating and the car charger.
Since version 1.3.0 this application is fully operational (since a couple of days). BMW's Cardata stream seems to be a little fragile in the sense that you should not try to use too many connection requests within a short time. That's why this service completely disables a retry mechanism and relies solely on the service's main loop which is executed every 60 seconds. In that loop a failed MQTT connection will be re-established.

Other than that it appeared to me that Go-E's implementation of PV surplus charging seems to be somehow unpredictable (at least the action taken by this charger when simply provided with the amount of power available at the moment was delayed and/or unpredictable by me. That's why I relied on my own implementation).

<figure class="image">
<img width="793" height="1365" alt="image" src="https://github.com/user-attachments/assets/b449a856-774c-4c88-b0d4-d9c096393f46" />
<p><figcaption><em>Fig. 1: Web browser view of the status. This page was installed as web app in Windows 11.</em></figcaption></p>
</figure>

<p />

<figure class="image">
<img width="422" height="917" alt="image" src="https://github.com/user-attachments/assets/38394b49-b996-4495-80c5-8d2dfe46e09d" />
<p><figcaption><em>Fig. 2. iOS view of the status. This page was installed as shortcut on the home screen.</em></figcaption></p>
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

## Generating certificates

Run `./create-ssl-key.sh` to create the required keys and certificates. `root-cert.pem` and `root-key.pem` are the root key and certificate which are used to sign the server's CSR and thus create the final key and the certificate (`server-cert.pem` and `server-key.pem`). In your local operating system (e.g. Windows, iOS) you have to install and trust the server certificate. By going this way I was able to get TLS up and running on Windows 11 and iOS without getting any certificate-related warnings.

## Version history
- `control_relays.py` was the first version of the energy controller without supporting an electric car charger.
Now I've started to redesign everything and to support an electric car charger.
- Version 1.0.0 is finished which comes along with a status UI.
- Version 1.3.0 is the fully working version with support for BMW's Cardata MQTT streaming.
- More see https://github.com/tocosonic/energy-management/releases
