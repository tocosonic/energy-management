from datetime import datetime
import logging
import json
import requests

from dataclasses import dataclass
from services.database_service import BMWCardataAuth, BMWCardataAuthKeys, DBService

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
    def __init__(self, db_service: DBService, vin: str, client_id: str):
        self.db_service = db_service
        self.vin = vin
        self.client_id = client_id
        
        if not self.is_access_token_valid(600) and not self.is_refresh_token_valid(600):
            log.debug(f"Access token and refresh token are not valid. Start DCF workflow.")
            self.dcf_step1_request_user_and_device_code()

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
            return self.dcf_step4_refresh_access_token()
        else:
            log.debug("Access token and refresh token are not valid. Start DCF workflow.")
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

    def get_mileage(self, container: dict) -> int | None:
        """Get the mileage of the car."""
        if container:
            mileage = container['telematicData']['vehicle.vehicle.travelledDistance']['value']
            if mileage is not None:
                return int(mileage)
            else:
                log.error(f"Mileage not found in container data for container 'i5_charging'.")
                return None
        else:
            log.error(f"Container must not be None.")
            return None
        
    def get_mileage_unit(self, container: dict) -> str | None:
        """Get the unit of the mileage."""
        if container:
            mileage_unit = container['telematicData']['vehicle.vehicle.travelledDistance']['unit']
            if mileage_unit is not None:
                return mileage_unit
            else:
                log.error(f"Mileage unit not found in container data for container 'i5_charging'.")
                return None
        else:
            log.error(f"Container must not be None.")
            return None
        
    def get_battery_charge_level(self, container: dict) -> int | None:
        """Get the battery charge level of the car."""
        if container:
            charge_level = container['telematicData']['vehicle.drivetrain.batteryManagement.header']['value']
            if charge_level is not None:
                return int(charge_level)
            else:
                log.error(f"Battery charge level not found in container data for container 'i5_charging'.")
                return None
        else:
            log.error(f"Container must not be None.")
            return None
        
    def get_battery_charge_level_unit(self, container: dict) -> str | None:
        """Get the unit of the battery charge level."""
        if container:
            charge_level_unit = container['telematicData']['vehicle.drivetrain.batteryManagement.header']['unit']
            if charge_level_unit is not None:
                return charge_level_unit
            else:
                log.error(f"Battery charge level unit not found in container data for container 'i5_charging'.")
                return None
        else:
            log.error(f"Container must not be None.")
            return None
        
    def get_battery_delta_fully_charged(self, container: dict) -> int | None:
        """Get the amount of energy missing for a full charge."""
        if container:
            delta_fully_charged = container['telematicData']['vehicle.drivetrain.electricEngine.charging.smeEnergyDeltaFullyCharged']['value']
            if delta_fully_charged is not None:
                return int(delta_fully_charged)
            else:
                log.error(f"Delta fully charged not found in container data for container 'i5_charging'.")
                return None
        else:
            log.error(f"Container must not be None.")
            return None
        
    def get_battery_delta_fully_charged_unit(self, container: dict) -> str | None:
        """Get the unit of the amount of energy missing for a full charge."""
        if container:
            delta_fully_charged_unit = container['telematicData']['vehicle.drivetrain.electricEngine.charging.smeEnergyDeltaFullyCharged']['unit']
            if delta_fully_charged_unit is not None:
                return delta_fully_charged_unit
            else:
                log.error(f"Delta fully charged unit not found in container data for container 'i5_charging'.")
                return None
        else:
            log.error(f"Container must not be None.")
            return None
