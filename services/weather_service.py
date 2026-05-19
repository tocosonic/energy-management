import requests
from time import time

class WeatherService:
    def __init__(self, api_key, latitude, longitude):
        self.api_key = api_key
        self.latitude = latitude
        self.longitude = longitude
        self.sunrise_sunset = [0.0, 0.0]
        self._query_sunrise_sunset()

    # Query Sunrise and Sunset
    def _query_sunrise_sunset(self):
        try:
            url = "https://api.openweathermap.org/data/2.5/weather"
            params = {
                "lat": self.latitude,
                "lon": self.longitude,
                "APPID": self.api_key,
                "units": "metric"
            }

            response = requests.get(url, params=params)
            data = response.json()
            sunrise = data['sys']['sunrise']
            sunset = data['sys']['sunset']
            self.sunrise_sunset[0] = sunrise
            self.sunrise_sunset[1] = sunset
        except Exception as e:
            print(f"Error fetching sunrise and sunset times: {e}")

    # Checks if the current time is within a specified number of minutes of sunset.
    def is_close_to_sunset(self, threshold_minutes=90):
        if self.sunrise_sunset[1] > 0.0:
            # Convert threshold from minutes to seconds
            threshold_seconds = threshold_minutes * 60
            current_time = time.localtime()
            sunset_time = time.localtime(self.sunrise_sunset[1])
            time_diff = time.mktime(sunset_time) - time.mktime(current_time)
            return time_diff <= threshold_seconds
        else:
            return False

