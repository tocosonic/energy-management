import logging
import json
import requests

from dataclasses import dataclass
from services.database_service import DBService

log = logging.getLogger(__name__)

@dataclass(frozen=True)
class DCFUserAndDeviceCode:
    user_code: str
    device_code: str
    verification_uri: str

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
            )
        else:
            log.error(f"Error requesting user and device code from BMW DCF: {response.status_code} - {response.text}")
            return None
        
        # url = "https://customer.bmwgroup.com/gcdm/oauth/authenticate"
        # headers = {
        #     "Content-Type": "application/x-www-form-urlencoded"
        # }
        # data = {
        #     "client_id": self.client_id,
        #     "scope": "remote_services:vehicle:read remote_services:vehicle:write"
        # }
        # response = requests.post(url, headers=headers, data=data)
        # if response.status_code == 200:
        #     return response.json()
        # else:
        #     log.error(f"Error requesting user and device code from BMW DCF: {response.status_code} - {response.text}")
        #     return None
    
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
