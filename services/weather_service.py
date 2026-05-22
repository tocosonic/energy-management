from datetime import datetime
import logging
import requests

log = logging.getLogger(__name__)

class WeatherService:
    def __init__(self, api_key, latitude, longitude):
        self.api_key = api_key
        self.latitude = latitude
        self.longitude = longitude
        self.sunrise_sunset = [0.0, 0.0]
        self._query_sunrise_sunset()

    def _query_sunrise_sunset(self):
        """Fetch sunrise and sunset times from the OpenWeather API and store them in the sunrise_sunset attribute."""
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
            log.error(f"Error fetching sunrise and sunset times: {e}")

    def is_close_to_sunset(self, threshold_minutes=90):
        """Checks if the current time is within a specified number of minutes of sunset."""
        self._query_sunrise_sunset()
        if self.sunrise_sunset[1] > 0.0:
            # Convert threshold from minutes to seconds
            threshold_seconds = threshold_minutes * 60
            current_time = datetime.now()
            sunset_time = datetime.fromtimestamp(self.sunrise_sunset[1])
            time_diff = (sunset_time - current_time).total_seconds()
            log.debug(f"Current time: {current_time}, Sunset time: {sunset_time}, Time difference in seconds: {time_diff}, Threshold in seconds: {threshold_seconds}")
            return time_diff <= threshold_seconds
        else:
            return False

