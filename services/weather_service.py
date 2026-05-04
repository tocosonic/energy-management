import requests
import time

class WeatherService:
    def __init__(self, api_key, latitude, longitude):
        self.api_key = api_key
        self.latitude = latitude
        self.longitude = longitude
        self.sunrise_sunset = [0.0, 0.0]
        self._querySunriseSunset()

    def _querySunriseSunset(self):
        # Query Sunrise and Sunset
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

    def isCloseToSunset(self, threshold_minutes=90):
        if self.sunrise_sunset[1] > 0.0:
            # Convert threshold from minutes to seconds
            threshold_seconds = threshold_minutes * 60
            currentTime = time.localtime()
            sunsetTime = time.localtime(self.sunrise_sunset[1])
            time_diff = time.mktime(sunsetTime) - time.mktime(currentTime)
            return time_diff <= threshold_seconds
        else:
            return False
    