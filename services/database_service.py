import logging
from enum import Enum
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

class ChargerAction(Enum):
    NO_ACTION = (0, "No action")
    REQUEST_DYNAMIC_CHARGING = (1, "Request dynamic charging")
    REQUEST_MAX_CHARGING = (2, "Request max charging")
    DYNAMIC_CHARGING = (3, "Dynamic charging")
    MAX_CHARGING = (4, "Max charging")
    REQUEST_STOP_CHARGING = (5, "Request stop charging")
    CHARGING_STOPPED = (6, "Charging stopped")
    SURPLUS_CHARGING = (7, "Surplus charging")
    REQUEST_SURPLUS_CHARGING = (8, "Request surplus charging")
    
    def __new__(cls, value, label):
        obj = object.__new__(cls)
        obj._value_ = value
        obj.label = label
        return obj

class HeatpumpAction(Enum):
    NO_ACTION = (0, "No action")
    REQUEST_HEATPUMP_ON = (1, "Request heatpump on")
    REQUEST_HEATPUMP_OFF = (2, "Request heatpump off")
    HEATPUMP_ON = (3, "Heatpump on")
    HEATPUMP_OFF = (4, "Heatpump off")
    
    def __new__(cls, value, label):
        obj = object.__new__(cls)
        obj._value_ = value
        obj.label = label
        return obj

class BMWCardataAuthKeys(Enum):
    USER_CODE = (0, "user_code")
    DEVICE_CODE = (1, "device_code")
    VERIFICATION_URI = (2, "verification_uri")
    GCID = (3, "gcid")
    ACCESS_TOKEN = (4, "access_token")
    REFRESH_TOKEN = (5, "refresh_token")
    ID_TOKEN = (6, "id_token")
    
    def __new__(cls, id, key):
        obj = object.__new__(cls)
        obj._value_ = id
        obj.id = id
        obj.key = key
        return obj

@dataclass(frozen=True)
class EnergyStatus:
    timestamp: datetime
    production: int
    consumption: int
    feed_in: int
    battery_feed_in: int
    car_charging: int

@dataclass(frozen=True)
class HeatpumpStatus:
    id: int
    timestamp: datetime
    device_name: str
    action: HeatpumpAction

@dataclass(frozen=True)
class ChargerStatus:
    action: ChargerAction
    timestamp: datetime
    session_id: int
    user_id: int

@dataclass(frozen=True)
class BMWCardataAuth:
    """ This class represents an entry in the bmw_cardata_auth table in the database.
        It is used to store the authentication information for the BMW CarData API,
        including the user code, device code, GCID, access token, refresh token, ID token,
        and the timestamp of when the entry was created or last updated.
        
        `expires_in` is the number of seconds until the access token expires, which can be used to determine when to refresh the token. The actual expiration time can be calculated by adding expires_in to the timestamp.
    """
    key: BMWCardataAuthKeys
    value: str
    expires_in: int
    timestamp: datetime

@dataclass(frozen=True)
class BMWCardataMessage:
    """ This class represents a message received from the BMW CarData streaming API via MQTT.
        It includes the topic of the message, the key, the value, the unit, and the timestamp of when the message was received.
    """
    topic: str
    key: str
    value: str
    unit: str
    timestamp: datetime

class DBService:
    def __init__(self, db_path, energy_status_retention_minutes: int = 60):
        self.db_path = db_path
        self._initialize_database()
        self.energy_status_retention_minutes = energy_status_retention_minutes

    def _initialize_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS relay_status (
                id INTEGER PRIMARY KEY NOT NULL,
                device_name TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                is_on BOOLEAN NOT NULL
            )
        ''')
        conn.commit()

        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS energy_status (
                timestamp DATETIME NOT NULL,
                production INTEGER NOT NULL,
                consumption INTEGER NOT NULL,
                feed_in INTEGER NOT NULL,
                battery_feed_in INTEGER NOT NULL,
                car_charging INTEGER
            )
        ''')
        conn.commit()

        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS goe_action (
                action INTEGER PRIMARY KEY NOT NULL,
                timestamp DATETIME NOT NULL,
                session_id INTEGER,
                rfid_chip_id INTEGER
            )
        ''')
        conn.commit()

        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS heatpump_action (
                id INTEGER PRIMARY KEY NOT NULL,
                device_name TEXT NOT NULL,
                action INTEGER NOT NULL,
                timestamp DATETIME NOT NULL
            )
        ''')
        conn.commit()

        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS car_charging_report (
                id INTEGER PRIMARY KEY NOT NULL,
                charger_sn TEXT NOT NULL,
                charger_name TEXT NOT NULL,
                rfid_chip_id INTEGER NOT NULL,
                rfid_chip_name TEXT NOT NULL,
                start_time DATETIME NOT NULL,
                end_time DATETIME,
                duration_minutes INTEGER,
                energy_meter_start INTEGER NOT NULL,
                energy_meter_end INTEGER,
                energy_consumed_wh INTEGER,
                current_mileage_km INTEGER
            )
        ''')
        conn.commit()

        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bmw_cardata_auth (
                id INTEGER PRIMARY KEY NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                expires_in INTEGER,
                timestamp DATETIME NOT NULL
            )
        ''')
        conn.commit()

        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bmw_cardata_message (
                id INTEGER PRIMARY KEY NOT NULL,
                topic TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                unit TEXT,
                timestamp DATETIME NOT NULL
            )
        ''')
        conn.commit()
        conn.close()

    def _clear_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM relay_status')
        cursor.execute('DELETE FROM energy_status')
        cursor.execute('DELETE FROM goe_action')
        cursor.execute('DELETE FROM heatpump_action')
        cursor.execute('DELETE FROM car_charging_report')
        conn.commit()
        conn.close()

    def create_car_charging_entry(self, charger_sn: str, charger_name: str, rfid_chip_id: int, rfid_chip_name: str, energy_meter_start: int) -> int:
        """Create a new car charging entry in the database when a charging session starts. Returns the session ID of the created entry."""
        conn = sqlite3.connect(self.db_path)
        # Check if there is already an open charging report entry. Re-use this session and don't create a new one.
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id FROM car_charging_report WHERE end_time IS NULL AND charger_sn = ?
        ''', (charger_sn,))
        # we have to get the last open entry for this charger, because there could be multiple open entries. In this case we want to continue the most recent session and not create a new one.
        result = cursor.fetchall()
        if result and len(result) > 0:
            session_id = result[-1][0]
            # same user?
            if result[-1][3] == rfid_chip_id:
                log.debug(f"Found an open charging session with ID {session_id} for charger {charger_sn} and user with rfid_chip_id {rfid_chip_id}. Re-using this session for dynamic charging.")
                conn.close()
                return session_id
            else:
                log.warning(f"Found an open charging session with ID {session_id} for charger {charger_sn}, but it belongs to a different user (rfid_chip_id {result[-1][3]}) than the current user (rfid_chip_id {rfid_chip_id}). Will close the old session and create a new charging session for the current user.")
                self.end_car_charging_entry(session_id, energy_meter_start)

        start_time = datetime.now()
        log.debug(f"Creating car charging entry in database with charger s/n {charger_sn}, charger_name {charger_name}, rfid_chip_id {rfid_chip_id}, rfid_chip_name {rfid_chip_name}, start_time {start_time}, energy_meter_start {energy_meter_start} Wh")
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO car_charging_report (charger_sn, charger_name, rfid_chip_id, rfid_chip_name, start_time, energy_meter_start)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (charger_sn, charger_name, rfid_chip_id, rfid_chip_name, start_time, energy_meter_start))
        conn.commit()
        session_id = cursor.lastrowid
        conn.close()
        return session_id

    def update_car_charging_entry_mileage(self, mileage_km: int):
        """Update the mileage of a car charging entry in the database."""
        conn = sqlite3.connect(self.db_path)
        # get the last charging entry and update the mileage, if no value is present
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id FROM car_charging_report WHERE end_time IS NULL AND current_mileage_km IS NULL ORDER BY start_time DESC LIMIT 1
        ''')
        result = cursor.fetchone()
        if result:
            session_id = result[0]
        else:
            log.debug("No open car charging entry found to update mileage.")
            conn.close()
            return

        log.debug(f"Updating mileage for car charging entry in database with session ID {session_id} to {mileage_km} km")
        cursor.execute('''
            UPDATE car_charging_report
            SET current_mileage_km = ?
            WHERE id = ?
        ''', (mileage_km, session_id))
        conn.commit()
        conn.close()

    def end_car_charging_entry(self, session_id: int, energy_meter_end: int):
        """Update a car charging entry in the database when a charging session ends. It sets the end time, calculates the duration and energy consumed, and updates the entry."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        end_time = datetime.now()
        log.debug(f"Ending car charging entry in database for session ID {session_id} with end_time {end_time} and energy_meter_end {energy_meter_end} Wh")
        cursor.execute('''
            SELECT start_time, energy_meter_start FROM car_charging_report WHERE id = ?
        ''', (session_id,))
        result = cursor.fetchone()

        if not result:
            log.warning(f"No car charging entry found with session ID {session_id}")
            conn.close()
            return

        start_time, energy_meter_start = result
        duration_minutes = int((end_time - datetime.fromisoformat(start_time)).total_seconds() / 60)
        energy_consumed_wh = max(0, energy_meter_end - energy_meter_start)  # Energy consumed in Wh

        cursor.execute('''
            UPDATE car_charging_report
            SET end_time = ?, duration_minutes = ?, energy_meter_end = ?, energy_consumed_wh = ?
            WHERE id = ?
        ''', (end_time, duration_minutes, energy_meter_end, energy_consumed_wh, session_id))
        conn.commit()
        conn.close()

    def create_goe_action(self, action: ChargerAction, session_id: int = None, user_id: int = None, force_create: bool = False) -> ChargerAction:
        """Create the current active GoE action in the database. Only one action can be active at a time."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT action, session_id FROM goe_action LIMIT 1
        ''')
        existing = cursor.fetchone()

        # If this action is already active, keep the original timestamp.
        if existing and existing[0] == action.value and (not force_create or existing[1] is None):
            conn.close()
            return action

        # Keep only one active action row at any time.
        cursor.execute('''
            DELETE FROM goe_action
        ''')

        timestamp = datetime.now()
        log.debug(f"Creating GoE action entry in database with action {action}, timestamp {timestamp}, session_id {session_id}")
        cursor.execute('''
            INSERT INTO goe_action (action, timestamp, session_id,  rfid_chip_id)
            VALUES (?, ?, ?, ?)
        ''', (action.value, timestamp, session_id, user_id))
        conn.commit()
        conn.close()
        return action

    def get_goe_action_timestamp(self) -> datetime:
        """Get the timestamp of when a specific GoE action was last set."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT timestamp FROM goe_action
        ''', )
        result = cursor.fetchone()
        conn.close()

        if result:
            return datetime.fromisoformat(result[0])
        else:
            return None

    def get_goe_action_timestamp_by_charger_action(self, action: ChargerAction) -> datetime:
        """Get the timestamp of when a specific GoE action was last set for a given charger action."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT timestamp FROM goe_action WHERE action = ?
        ''', (action.value,))
        result = cursor.fetchone()
        conn.close()

        if result:
            return datetime.fromisoformat(result[0])
        else:
            return None

    def get_goe_action_session_id(self) -> int:
        """Get the current session ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT session_id FROM goe_action
        ''', )
        result = cursor.fetchone()
        conn.close()

        if result:
            return result[0]
        else:
            return None

    def get_goe_action_session_id_by_charger_action(self, action: ChargerAction) -> int:
        """Get the current session ID associated with a specific GoE action."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT session_id FROM goe_action WHERE action = ?
        ''', (action.value,))
        result = cursor.fetchone()
        conn.close()

        if result:
            return result[0]
        else:
            return None

    def get_goe_action_user_id(self) -> int:
        """Get the user ID of the current GoE action."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT rfid_chip_id FROM goe_action
        ''', )
        result = cursor.fetchone()
        conn.close()

        if result:
            return result[0]
        else:
            return None

    def get_goe_action(self) -> ChargerAction:
        """Get the current GoE action."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT action FROM goe_action LIMIT 1
        ''')
        result = cursor.fetchone()
        conn.close()

        if result:
            return ChargerAction(result[0])
        else:
            return None

    def get_goe_status(self) -> ChargerStatus:
        """Get the current GoE status, including action, timestamp, session ID, and user ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT action, timestamp, session_id, rfid_chip_id FROM goe_action LIMIT 1
        ''')
        result = cursor.fetchone()
        conn.close()

        if result:
            return ChargerStatus(
                action=ChargerAction(result[0]),
                timestamp=datetime.fromisoformat(result[1]),
                session_id=result[2],
                user_id=result[3]
            )
        else:
            return None

    def is_goe_action(self, action: ChargerAction) -> bool:
        """Check if a specific GoE action is currently active."""
        current_action = self.get_goe_action()
        return current_action == action

    def create_heatpump_action(self, id: int, device_name: str, action: HeatpumpAction) -> HeatpumpAction:
        """Create the current active heatpump action in the database. Only one action can be active at a time for each heat pump."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f'''
            SELECT action FROM heatpump_action WHERE id = ? LIMIT 1
        ''', (id,))
        existing = cursor.fetchone()

        # If this action is already active, keep the original timestamp.
        if existing and existing[0] == action.value:
            conn.close()
            return action

        # Keep only one active action row for each device at any time.
        cursor.execute(f'''
            DELETE FROM heatpump_action where id = ?
        ''', (id,))

        timestamp = datetime.now()
        log.debug(f"Creating heatpump action entry for device {device_name} with id {id} in database for table heatpump_action with action {action} and timestamp {timestamp}")
        cursor.execute(f'''
            INSERT INTO heatpump_action (id, device_name, action, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (id, device_name, action.value, timestamp))
        conn.commit()
        conn.close()
        return action
        
    def get_heatpump_action_timestamp_by_heatpump_action(self, id: int, action: HeatpumpAction) -> datetime:
        """Get the timestamp of when a specific heatpump action was last set."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f'''
            SELECT timestamp FROM heatpump_action WHERE id = ? AND action = ? LIMIT 1
        ''', (id, action.value))
        result = cursor.fetchone()
        conn.close()

        if result:
            return datetime.fromisoformat(result[0])
        else:
            return None

    def get_heatpump_action_by_id(self, id: int) -> HeatpumpAction:
        """Get the current heatpump action for a given id."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f'''
            SELECT action FROM heatpump_action WHERE id = ? LIMIT 1
        ''', (id,))
        result = cursor.fetchone()
        conn.close()

        if result:
            return HeatpumpAction(result[0])
        else:
            return None

    def get_heatpump_status_by_id(self, id: int) -> HeatpumpStatus:
        """Get the current heatpump status for a given heatpump id."""
        log.debug(f"Fetching heatpump status from database for heatpump with id {id}")
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f'''
            SELECT device_name, action, timestamp FROM heatpump_action WHERE id = ? LIMIT 1
        ''', (id,))
        result = cursor.fetchone()
        conn.close()

        if result:
            return HeatpumpStatus(
                id=id,
                device_name=result[0],
                action=HeatpumpAction(result[1]),
                timestamp=datetime.fromisoformat(result[2])
            )
        else:
            return None

    def create_relay_status(self, id: int, device_name: str, is_on: bool):
        """Create or update the relay status entry in the database for a given device."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        timestamp = datetime.now()
        log.debug(f"Creating relay status entry in database for device {device_name} with id {id}, is_on {is_on}, and timestamp {timestamp}")
        # check, if the status needs an update or not
        cursor.execute('''
            SELECT is_on FROM relay_status WHERE id = ? LIMIT 1
        ''', (id,))
        existing = cursor.fetchone()
        if existing and existing[0] == is_on:
            conn.close()
            return
        elif existing:
            log.debug(f"Relay status entry in database for device {device_name} with id {id} already exists with is_on {existing[0]}. Updating the entry with new is_on {is_on} and timestamp {timestamp}")
            cursor.execute('''
                UPDATE relay_status
                SET timestamp = ?, is_on = ?
                WHERE id = ?
            ''', (timestamp, is_on, id))
        else:
            cursor.execute('''
                INSERT OR IGNORE INTO relay_status (id, device_name, timestamp, is_on)
                VALUES (?, ?, ?, ?)
            ''', (id, device_name, timestamp, is_on))
        conn.commit()
        conn.close()

    def get_updated_relay_timestamp(self, id: int) -> datetime:
        """Get the timestamp of the last status update for a relay device."""
        log.debug(f"Fetching updated relay timestamp from database for relay with id {id}")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT timestamp FROM relay_status WHERE id = ?
        ''', (id,))
        result = cursor.fetchone()
        conn.close()

        # Values are stored using datetime.now(), so return them directly.
        if result:
            return datetime.fromisoformat(result[0])
        else:
            return None

    def create_energy_status(self, production: int, consumption: int, feed_in: int, battery_feed_in: int, car_charging: int = None):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        timestamp = datetime.now()
        log.debug(f"Creating energy status entry in database with timestamp {timestamp}, production {production} W, consumption {consumption} W, feed_in {feed_in} W, battery_feed_in {battery_feed_in} W, car_charging {car_charging} W")
        cursor.execute('''
            INSERT INTO energy_status (timestamp, production, consumption, feed_in, battery_feed_in, car_charging)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (timestamp, production, consumption, feed_in, battery_feed_in, car_charging))
        conn.commit()
        conn.close()
        
    def get_energy_status_time_series(self, minutes: int) -> list[EnergyStatus]:
        """Get energy status entries from the last specified number of minutes."""
        self._clean_up_old_energy_status(self.energy_status_retention_minutes)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        log.debug(f"Fetching energy status entries from database since cutoff time {cutoff_time}")
        cursor.execute('''
            SELECT timestamp, production, consumption, feed_in, battery_feed_in, car_charging
            FROM energy_status
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
        ''', (cutoff_time,))
        rows = cursor.fetchall()
        conn.close()
        series = [
            EnergyStatus(
                timestamp=row[0],
                production=row[1],
                consumption=row[2],
                feed_in=row[3],
                battery_feed_in=row[4],
                car_charging=row[5]
            )
            for row in rows
        ]
        return series[-minutes:]  # Return only the last 'minutes' entries to limit the size of the returned data
        
    def _clean_up_old_energy_status(self, minutes: int):
        """Delete energy status entries that are older than the specified number of minutes."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        log.debug(f"Cleaning up old energy status entries from database before cutoff time {cutoff_time}")
        cursor.execute('''
            DELETE FROM energy_status WHERE timestamp < ?
        ''', (cutoff_time,))
        conn.commit()
        conn.close()
        
    def create_bmw_cardata_auth_entry(self, entry: BMWCardataAuth):
        """Create or update an entry in the bmw_cardata_auth table for a given key."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        log.debug(f"Creating/updating BMW CarData auth entry in database for {entry.key.key} and timestamp {entry.timestamp}")
        # check, if the entry needs an update or not
        cursor.execute('''
            SELECT value FROM bmw_cardata_auth WHERE id = ? LIMIT 1
        ''', (entry.key.id,))
        existing = cursor.fetchone()
        if existing and existing[0] == entry.value:
            conn.close()
            return
        elif existing:
            log.debug(f"BMW CarData auth entry in database for key {entry.key.key} already exists with value {existing[0]}. Updating the entry with new value {entry.value}, expires_in {entry.expires_in}, and timestamp {entry.timestamp}")
            cursor.execute('''
                UPDATE bmw_cardata_auth
                SET value = ?, expires_in = ?, timestamp = ?
                WHERE id = ?
            ''', (entry.value, entry.expires_in, entry.timestamp, entry.key.id))
        else:
            cursor.execute('''
                INSERT INTO bmw_cardata_auth (id, key, value, expires_in, timestamp)
                VALUES (?, ?, ?, ?, ?)
            ''', (entry.key.id, entry.key.key, entry.value, entry.expires_in, entry.timestamp))
        conn.commit()
        conn.close()
              
    def delete_bmw_cardata_auth_entry(self, key: BMWCardataAuthKeys):
        """Delete an entry from the bmw_cardata_auth table for a given key."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        log.debug(f"Deleting BMW CarData auth entry from database for key {key.key}")
        cursor.execute('''
            DELETE FROM bmw_cardata_auth WHERE id = ?
        ''', (key.id,))
        conn.commit()
        conn.close()
        
    def get_bmw_cardata_auth_entry(self, key: BMWCardataAuthKeys) -> BMWCardataAuth:
        """Get an entry from the bmw_cardata_auth table for a given key."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        log.debug(f"Fetching BMW CarData auth entry from database for key {key.key}")
        cursor.execute('''
            SELECT value, expires_in, timestamp FROM bmw_cardata_auth WHERE id = ? LIMIT 1
        ''', (key.id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return BMWCardataAuth(
                key=key,
                value=row[0],
                expires_in=row[1],
                timestamp=datetime.fromisoformat(row[2])
            )
        return None
    
    def create_bmw_cardata_message_entry(self, message: BMWCardataMessage):
        """Create a new entry in the bmw_cardata_message table for a received MQTT message from the BMW CarData streaming API."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        log.debug(f"Creating BMW CarData message entry in database for topic {message.topic}, key {message.key}, value {message.value}, unit {message.unit}, and timestamp {message.timestamp}")
        # check, if the entry needs an update or not based on the topic and key, because there could be multiple messages with the same topic but different keys
        cursor.execute('''
            SELECT id FROM bmw_cardata_message WHERE topic = ? AND key = ? LIMIT 1
        ''', (message.topic, message.key))
        existing = cursor.fetchone()
        if existing:
            log.debug(f"BMW CarData message entry in database for topic {message.topic} and key {message.key} already exists with value {existing[0]}. Updating the entry with new value {message.value}, unit {message.unit}, and timestamp {message.timestamp}")
            cursor.execute('''
                UPDATE bmw_cardata_message
                SET value = ?, unit = ?, timestamp = ?
                WHERE id = ?
            ''', (message.value, message.unit, message.timestamp, existing[0]))
        else:
            cursor.execute('''
                INSERT INTO bmw_cardata_message (topic, key, value, unit, timestamp)
                VALUES (?, ?, ?, ?, ?)
            ''', (message.topic, message.key, message.value, message.unit, message.timestamp))
        conn.commit()
        conn.close()
        
    def get_bmw_cardata_message_entry(self, topic: str, key: str) -> BMWCardataMessage:
        """Get an entry from the bmw_cardata_message table for a given topic and key."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        log.debug(f"Fetching BMW CarData message entry from database for topic {topic} and key {key}")
        cursor.execute('''
            SELECT value, unit, timestamp FROM bmw_cardata_message WHERE topic = ? AND key = ? LIMIT 1
        ''', (topic, key))
        row = cursor.fetchone()
        conn.close()
        if row:
            return BMWCardataMessage(
                topic=topic,
                key=key,
                value=row[0],
                unit=row[1],
                timestamp=datetime.fromisoformat(row[2])
            )
        return None