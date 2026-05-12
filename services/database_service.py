from enum import Enum
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta


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
                timestamp DATETIME PRIMARY KEY NOT NULL,
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
                timestamp DATETIME NOT NULL
            )
        ''')
        conn.commit()
        conn.close()

    def create_goe_action(self, action: ChargerAction):
        """Create the current active GoE action in the database. Only one action can be active at a time."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT action FROM goe_action LIMIT 1
        ''')
        existing = cursor.fetchone()

        # If this action is already active, keep the original timestamp.
        if existing and existing[0] == action.value:
            conn.close()
            return

        # Keep only one active action row at any time.
        cursor.execute('''
            DELETE FROM goe_action
        ''')

        timestamp = datetime.now()
        cursor.execute('''
            INSERT INTO goe_action (action, timestamp)
            VALUES (?, ?)
        ''', (action.value, timestamp))
        conn.commit()
        conn.close()

    def get_goe_action_timestamp(self, action: ChargerAction) -> datetime:
        """Get the timestamp of when a specific GoE action was last set."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT timestamp FROM goe_action WHERE action = ?
        ''', (action.value,))
        result = cursor.fetchone()
        conn.close()

        if result:
            return result[0]
        else:
            return None

    def create_relay_status(self, id: int, device_name: str, is_on: bool):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        timestamp = datetime.now()
        cursor.execute('''
            INSERT OR IGNORE INTO relay_status (id, device_name, timestamp, is_on)
            VALUES (?, ?, ?, ?)
        ''', (id, device_name, timestamp, is_on))
        conn.commit()
        conn.close()

    def update_relay_status(self, id: int, is_on: bool):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        timestamp = datetime.now()
        cursor.execute('''
            UPDATE relay_status
            SET timestamp = ?, is_on = ?
            WHERE id = ?
        ''', (timestamp, is_on, id))
        conn.commit()
        conn.close()

    def get_updated_relay_timestamp(self, id: int) -> datetime:
        """Get the timestamp of the last status update for a relay device."""
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT timestamp FROM relay_status WHERE id = ?
        ''', (id,))
        result = cursor.fetchone()
        conn.close()

        # Values are stored using datetime.now(), so return them directly.
        return result[0]

    def create_energy_status(self, production: int, consumption: int, feed_in: int):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        timestamp = datetime.now()
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
        cursor.execute('''
            DELETE FROM energy_status WHERE timestamp < ?
        ''', (cutoff_time,))
        conn.commit()
        conn.close()
        