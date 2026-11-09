import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class MarketDataStorage:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.initialize()

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def initialize(self):
        with self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS market_snapshots (
                    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    index_price REAL,
                    status TEXT NOT NULL,
                    reason TEXT
                )
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS selected_pairs (
                    snapshot_id INTEGER PRIMARY KEY,
                    expiry TEXT NOT NULL,
                    strike REAL NOT NULL,
                    settlement TEXT NOT NULL,
                    call_symbol TEXT NOT NULL,
                    put_symbol TEXT NOT NULL,
                    call_bid REAL NOT NULL,
                    call_ask REAL NOT NULL,
                    call_bid_size REAL NOT NULL,
                    call_ask_size REAL NOT NULL,
                    put_bid REAL NOT NULL,
                    put_ask REAL NOT NULL,
                    put_bid_size REAL NOT NULL,
                    put_ask_size REAL NOT NULL,
                    combined_entry_bid REAL NOT NULL,
                    combined_buyback_ask REAL NOT NULL,
                    FOREIGN KEY (snapshot_id)
                        REFERENCES market_snapshots(snapshot_id)
                        ON DELETE CASCADE
                )
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS engine_heartbeat (
                    worker_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    details TEXT
                )
            """)
            self.connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_snapshots_captured
                ON market_snapshots(captured_at DESC)
            """)

    def save_snapshot(self, index_price, status, reason=None, pair=None):
        captured_at = self.now()
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO market_snapshots "
                "(captured_at, index_price, status, reason) VALUES (?, ?, ?, ?)",
                (captured_at, index_price, status, reason),
            )
            snapshot_id = cursor.lastrowid
            if pair is not None:
                call = pair["call"]
                put = pair["put"]
                self.connection.execute("""
                    INSERT INTO selected_pairs (
                        snapshot_id, expiry, strike, settlement,
                        call_symbol, put_symbol,
                        call_bid, call_ask, call_bid_size, call_ask_size,
                        put_bid, put_ask, put_bid_size, put_ask_size,
                        combined_entry_bid, combined_buyback_ask
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    snapshot_id,
                    pair["expiry"].isoformat(),
                    float(pair["strike"]),
                    str(pair["settlement"]),
                    call.symbol,
                    put.symbol,
                    float(call.bid1_price or 0),
                    float(call.ask1_price or 0),
                    float(call.bid1_size or 0),
                    float(call.ask1_size or 0),
                    float(put.bid1_price or 0),
                    float(put.ask1_price or 0),
                    float(put.bid1_size or 0),
                    float(put.ask1_size or 0),
                    float(pair["combined_entry_bid"]),
                    float(pair["combined_buyback_ask"]),
                ))
        return snapshot_id

    def update_heartbeat(self, worker_id, status, details=None):
        with self.connection:
            self.connection.execute("""
                INSERT INTO engine_heartbeat (worker_id, status, last_seen, details)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    status = excluded.status,
                    last_seen = excluded.last_seen,
                    details = excluded.details
            """, (worker_id, status, self.now(), details))

    def close(self):
        self.connection.close()
