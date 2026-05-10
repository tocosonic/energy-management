import sqlite3
from datetime import datetime

class DBService:
    def __init__(self, db_path):
        self.db_path = db_path
        self._initialize_database()

    def _initialize_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS relay_status (
                id INTEGER PRIMARY KEY NOT NULL,
                device_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                is_on BOOLEAN NOT NULL
            )
        ''')
        conn.commit()
        conn.close()

    def create_relay_status(self, id: int, device_name: str, is_on: bool):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        cursor.execute('''
            INSERT OR IGNORE INTO relay_status (id, device_name, timestamp, is_on)
            VALUES (?, ?, ?, ?)
        ''', (id, device_name, timestamp, is_on))
        conn.commit()
        conn.close()

    def update_relay_status(self, id: int, is_on: bool):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
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

        # Values are stored using datetime.now().isoformat(), so parse them back.
        return datetime.fromisoformat(result[0])
