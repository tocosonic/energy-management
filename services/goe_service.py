import requests
import math
import time

class GoEService:
    """Client for reading and updating charger state through the go-e API."""

    def __init__(self, host, api_key):
        """Initialize the service with the charger host and API key."""
        self.host = host
        self.api_key = api_key

    def get_last_user(self) -> int:
        """Returns:
            The card index of the last authenticated user."""
        return self._get_status("lrc")

    def get_car_status(self) -> int:
        """The current status code of the car reported by the charger.
        Returns:
            None on internal errors.
            Values are: Unknown/Error=0, Idle=1, Charging=2, WaitCar=3,
            Complete=4, Error=5.
        """
        return self._get_status("car")

    def is_car_charging(self) -> bool:
        """Return whether the charger currently reports an active charging session."""
        return self.get_car_status() == 2

    def is_car_charging_allowed(self) -> bool:
        """Return whether charging is currently allowed by the charger."""
        return self._get_status("alw")

    def get_error(self) -> int:
        """The error code reported by the charger.
        Returns:
            None on internal errors.
            Values include: None=0, FiAc=1, FiDc=2, Phase=3, Overvolt=4,
            Overamp=5, Diode=6, PpInvalid=7, GndInvalid=8,
            ContactorStuck=9, ContactorMiss=10, FiUnknown=11, Unknown=12,
            Overtemp=13, NoComm=14, StatusLockStuckOpen=15,
            StatusLockStuckLocked=16, Reserved20=20, Reserved21=21,
            Reserved22=22, Reserved23=23, Reserved24=24.
        """
        return self._get_status("err")

    def _get_phases(self) -> int:
        """The configured number of charging phases.
        Returns:
            0 for automatic phase switching,
            1 for single-phase charging,
            3 for three-phase charging,
            -1 for unknown charger value.
        """
        ret = self._get_status("psm")
        match ret:
            case 0:
                return 0
            case 1:
                return 1
            case 2:
                return 3
            case _:
                print(f"Unknown phase mode: {ret}")
                return -1

    def get_charging_power(self) -> int:
        """The current charging power in watts as reported by the charger.
        Returns:
            The current charging power in watts, or None on internal errors.
        """
        phases = self._get_phases()
        if phases == -1:
            return None
        elif phases == 0:
            # if the charger is in automatic phase switching mode, we assume 3 phases are available
            phases = 3
        current_per_phase = self._get_status("amp")
        if current_per_phase is None:
            return None
        return phases * current_per_phase * 230  # convert current in amperes to power in watts assuming 230 V

    def _get_status(self, filter):
        """Get a single status value from the charger API.
        Args:
            filter: The go-e status key to request. See https://github.com/goecharger/go-eCharger-API-v2/blob/export_api_docs_from_firmware/apikeys-en.md
        Returns:
            The value for the requested key, or None if the request fails.
        """
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

    def _update_setting(self, key, value) -> bool:
        """Update a single charger setting through the API.
        Args:
            key: The charger setting key.
            value: The value to write.
        Returns:
            True if the update succeeded, otherwise False.
        """
        url = f"http://{self.host}/api/set?{key}={value}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                return True
            else:
                print(f"Error updating setting '{key}': {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"Error updating setting '{key}': {e}")
            return False

    def set_charging_off(self) -> bool:
        """Force charging off."""
        ret = self._update_setting("frc", 1)
        time.sleep(15)  # wait for the charger to stop charging before returning to avoid issues with subsequent updates
        return ret

    def set_charging_on(self) -> bool:
        """Force charging on."""
        ret = self._update_setting("frc", 2)
        time.sleep(15)  # wait for the charger to start charging before returning to avoid issues with subsequent updates
        return ret

    def set_charging_default(self) -> bool:
        """Restore the charger's default charging mode."""
        return self._update_setting("frc", 0)

    def _set_charging_phases(self, phases) -> bool:
        """Set the number of phases used for charging.
        Args:
            phases: Allowed values are 0 for automatic switching, 1, or 3.
        Returns:
            True if the update succeeded, otherwise False.
        """
        current_phases = self._get_phases()
        is_car_charging = self.is_car_charging()
        charging_stopped = False
        
        if current_phases != phases and is_car_charging:
            # turn off charging if changing the number of phases to avoid issues with the car
            self.set_charging_off()
            charging_stopped = True
        
        ret = False
        match phases:
            case 0:
                ret = self._update_setting("psm", 0)
            case 1:
                ret = self._update_setting("psm", 1)
            case 3:
                ret = self._update_setting("psm", 2)
            case _:
                print(f"Invalid number of phases: {phases}. Only 0 (auto), 1 and 3 are allowed.")
                ret = False
        
        # turn on charging again if it was on before
        if charging_stopped:
            if is_car_charging:
                self.set_charging_on()
            else:
                self.set_charging_default()
        return ret

    def _set_charging_current(self, current) -> bool:
        """Set the charging current in amperes.
        Args:
            current: Charging current in the allowed range from 6 to 16 A.
        Returns:
            True if the update succeeded, otherwise False.
        """
        if current < 6 or current > 16:
            print(f"Invalid charging current: {current}. Only values between 6 and 16 are allowed.")
            return False
        return self._update_setting("amp", current)

    def set_max_charging_power(self) -> bool:
        """Set the charger to maximum power using 3 phases and 16 A per phase."""
        ret = self._set_charging_phases(3)
        if ret:
            return self._set_charging_current(16)
        return False

    def set_charging_power(self, power) -> bool:
        """Set the charger to the indicated power. Phases and current are selected automatically based on the requested power. The method will try to use as few phases as possible while keeping the current per phase within the allowed range of 6 to 16 A.
        Furthermore, the requested power must be at least 1380 W (6 A on a single phase) and at most 11040 W (16 A on three phases).
        The effective power will never exceed the requested power, but may be lower due to the discrete number of phases and current steps supported by the charger.
        Args:
            power: The desired charging power in watts. The method will calculate the required current and number of phases and update the charger settings accordingly. The minimum allowed value is 1380 W (6 A on a single phase), the maximum is 11040 W (16 A on three phases).
        Returns:
            True if the update succeeded, otherwise False.
        """
        total_current_required = power / 230  # convert energy in watts to current in amperes assuming 230 V
        if total_current_required < 6:
            print(f"Requested power {power} W is too low. Minimum is 1380 W (6 A). Turning charging off and setting minimum values.")
            self.set_charging_power(1380)
            self.set_charging_off()
            return False
        else:
            # if the required total current is between 6 and 18 A (18 A is the minimum total current for three phases: 3x 6 A), use single phase charging with the required current
            phases_required = 1 if total_current_required < 18 else 3
            current_required = math.floor(min(total_current_required / phases_required, 16))  # the charger supports a maximum of 16 A per phase
            
            ret = self._set_charging_phases(phases_required)
            if ret:
                ret = self._set_charging_current(current_required)
                if(ret):
                    self.set_charging_on()  # make sure charging is on after successfully updating the settings
                return ret
        return False
