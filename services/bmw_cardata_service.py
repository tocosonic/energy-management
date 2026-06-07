from datetime import datetime
import logging
import json
from json import JSONDecodeError
import random
import requests

from paho.mqtt import client as mqtt_client
from dataclasses import dataclass
from services.database_service import BMWCardataAuth, BMWCardataAuthKeys, BMWCardataMessage, DBService

log = logging.getLogger(__name__)

@dataclass(frozen=True)
class DCFUserAndDeviceCode:
    user_code: str
    device_code: str
    verification_uri: str
    expires_in: int # BMW user codes are valid for 5 minutes (300 seconds)

@dataclass(frozen=True)
class DCFToken:
    access_token: str
    refresh_token: str
    id_token: str
    expires_in: int
    gcid: str

class BMWCarDataService:
    """ Service for accessing the BMW CarData API. It handles the DCF workflow for authentication and provides methods for accessing the car data.
        `streaming_user` and `streaming_topic` are optional parameters that can be used to access the BMW CarData streaming API. If they are provided, the service will also handle the authentication for the streaming API and provide methods for accessing the streaming data.
    """
    def __init__(self, db_service: DBService, vin: str, client_id: str, streaming_user: str = None, streaming_topic: str = None):
        self.db_service = db_service
        self.mqtt_client = None
        self.vin = vin
        self.client_id = client_id
        self.streaming_user = streaming_user
        self.streaming_topic = streaming_topic
        
        if not self.is_access_token_valid(600) and not self.is_refresh_token_valid(600):
            log.debug(f"Access token and refresh token are not valid. Start DCF workflow.")
            self.dcf_step1_request_user_and_device_code()

    def is_mqtt_client_connected(self) -> bool:
        """Check if the MQTT client is connected to the BMW CarData streaming API."""
        if self.mqtt_client:
            ret = self.mqtt_client.is_connected()
            if not ret:
                log.warning("MQTT client is initialized but not connected to BMW MQTT broker. Disconnecting the session now.")
                self.disconnect_mqtt_client()
            return ret
        else:
            log.warning("MQTT client is not initialized. Cannot check connection status.")
            return False

    def init_mqtt_client(self) -> bool:
        """Initialize the MQTT client for the BMW CarData streaming API."""
        if not self.streaming_user or not self.streaming_topic:
            log.error("Streaming user and streaming topic must be provided to initialize the MQTT client.")
            return False

        if not self.is_access_token_valid():
            log.debug("Access token is not valid. Refresh access token before initializing MQTT client.")
            return False
            
        def on_mqtt_connect(client, userdata, flags, reason_code, properties) -> bool:
            if reason_code == 0:
                log.debug("## Connected to BMW MQTT broker successfully.")
            else:
                log.error(f"##!! Failed to connect to BMW MQTT broker. Return code: {reason_code}")

        client_id_rnd = random.randint(0, 100000) # generate random client ID to avoid "client ID already in use" error from BMW MQTT broker

        self.mqtt_client = mqtt_client.Client(
            client_id=f"ema-{client_id_rnd}",
            protocol=mqtt_client.MQTTv311,
            callback_api_version=mqtt_client.CallbackAPIVersion.VERSION2
        )
        self.mqtt_client.tls_set() # BMW MQTT broker requires TLS
        id_token = self.db_service.get_bmw_cardata_auth_entry(BMWCardataAuthKeys.ID_TOKEN)
        self.mqtt_client.username_pw_set(self.streaming_user, id_token.value)
        self.mqtt_client.reconnect_delay_set(min_delay=90, max_delay=120) # don't use auto-reconnect feature of the MQTT client, because BMW MQTT broker has a rate limit. Instead, we will handle reconnection manually in the main loop of the application after refreshing the access token if needed.
        self.mqtt_client.on_connect = on_mqtt_connect
        
        # self.mqtt_client.on_message = self._on_mqtt_message
        err = self.mqtt_client.connect("customer.streaming-cardata.bmwgroup.com", 9000)
        log.info(f"## Connecting to BMW MQTT broker for streaming data with client ID 'ema-{client_id_rnd}' and streaming user '{self.streaming_user}'.")
        if err != 0:
            log.error(f"##!! Failed to connect to BMW MQTT broker. Error code: {err}")
            return False
        return True

    def disconnect_mqtt_client(self):
        """Disconnect the MQTT client from the BMW CarData streaming API."""
        if self.mqtt_client:
            self.mqtt_client.disconnect()
            self.mqtt_client = None
            log.debug("Disconnected from BMW MQTT broker.")
        else:
            log.warning("MQTT client is not initialized. Cannot disconnect.")

    def subscribe_to_streaming_topic(self) -> bool:
        """Subscribe to the streaming topic for the car data."""
        if self.mqtt_client:
            topic = f"{self.streaming_user}/{self.streaming_topic}"
            self.mqtt_client.subscribe(topic)
            self.mqtt_client.on_message = self._on_mqtt_message
            log.debug(f"Subscribed to BMW MQTT topic: {topic}")
            return True
        else:
            log.error("MQTT client is not initialized. Cannot subscribe to topic.")
            return False

    def _on_mqtt_message(self, client, userdata, msg: mqtt_client.MQTTMessage):
        """Callback function for handling incoming MQTT messages from the BMW CarData streaming API."""
        # log.info(f"Received MQTT message on topic {msg.topic}: {msg.payload.decode()}")
        print(f">>>>> Received MQTT message on topic {msg.topic}: {msg.payload.decode()}")
        # Here you can add code to process the incoming streaming data as needed.
        try:
            payload_json: dict = json.loads(msg.payload.decode())
        except JSONDecodeError as e:
            log.error(f"Error decoding MQTT message payload as JSON: {e}")
            print((f"!!!!! Error decoding MQTT message payload as JSON: {e}"))
            return
        
        data: dict = payload_json["data"]
        key: str | None = list(data.keys())[0] if data else None
        print(f">>>> Extracted key from MQTT message: {key}")
        values: dict | None = data[key] if key else None
        if isinstance(values, dict):
            print(f">>>> Extracted values from MQTT message: {values}")
            value = str(values.get("value", ""))
            unit = values.get("unit", None)
            bmw_message = BMWCardataMessage(
                topic=payload_json["topic"],
                key=key,
                value=value,
                unit=unit,
                timestamp=datetime.now()
            )
            print(f">>>> Created BMWCardataMessage: {bmw_message}")
            self.db_service.create_bmw_cardata_message_entry(bmw_message)
        else:
            print(f"!!!!! Values in MQTT message are not in expected format: {values}")

    def run_mqtt_client(self):
        """Run the MQTT client loop to receive streaming data from the BMW CarData streaming API."""
        if self.mqtt_client:
            self.mqtt_client.loop_start()
            log.debug("Started MQTT client loop.")
        else:
            log.error("MQTT client is not initialized. Cannot start loop.")

    def is_access_token_valid(self, grace_period: int = 0) -> bool:
        """Check if the access token stored in the database is still valid."""
        access_token_entry = self.db_service.get_bmw_cardata_auth_entry(BMWCardataAuthKeys.ACCESS_TOKEN)
        if access_token_entry:
            expires_in = access_token_entry.expires_in
            timestamp = access_token_entry.timestamp
            if expires_in and timestamp:
                expiration_time = timestamp.timestamp() + expires_in - grace_period
                current_time = datetime.now().timestamp()
                return current_time < expiration_time
        return False

    def is_refresh_token_valid(self, grace_period: int = 0) -> bool:
        """Check if the refresh token stored in the database is still valid."""
        refresh_token_entry = self.db_service.get_bmw_cardata_auth_entry(BMWCardataAuthKeys.REFRESH_TOKEN)
        if refresh_token_entry:
            expires_in = refresh_token_entry.expires_in
            timestamp = refresh_token_entry.timestamp
            if expires_in and timestamp:
                expiration_time = timestamp.timestamp() + expires_in - grace_period
                current_time = datetime.now().timestamp()
                return current_time < expiration_time
        return False

    def dcf_step1_request_user_and_device_code(self) -> DCFUserAndDeviceCode | None:
        """ Request the user code, device code and verification URI from the BMW DCF and store them in the database.
            If there are already entries for the user code, device code and verification URI as well
            as other related tokens in the database, they will be deleted.
        """
        result = self._dcf_request_user_and_device_code()
        if result:
            # clean up old entries
            self.db_service.delete_bmw_cardata_auth_entry(BMWCardataAuthKeys.USER_CODE)
            self.db_service.delete_bmw_cardata_auth_entry(BMWCardataAuthKeys.DEVICE_CODE)
            self.db_service.delete_bmw_cardata_auth_entry(BMWCardataAuthKeys.VERIFICATION_URI)
            self.db_service.delete_bmw_cardata_auth_entry(BMWCardataAuthKeys.GCID)
            self.db_service.delete_bmw_cardata_auth_entry(BMWCardataAuthKeys.ACCESS_TOKEN)
            self.db_service.delete_bmw_cardata_auth_entry(BMWCardataAuthKeys.REFRESH_TOKEN)
            self.db_service.delete_bmw_cardata_auth_entry(BMWCardataAuthKeys.ID_TOKEN)
            
            self._store_user_and_device_code(result)
        return result

    def _store_user_and_device_code(self, value: DCFUserAndDeviceCode):
        """Store the user code, device code and verification URI in the database."""
        timestamp = datetime.now()
        user_code_entry = BMWCardataAuth(
            key=BMWCardataAuthKeys.USER_CODE,
            value=value.user_code,
            expires_in=value.expires_in,
            timestamp=timestamp
        )
        device_code_entry = BMWCardataAuth(
            key=BMWCardataAuthKeys.DEVICE_CODE,
            value=value.device_code,
            expires_in=value.expires_in,
            timestamp=timestamp
        )
        verification_uri_entry = BMWCardataAuth(
            key=BMWCardataAuthKeys.VERIFICATION_URI,
            value=value.verification_uri,
            expires_in=value.expires_in,
            timestamp=timestamp
        )
        self.db_service.create_bmw_cardata_auth_entry(user_code_entry)
        self.db_service.create_bmw_cardata_auth_entry(device_code_entry)
        self.db_service.create_bmw_cardata_auth_entry(verification_uri_entry)
        

    def _dcf_request_user_and_device_code(self) -> DCFUserAndDeviceCode | None:
        url = "https://customer.bmwgroup.com/gcdm/oauth/device/code"
        headers = {
            "accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        payload = {
            "client_id": self.client_id,
            "response_type": "device_code",
            "scope": "authenticate_user openid cardata:api:read cardata:streaming:read",
            "code_challenge": "6xSQkAzH8oEmFMieIfFjAlAsYMS23uhOCXg70Gf13p8",
            "code_challenge_method": "S256",
        }
        response = requests.post(url, headers=headers, data=payload, timeout=30)
        if response.status_code == 200:
            log.debug(f"BMW DCF response for user and device code request: {response.text}")
            data = response.json()
            return DCFUserAndDeviceCode(
                user_code=data.get("user_code"),
                device_code=data.get("device_code"),
                verification_uri=f"{data.get('verification_uri')}?user_code={data.get('user_code')}",
                expires_in=data.get("expires_in")
            )
        else:
            log.error(f"Error requesting user and device code from BMW DCF: {response.status_code} - {response.text}")
            return None

    def dcf_step2_get_verification_uri(self) -> str | None:
        """ Get the verification URI from the database. This URI has to be called manually in a web browser
            to provide the user code and to login to the BMW user portal. It will authorize the application
            to access the car data."""
        entry = self.db_service.get_bmw_cardata_auth_entry(BMWCardataAuthKeys.VERIFICATION_URI)
        if entry:
            return entry.value
        else:
            log.error(f"Verification URI not found in database for key: {BMWCardataAuthKeys.VERIFICATION_URI}")
            return None

    def dcf_step3_request_access_token(self) -> DCFToken | None:
        """Request the access token, refresh token, id token and gcid from the BMW DCF using the device code stored in the database."""
        device_code_entry = self.db_service.get_bmw_cardata_auth_entry(BMWCardataAuthKeys.DEVICE_CODE)
        if device_code_entry:
            result = self._dcf_request_access_token(device_code_entry.value)
            if result:
                # clean-up old entries
                self.db_service.delete_bmw_cardata_auth_entry(BMWCardataAuthKeys.GCID)
                self.db_service.delete_bmw_cardata_auth_entry(BMWCardataAuthKeys.ACCESS_TOKEN)
                self.db_service.delete_bmw_cardata_auth_entry(BMWCardataAuthKeys.REFRESH_TOKEN)
                self.db_service.delete_bmw_cardata_auth_entry(BMWCardataAuthKeys.ID_TOKEN)
                
                self._store_access_token(result)
            return result
        else:
            log.error(f"Device code not found in database for key: {BMWCardataAuthKeys.DEVICE_CODE}")
            return None

    def _store_access_token(self, value: DCFToken):
        """Store the access token, refresh token, id token and gcid in the database."""
        timestamp = datetime.now()
        access_token_entry = BMWCardataAuth(
            key=BMWCardataAuthKeys.ACCESS_TOKEN,
            value=value.access_token,
            expires_in=value.expires_in,
            timestamp=timestamp
        )
        refresh_token_entry = BMWCardataAuth(
            key=BMWCardataAuthKeys.REFRESH_TOKEN,
            value=value.refresh_token,
            expires_in=14*24*3600, # BMW refresh tokens are valid for 14 days
            timestamp=timestamp
        )
        id_token_entry = BMWCardataAuth(
            key=BMWCardataAuthKeys.ID_TOKEN,
            value=value.id_token,
            expires_in=value.expires_in,
            timestamp=timestamp
        )
        gcid_entry = BMWCardataAuth(
            key=BMWCardataAuthKeys.GCID,
            value=value.gcid,
            expires_in=value.expires_in,
            timestamp=timestamp
        )
        self.db_service.create_bmw_cardata_auth_entry(access_token_entry)
        self.db_service.create_bmw_cardata_auth_entry(refresh_token_entry)
        self.db_service.create_bmw_cardata_auth_entry(id_token_entry)
        self.db_service.create_bmw_cardata_auth_entry(gcid_entry)
    
    def _dcf_request_access_token(self, device_code: str) -> DCFToken | None:
        url = "https://customer.bmwgroup.com/gcdm/oauth/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        code_verifier = "Lc-kVofs3uj2Aj5Yrpd8X8Sa0N6tGmp4VIjflKSbFSQ" #random string
        data = {
            "client_id": self.client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "code_verifier": code_verifier,
        }
        response = requests.post(url, headers=headers, data=data, timeout=30)
        if response.status_code == 200:
            log.debug(f"BMW DCF response for access token request: {response.text}")
            data = response.json()
            return DCFToken(
                access_token=data.get("access_token"),
                refresh_token=data.get("refresh_token"),
                expires_in=data.get("expires_in"),
                id_token=data.get("id_token"),
                gcid=data.get("gcid")
            )
        else:
            log.error(f"Error requesting access token from BMW DCF: {response.status_code} - {response.text}")
            return None
        
    def refresh_access_token_if_needed(self) -> DCFToken | None:
        """Check if the access token is still valid. If not, check if the refresh token is still valid and use it to request a new access token."""
        if self.is_access_token_valid(600):
            log.debug("Access token is still valid. No need to refresh.")
            return None
        elif self.is_refresh_token_valid(600):
            log.debug("Access token is not valid, but refresh token is still valid. Refresh access token.")
            self.disconnect_mqtt_client() # will be restarted in the main loop of the application after refreshing the access token
            return self.dcf_step4_refresh_access_token()
        else:
            log.debug("Access token and refresh token are not valid. Start DCF workflow.")
            self.disconnect_mqtt_client() # will be restarted in the main loop of the application after refreshing the access token
            self.dcf_step1_request_user_and_device_code()
            return None
        
    def dcf_step4_refresh_access_token(self) -> DCFToken | None:
        refresh_token = self.db_service.get_bmw_cardata_auth_entry(BMWCardataAuthKeys.REFRESH_TOKEN)
        if refresh_token:
            result = self._dcf_refresh_access_token(refresh_token.value)
            if result:
                # clean-up old entries
                self.db_service.delete_bmw_cardata_auth_entry(BMWCardataAuthKeys.GCID)
                self.db_service.delete_bmw_cardata_auth_entry(BMWCardataAuthKeys.ACCESS_TOKEN)
                self.db_service.delete_bmw_cardata_auth_entry(BMWCardataAuthKeys.REFRESH_TOKEN)
                self.db_service.delete_bmw_cardata_auth_entry(BMWCardataAuthKeys.ID_TOKEN)

                self._store_access_token(result)
            return result
        else:
            log.error(f"Refresh token not found in database for key: {BMWCardataAuthKeys.REFRESH_TOKEN}")
            return None
        
    def _dcf_refresh_access_token(self, refresh_token: str) -> DCFToken | None:
        url = "https://customer.bmwgroup.com/gcdm/oauth/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "client_id": self.client_id,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        response = requests.post(url, headers=headers, data=data, timeout=30)
        if response.status_code == 200:
            log.debug(f"BMW DCF response for access token refresh request: {response.text}")
            data = response.json()
            return DCFToken(
                access_token=data.get("access_token"),
                refresh_token=data.get("refresh_token"),
                expires_in=data.get("expires_in"),
                id_token=data.get("id_token"),
                gcid=data.get("gcid")
            )
        else:
            log.error(f"Error refreshing access token from BMW DCF: {response.status_code} - {response.text}. You have to request a new user and device code.")
            return None

    def get_container_by_name(self, container_name: str) -> dict | None:
        """Get the container data for the specified container name."""
        access_token_entry = self.db_service.get_bmw_cardata_auth_entry(BMWCardataAuthKeys.ACCESS_TOKEN)
        if access_token_entry:
            access_token = access_token_entry.value
            container_id = self._get_container_id_by_name(access_token, container_name)
            if container_id:
                return self._get_container_data(access_token, container_id, self.vin)
            else:
                log.error(f"Container with name '{container_name}' not found.")
                return None
        else:
            log.error(f"Access token not found in database for key: {BMWCardataAuthKeys.ACCESS_TOKEN}")
            return None
        
    def _get_container_id_by_name(self, access_token: str, container_name: str) -> str | None:
        url = f"https://api-cardata.bmwgroup.com/customers/containers"
        headers = {
            "accept": "application/json",
            "x-version": "v1",
            "Authorization": f"Bearer {access_token}"
        }
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            log.debug(f"BMW API response for container list request: {response.text}")
            containers = response.json().get("containers", [])
            for container in containers:
                if container.get("name") == container_name:
                    return container.get("containerId")
            log.error(f"Container with name '{container_name}' not found in BMW API response.")
            return None
        else:
            log.error(f"Error requesting container list from BMW API: {response.status_code} - {response.text}")
            return None

    def _get_container_data(self, access_token: str, container_id: str, vin: str) -> dict | None:
        url = f"https://api-cardata.bmwgroup.com/customers/vehicles/{vin}/telematicData?containerId={container_id}"
        headers = {
            "accept": "application/json",
            "x-version": "v1",
            "Authorization": f"Bearer {access_token}"
        }
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            log.debug(f"BMW API response for container data request: {response.text}")
            return response.json()
        else:
            log.error(f"Error requesting container data from BMW API: {response.status_code} - {response.text}")
            return None

    def get_mileage(self) -> tuple[int, str, datetime] | None:
        """Get the mileage of the car."""
        msg = self.db_service.get_bmw_cardata_message_entry(self.streaming_topic, "vehicle.vehicle.travelledDistance")
        if msg:
            try:
                value = int(msg.value)
                unit = msg.unit
                return value, unit, msg.timestamp
            except ValueError as e:
                log.error(f"Error converting mileage value to int: {e}")
                return None
        else:
            log.error(f"Mileage not found in database for topic '{self.streaming_topic}' and key 'vehicle.vehicle.travelledDistance'.")
            return None
        
    def get_battery_charge_level(self) -> tuple[int, str, datetime] | None:
        """Get the battery charge level of the car."""
        msg = self.db_service.get_bmw_cardata_message_entry(self.streaming_topic, "vehicle.drivetrain.batteryManagement.header")
        if msg:
            try:
                value = int(msg.value)
                unit = "%" if msg.unit == "percent" else msg.unit
                return value, unit, msg.timestamp
            except ValueError as e:
                log.error(f"Error converting battery charge level value to int: {e}")
                return None
        else:
            log.error(f"Battery charge level not found in database for topic '{self.streaming_topic}' and key 'vehicle.drivetrain.batteryManagement.header'.")
            return None

    def get_battery_delta_fully_charged(self) -> tuple[int, str, datetime] | None:
        """Get the amount of energy missing for a full charge."""
        msg = self.db_service.get_bmw_cardata_message_entry(self.streaming_topic, "vehicle.drivetrain.electricEngine.charging.smeEnergyDeltaFullyCharged")
        if msg:
            try:
                value = int(msg.value)
                unit = msg.unit
                timestamp = msg.timestamp
                return value, unit, timestamp
            except ValueError as e:
                log.error(f"Error converting battery delta fully charged value to int: {e}")
                return None
        else:
            log.error(f"Battery delta fully charged not found in database for topic '{self.streaming_topic}' and key 'vehicle.drivetrain.electricEngine.charging.smeEnergyDeltaFullyCharged'.")
            return None

    def get_remaining_range(self) -> tuple[int, str, datetime] | None:
        """Get the remaining range of the car."""
        msg = self.db_service.get_bmw_cardata_message_entry(self.streaming_topic, "vehicle.drivetrain.electricEngine.kombiRemainingElectricRange")
        if msg:
            try:
                value = int(msg.value)
                unit = msg.unit
                return value, unit, msg.timestamp
            except ValueError as e:
                log.error(f"Error converting remaining range value to int: {e}")
                return None
        else:
            log.error(f"Remaining range not found in database for topic '{self.streaming_topic}' and key 'vehicle.drivetrain.electricEngine.kombiRemainingElectricRange'.")
            return None
