import requests

class GoEService:
    def __init__(self, host, api_key):
        self.host = host
        self.api_key = api_key
        
    def get_last_user(self):
        return self.get_status("lrc")

    def get_car_status(self):
        return self.get_status("car")
    
    def is_car_charging_allowed(self) -> bool:
        return self.get_status("alw")

    def get_error(self):
        return self.get_status("err")
        
    def get_status(self, filter):
        # Implement the logic to get the last user from the GoE API
        url = f"http://{self.host}/api/status?filter={filter}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                return response.json().get(filter)
            else:
                print(f"Error getting status for filter '{filter}': {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"Error getting status for filter '{filter}': {e}")
            return None
