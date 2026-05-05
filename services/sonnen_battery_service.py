import requests

class SonnenBatteryService:
    def __init__(self, host, port, api_key):
        self.host = host
        self.port = port
        self.api_key = api_key
        self.sonnen_status = None
        self._query_status()

    def _query_status(self):
        try:
            url = f"http://{self.host}:{self.port}/api/v1/status"
            headers = {
                "Authorization": f"Bearer {self.api_key}"
            }
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                self.sonnen_status = response.json()
            else:                
                print(f"Error fetching status of Sonnen battery: {response.status_code} - {response.text}")
                self.sonnen_status = None
        except Exception as e:
            print(f"Error fetching status of Sonnen battery: {e}")
            self.sonnen_status = None

    # This method can be called to refresh the status of the Sonnen battery. It will call the _query_status method to fetch the latest status from the API.
    def refresh_status(self):
        self._query_status()

    # Status of the Sonnen battery as JSON structure. This includes the current battery level, energy production, and energy consumption.
    def get_battery_status(self):
        return self.sonnen_status

    def get_energy_production(self) -> int:
        return self.sonnen_status["Production_W"] if self.sonnen_status else None

    def get_energy_consumption(self) -> int:
        return self.sonnen_status["Consumption_Avg"] if self.sonnen_status else None
    
    def get_grid_feed(self) -> int:
        return self.sonnen_status["GridFeedIn_W"] if self.sonnen_status else None
    
    def get_battery_feed(self) -> int:
        return -self.sonnen_status["Pac_total_W"] if self.sonnen_status else None
    
    def get_battery_level(self) -> int:
        return self.sonnen_status["USOC"] if self.sonnen_status else None
    