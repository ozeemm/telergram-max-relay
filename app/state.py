import sqlite3
from pathlib import Path


class StateStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_notifications (
                receipt_id TEXT PRIMARY KEY,
                processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.connection.commit()

    def is_processed(self, receipt_id: str | int) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM processed_notifications WHERE receipt_id = ?",
            (str(receipt_id),),
        ).fetchone()
        return row is not None

    def mark_processed(self, receipt_id: str | int) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO processed_notifications (receipt_id) VALUES (?)",
            (str(receipt_id),),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
