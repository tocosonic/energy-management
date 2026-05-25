import logging
from enum import Enum
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

@dataclass(frozen=True)
class EnergyStatus:
    timestamp: datetime
    production: int
    consumption: int
    feed_in: int

class ChargerAction(Enum):
    NO_ACTION = 0
    REQUEST_DYNAMIC_CHARGING = 1
    REQUEST_MAX_CHARGING = 2
    DYNAMIC_CHARGING = 3
    MAX_CHARGING = 4
    REQUEST_STOP_CHARGING = 5
    CHARGING_STOPPED = 6
    SURPLUS_CHARGING = 7
    REQUEST_SURPLUS_CHARGING = 8

class HeatpumpAction(Enum):
    NO_ACTION = 0
    REQUEST_HEATPUMP_ON = 1
    REQUEST_HEATPUMP_OFF = 2
    HEATPUMP_ON = 3
    HEATPUMP_OFF = 4

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
                feed_in INTEGER NOT NULL
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
                energy_consumed_wh INTEGER
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
        start_time = datetime.now()
        log.debug(f"Creating car charging entry in database with charger s/n {charger_sn}, charger_name {charger_name}, rfid_chip_id {rfid_chip_id}, rfid_chip_name {rfid_chip_name}, start_time {start_time}, energy_meter_start {energy_meter_start} Wh")
        # TODO update to close a non-closed previous entry for the same charger


        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO car_charging_report (charger_sn, charger_name, rfid_chip_id, rfid_chip_name, start_time, energy_meter_start)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (charger_sn, charger_name, rfid_chip_id, rfid_chip_name, start_time, energy_meter_start))
        conn.commit()
        session_id = cursor.lastrowid
        conn.close()
        return session_id

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

    def create_goe_action(self, action: ChargerAction, session_id: int = None, user_id: int = None, force: bool = False) -> ChargerAction:
        """Create the current active GoE action in the database. Only one action can be active at a time."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT action FROM goe_action LIMIT 1
        ''')
        existing = cursor.fetchone()

        # If this action is already active, keep the original timestamp.
        if existing and existing[0] == action.value and not force:
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

    def create_energy_status(self, production: int, consumption: int, feed_in: int):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        timestamp = datetime.now()
        log.debug(f"Creating energy status entry in database with timestamp {timestamp}, production {production} W, consumption {consumption} W, feed_in {feed_in} W")
        cursor.execute('''
            INSERT INTO energy_status (timestamp, production, consumption, feed_in)
            VALUES (?, ?, ?, ?)
        ''', (timestamp, production, consumption, feed_in))
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
            SELECT timestamp, production, consumption, feed_in
            FROM energy_status
            WHERE timestamp >= ?
            ORDER BY timestamp DESC
        ''', (cutoff_time,))
        rows = cursor.fetchall()
        conn.close()

        return [
            EnergyStatus(
                timestamp=row[0],
                production=row[1],
                consumption=row[2],
                feed_in=row[3],
            )
            for row in rows
        ]
        
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
        