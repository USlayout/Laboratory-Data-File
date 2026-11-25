"""Local SQLite snapshots; original measurement folders are never modified."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class History:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                connection.execute("CREATE TABLE IF NOT EXISTS analyses (id INTEGER PRIMARY KEY, created TEXT, environment TEXT, source TEXT, report TEXT)")
                yield connection
        finally:
            connection.close()

    def add(self, report):
        with self.connect() as connection:
            cursor = connection.execute("INSERT INTO analyses(created, environment, source, report) VALUES (?,?,?,?)",
                                        (report["created"], report["environment"], report["source"], json.dumps(report, ensure_ascii=False, allow_nan=False)))
            return cursor.lastrowid

    def entries(self):
        with self.connect() as connection:
            return connection.execute("SELECT id, created, environment, source FROM analyses ORDER BY id DESC").fetchall()

    def load(self, identity):
        with self.connect() as connection:
            row = connection.execute("SELECT report FROM analyses WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise ValueError("履歴が見つかりません")
        return json.loads(row[0])

    def delete(self, identity):
        with self.connect() as connection:
            connection.execute("DELETE FROM analyses WHERE id=?", (identity,))
