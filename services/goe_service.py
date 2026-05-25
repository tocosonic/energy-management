from enum import Enum
import logging
import requests
import math
import time

log = logging.getLogger(__name__)

class CarStatus(Enum):
    UNKNOWN_ERROR = 0
    IDLE = 1
    CHARGING = 2
    WAIT_CAR = 3
    COMPLETE = 4
    ERROR = 5

class ChargerStatus(Enum):
    NotChargingBecauseNoChargeCtrlData=0
    NotChargingBecauseOvertemperature=1
    NotChargingBecauseAccessControlWait=2
    ChargingBecauseForceStateOn=3
    NotChargingBecauseForceStateOff=4
    NotChargingBecauseScheduler=5
    NotChargingBecauseEnergyLimit=6
    ChargingBecauseAwattarPriceLow=7
    ChargingBecauseAutomaticStopTestLadung=8
    ChargingBecauseAutomaticStopNotEnoughTime=9
    ChargingBecauseAutomaticStop=10
    ChargingBecauseAutomaticStopNoClock=11
    ChargingBecausePvSurplus=12
    ChargingBecauseFallbackGoEDefault=13
    ChargingBecauseFallbackGoEScheduler=14
    ChargingBecauseFallbackDefault=15
    NotChargingBecauseFallbackGoEAwattar=16
    NotChargingBecauseFallbackAwattar=17
    NotChargingBecauseFallbackAutomaticStop=18
    ChargingBecauseCarCompatibilityKeepAlive=19
    ChargingBecauseChargePauseNotAllowed=20
    NotChargingBecauseSimulateUnplugging=22
    NotChargingBecausePhaseSwitch=23
    NotChargingBecauseMinPauseDuration=24
    NotChargingBecauseError=26
    NotChargingBecauseLoadManagementDoesntWant=27
    NotChargingBecauseOcppDoesntWant=28
    NotChargingBecauseReconnectDelay=29
    NotChargingBecauseAdapterBlocking=30
    NotChargingBecauseUnderfrequencyControl=31
    NotChargingBecauseUnbalancedLoad=32
    ChargingBecauseDischargingPvBattery=33
    NotChargingBecauseGridMonitoring=34
    NotChargingBecauseOcppFallback=35

class ChargerError(Enum):
    NoError=0
    FiAc=1
    FiDc=2
    Phase=3
    Overvolt=4
    Overamp=5
    Diode=6
    PpInvalid=7
    GndInvalid=8
    ContactorStuck=9
    ContactorMiss=10
    FiUnknown=11
    Unknown=12
    Overtemp=13
    NoComm=14
    StatusLockStuckOpen=15
    StatusLockStuckLocked=16
    Reserved20=20
    Reserved21=21
    Reserved22=22
    Reserved23=23
    Reserved24=24

class LogicMode(Enum):
    Default=3
    EcoMode=4
    AutomaticStop=5

class GoEService:
    """Client for reading and updating charger state through the go-e API."""

    def __init__(self, host: str, api_key: str, fixed_charging_user: int, dynamic_charging_user: int):
        """Initialize the service with the charger host and API key."""
        self.host = host
        self.api_key = api_key
        self.fixed_charging_user = fixed_charging_user
        self.dynamic_charging_user = dynamic_charging_user
        self.MINIMUM_ENERGY_CONSUMPTION = 1380  # the minimum energy consumption of the car when charging with 6 A on a single phase, which is the minimum allowed current by the charger   
        self.CHARGER_SN = self._get_status("sse")  # the serial number of the charger, which can be used to identify the charger
        self.CHARGER_NAME = self._get_status("fna")  # the name of the charger

    def get_last_user_with_name(self) -> tuple[int, str]:
        """Returns:
            The card index of the last authenticated user and the corresponding user name."""
        last_user = self.get_authenticated_user()
        last_user_name = self.get_user_name(last_user)
        return last_user, last_user_name

    def get_user_name(self, user_id: int) -> str:
        """Returns:
            The user name corresponding to the given card index of the user."""
        if user_id is None:
            return "None"
        filter = f"c{user_id}n"  # the filter for the user name of the given user ID. The API returns the user name for the last authenticated user with this filter, so it is important to provide the correct user ID to get the correct user name.
        user_name = self._get_status(filter)
        return user_name

    def get_authenticated_user(self) -> int:
        """Returns:
            The card index of the last authenticated user."""
        return self._get_status("lrc")

    def is_dynamic_charging_user(self) -> bool:
        """Returns:
            Whether the last authenticated user is the dynamic charging user."""
        return self.get_authenticated_user() == self.dynamic_charging_user

    def get_logic_mode(self) -> LogicMode:
        """Returns:
            The current logic mode of the charger (Default=3, Awattar=4, AutomaticStop=5)."""
        return LogicMode(self._get_status("lmo"))

    def _set_logic_mode(self, logic_mode: LogicMode) -> bool:
        """Set the logic mode of the charger.
        Args:
            logic_mode: The logic mode to set (Default=3, Awattar=4, AutomaticStop=5).
        Returns:
            True if the update succeeded, otherwise False.
        """
        return self._update_setting("lmo", logic_mode.value)

    def _is_pv_surplus_enabled(self) -> bool:
        """Returns:
            Whether the charger is configured to charge from PV surplus."""
        return self._get_status("fup")

    def _set_pv_surplus_enabled(self, enabled: bool) -> bool:
        """Enable or disable charging from PV surplus.
        Args:
            enabled: Whether to enable charging from PV surplus.
        Returns:
            True if the update succeeded, otherwise False.
        """
        return self._update_setting("fup", True if enabled else False)

    def enable_pv_surplus_charging(self) -> bool:
        """Enable charging from PV surplus. This is a convenience method that combines enabling PV surplus charging and setting the logic mode to Awattar, which is required for PV surplus charging to work."""
        ret = self._set_logic_mode(LogicMode.Awattar)
        if ret:
            return self._set_pv_surplus_enabled(True)
        return False

    def disable_pv_surplus_charging(self) -> bool:
        """Disable charging from PV surplus. This is a convenience method that combines disabling PV surplus charging and setting the logic mode to Default, which is required for PV surplus charging to work."""
        ret = self._set_pv_surplus_enabled(False)
        if ret:
            return self._set_logic_mode(LogicMode.Default)
        return False

    def set_pv_surplus_available_power(self, power: int) -> bool:
        """Set the available PV surplus power for charging in watts. This is only relevant if PV surplus charging is enabled.
        Args:
            power: The available PV surplus power in watts.
        Returns:
            True if the update succeeded, otherwise False.
        """
        ids = f"{{'pGrid': {-power}}}"  # the expected format for the available PV surplus power setting, which is a JSON object with a key "ids" and the value is the available power in watts (the API expects the available power to be negative!).
        return self._update_setting("ids", ids)

    def get_car_status(self) -> CarStatus:
        """The current status code of the car reported by the charger.
        Returns:
            None on internal errors.
            Values are: Unknown/Error=0, Idle=1, Charging=2, WaitCar=3,
            Complete=4, Error=5.
        """
        status = self._get_status("car")
        if status is None:
            return CarStatus.UNKNOWN_ERROR
        return CarStatus(status)

    def is_car_charging(self) -> bool:
        """Return whether the charger currently reports an active charging session."""
        return self.get_car_status() == CarStatus.CHARGING

    def is_car_charging_complete(self) -> bool:
        """Return whether the charger currently reports a completed charging session."""
        return self.get_car_status() == CarStatus.COMPLETE

    def is_car_charging_allowed(self) -> bool:
        """Return whether charging is currently allowed by the charger."""
        return self._get_status("alw")

    def get_error(self) -> ChargerError:
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
        err = self._get_status("err")
        return ChargerError(err) if err is not None else "Internal Error"

    def get_charger_status(self) -> ChargerStatus:
        """The charger status code reported by the charger.
        Returns:
            None on internal errors.
            Values include: NotChargingBecauseNoChargeCtrlData=0,
            NotChargingBecauseOvertemperature=1, NotChargingBecauseAccessControlWait=2,
            ChargingBecauseForceStateOn=3, NotChargingBecauseForceStateOff=4,
            NotChargingBecauseScheduler=5, NotChargingBecauseEnergyLimit=6,
            ChargingBecauseAwattarPriceLow=7, ChargingBecauseAutomaticStopTestLadung=8,
            ChargingBecauseAutomaticStopNotEnoughTime=9, ChargingBecauseAutomaticStop=10,
            ChargingBecauseAutomaticStopNoClock=11, ChargingBecausePvSurplus=12,
            ChargingBecauseFallbackGoEDefault=13, ChargingBecauseFallbackGoEScheduler=14,
            NotChargingBecausePhaseSwitch=23, NotChargingBecauseMinPauseDuration=24,
            NotChargingBecauseError=26, NotChargingBecauseLoadManagementDoesntWant=27,
            NotChargingBecauseOcppDoesntWant=28, NotChargingBecauseReconnectDelay=29,
            NotChargingBecauseAdapterBlocking=30, NotChargingBecauseUnderfrequencyControl=31,
            NotChargingBecauseUnbalancedLoad=32, ChargingBecauseDischargingPvBattery=33,
            NotChargingBecauseGridMonitoring=34, NotChargingBecauseOcppFallback=35.
        """
        status = self._get_status("modelStatus")
        if status is None:
            return None
        return ChargerStatus(status)

    def get_phases(self) -> int:
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
                log.warning(f"Unknown phase mode: {ret}")
                return -1

    def get_charging_current(self) -> int:
        """The current charging current in amperes as reported by the charger.
        Returns:
            The current charging current in amperes.
        """
        return self._get_status("amp")

    def get_configured_charging_power(self) -> int:
        """The currently configured charging power in watts as reported by the charger.
        Returns:
            The currently configured charging power in watts, or None on internal errors.
        """
        phases = self.get_phases()
        if phases == -1:
            return None
        elif phases == 0:
            # if the charger is in automatic phase switching mode, we assume 3 phases are available
            phases = 3
        current_per_phase = self.get_charging_current()
        if current_per_phase is None:
            return None
        return phases * current_per_phase * 230  # convert current in amperes to power in watts assuming 230 V

    def get_current_charging_power(self) -> int:
        """The current effective charging power in watts as reported by the charger. This is the actual power being delivered to the car.
        Returns:
            The current effective charging power in watts.
        """
        if self.is_car_charging():
            return self.get_configured_charging_power()
        return 0

    def get_total_power_average(self) -> int:
        """The 30 seconds total average power in Wh as reported by the charger.
        Returns:
            The 30 seconds total average power in Wh
        """
        tpa = self._get_status("tpa")
        # API values can arrive as numeric strings (e.g. "1234.0") or numbers.
        return int(float(tpa))

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
                log.error(f"Error getting status for filter '{filter}': {response.status_code} - {response.text}")
                return None
        except Exception as e:
            log.error(f"Error getting status for filter '{filter}': {e}")
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
                log.error(f"Error updating setting '{key}': {response.status_code} - {response.text}")
                return False
        except Exception as e:
            log.error(f"Error updating setting '{key}': {e}")
            return False

    def _get_sleep_time(self) -> int:
        return 15

    def set_charging_off(self) -> bool:
        """Force charging off."""
        ret = False
        if self.is_car_charging():
            ret = self._update_setting("frc", 1)
            time.sleep(self._get_sleep_time())  # wait for the charger to stop charging before returning to avoid issues with subsequent updates
        return ret

    def set_charging_on(self) -> bool:
        """Force charging on."""
        ret = False
        if not self.is_car_charging():
            ret = self._update_setting("frc", 2)
            time.sleep(self._get_sleep_time())  # wait for the charger to start charging before returning to avoid issues with subsequent updates
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
        log.debug(f"Setting charging phases to {phases}")
        
        current_phases = self.get_phases()
        is_car_charging = self.is_car_charging()
        charging_stopped = False
        ret = False
        
        if current_phases != phases:
            if is_car_charging:
                # turn off charging if changing the number of phases to avoid issues with the car
                self.set_charging_off()
                charging_stopped = True
        
            match phases:
                case 0:
                    ret = self._update_setting("psm", 0)
                case 1:
                    ret = self._update_setting("psm", 1)
                case 3:
                    ret = self._update_setting("psm", 2)
                case _:
                    log.error(f"Invalid number of phases: {phases}. Only 0 (auto), 1 and 3 are allowed.")
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
            True if the update was applied and succeeded, otherwise False.
        """
        log.debug(f"Setting charging current to {current}")
        
        if current < 6 or current > 16:
            log.error(f"Invalid charging current: {current}. Only values between 6 and 16 are allowed.")
            return False
        elif self.get_charging_current() != current:
            return self._update_setting("amp", current)
        return False

    def set_max_charging_power(self) -> bool:
        """Set the charger to maximum power using 3 phases and 16 A per phase."""
        ret = self._set_charging_phases(3)
        if ret:
            return self._set_charging_current(16)
        return False

    def set_charging_power(self, power: int) -> bool:
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
            log.debug(f"Requested power {power} W is too low. Minimum is {self.MINIMUM_ENERGY_CONSUMPTION} W (6 A). Turning charging off and setting minimum values.")
            ret = self.set_charging_off()
            self.set_charging_power(self.MINIMUM_ENERGY_CONSUMPTION)
            return ret
        else:
            # if the required total current is between 6 and 18 A (18 A is the minimum total current for three phases: 3x 6 A), use single phase charging with the required current
            phases_required = 1 if total_current_required < 18 else 3
            current_required = math.floor(min(total_current_required / phases_required, 16))  # the charger supports a maximum of 16 A per phase
            
            # TODO set phases and current at the same time to avoid intermediate states with wrong power, but this requires further testing to make sure that the charger accepts multiple simultaneous setting changes and applies them correctly. For now we set the phases first and then the current with a short delay in between to make sure that the charger has applied the new number of phases before we update the current to avoid issues with unsupported current-phase combinations.
            
            ret = self._set_charging_phases(phases_required)
            log.debug(f"Set charging phases to {phases_required} for requested power {power} W, return value: {ret}")
            if ret:
                ret = self._set_charging_current(current_required)
                log.debug(f"Set charging current to {current_required} A for requested power {power} W, return value: {ret}")
                if(ret):
                    self.set_charging_on()  # make sure charging is on after successfully updating the settings
                return ret
        return False
