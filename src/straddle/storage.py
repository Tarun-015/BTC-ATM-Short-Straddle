import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class SQLiteStorage:

    def __init__(self, db_path):
        self.db_path = str(db_path)

        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

        self.initialize()

    def _now(self):
        return datetime.now(timezone.utc).isoformat()

    def _value(self, value):
        if hasattr(value, "value"):
            return value.value
        return value

    def _get(self, obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def initialize(self):
        with self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    requested_quantity TEXT NOT NULL,
                    recovery_required INTEGER NOT NULL DEFAULT 0,
                    recovery_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS trade_legs (
                    trade_id TEXT NOT NULL,
                    leg TEXT NOT NULL,
                    state TEXT NOT NULL,
                    entry_filled_quantity TEXT NOT NULL DEFAULT '0',
                    exit_filled_quantity TEXT NOT NULL DEFAULT '0',
                    PRIMARY KEY (trade_id, leg),
                    FOREIGN KEY (trade_id)
                        REFERENCES trades(trade_id)
                        ON DELETE CASCADE
                )
            """)

            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    trade_id TEXT NOT NULL,
                    leg TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    requested_quantity TEXT NOT NULL,
                    filled_quantity TEXT NOT NULL DEFAULT '0',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (trade_id)
                        REFERENCES trades(trade_id)
                        ON DELETE CASCADE
                )
            """)

            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS execution_events (
                    event_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    trade_id TEXT NOT NULL,
                    leg TEXT NOT NULL,
                    role TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    price TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    FOREIGN KEY (order_id)
                        REFERENCES orders(order_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (trade_id)
                        REFERENCES trades(trade_id)
                        ON DELETE CASCADE
                )
            """)

            self.connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_orders_trade_id
                ON orders(trade_id)
            """)

            self.connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_trade_id
                ON execution_events(trade_id)
            """)

            self.connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_order_id
                ON execution_events(order_id)
            """)

            trade_columns = {
                row["name"]
                for row in self.connection.execute(
                    "PRAGMA table_info(trades)"
                ).fetchall()
            }

            if "recovery_required" not in trade_columns:
                self.connection.execute("""
                    ALTER TABLE trades
                    ADD COLUMN recovery_required INTEGER NOT NULL DEFAULT 0
                """)

            if "recovery_reason" not in trade_columns:
                self.connection.execute("""
                    ALTER TABLE trades
                    ADD COLUMN recovery_reason TEXT
                """)

    def save_trade(self, trade):
        trade_id = self._get(trade, "trade_id")
        state = self._value(self._get(trade, "state"))
        requested_quantity = str(
            self._get(trade, "requested_quantity", "0")
        )
        recovery_required = int(
            bool(self._get(trade, "recovery_required", False))
        )
        recovery_reason = self._get(trade, "recovery_reason")

        now = self._now()

        with self.connection:
            self.connection.execute("""
                INSERT INTO trades (
                    trade_id,
                    state,
                    requested_quantity,
                    recovery_required,
                    recovery_reason,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_id) DO UPDATE SET
                    state = excluded.state,
                    requested_quantity = excluded.requested_quantity,
                    recovery_required = excluded.recovery_required,
                    recovery_reason = excluded.recovery_reason,
                    updated_at = excluded.updated_at
            """, (
                trade_id,
                state,
                requested_quantity,
                recovery_required,
                recovery_reason,
                now,
                now,
            ))

            legs = self._get(trade, "legs", {})

            for leg_name, leg_state in legs.items():
                leg_value = self._value(leg_state)

                filled_quantities = self._get(
                    trade,
                    "filled_quantities",
                    {},
                )

                exit_filled_quantities = self._get(
                    trade,
                    "exit_filled_quantities",
                    {},
                )

                entry_filled = str(
                    filled_quantities.get(leg_name, "0")
                )

                exit_filled = str(
                    exit_filled_quantities.get(leg_name, "0")
                )

                self.connection.execute("""
                    INSERT INTO trade_legs (
                        trade_id,
                        leg,
                        state,
                        entry_filled_quantity,
                        exit_filled_quantity
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(trade_id, leg) DO UPDATE SET
                        state = excluded.state,
                        entry_filled_quantity =
                            excluded.entry_filled_quantity,
                        exit_filled_quantity =
                            excluded.exit_filled_quantity
                """, (
                    trade_id,
                    leg_name,
                    leg_value,
                    entry_filled,
                    exit_filled,
                ))

    def save_order(self, order):
        order_id = order["order_id"]
        trade_id = order["trade_id"]
        leg = self._value(order["leg"])
        role = self._value(order["role"])
        status = self._value(order["status"])
        requested_quantity = str(order.get("requested_quantity", "0"))
        filled_quantity = str(order.get("filled_quantity", "0"))
        created_at = order.get("created_at") or self._now()

        with self.connection:
            self.connection.execute("""
                INSERT INTO orders (
                    order_id,
                    trade_id,
                    leg,
                    role,
                    status,
                    requested_quantity,
                    filled_quantity,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    trade_id = excluded.trade_id,
                    leg = excluded.leg,
                    role = excluded.role,
                    status = excluded.status,
                    requested_quantity = excluded.requested_quantity,
                    filled_quantity = excluded.filled_quantity
            """, (
                order_id,
                trade_id,
                leg,
                role,
                status,
                requested_quantity,
                filled_quantity,
                created_at,
            ))

    def save_execution_event(self, event):
        with self.connection:
            cursor = self.connection.execute("""
                INSERT OR IGNORE INTO execution_events (
                    event_id,
                    order_id,
                    trade_id,
                    leg,
                    role,
                    quantity,
                    price,
                    event_time
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event["event_id"],
                event["order_id"],
                event["trade_id"],
                self._value(event["leg"]),
                self._value(event["role"]),
                str(event["quantity"]),
                str(event["price"]),
                event["event_time"],
            ))

        return cursor.rowcount == 1
    
    def get_trade(self, trade_id):
        row = self.connection.execute(
            """
            SELECT *
            FROM trades
            WHERE trade_id = ?
            """,
            (trade_id,),
        ).fetchone()

        return dict(row) if row else None

    def get_trade_legs(self, trade_id):
        rows = self.connection.execute(
            """
            SELECT *
            FROM trade_legs
            WHERE trade_id = ?
            ORDER BY leg
            """,
            (trade_id,),
        ).fetchall()

        return [dict(row) for row in rows]

    def get_orders(self, trade_id):
        rows = self.connection.execute(
            """
            SELECT *
            FROM orders
            WHERE trade_id = ?
            ORDER BY created_at
            """,
            (trade_id,),
        ).fetchall()

        return [dict(row) for row in rows]

    def get_execution_events(self, trade_id):
        rows = self.connection.execute(
            """
            SELECT *
            FROM execution_events
            WHERE trade_id = ?
            ORDER BY event_time
            """,
            (trade_id,),
        ).fetchall()

        return [dict(row) for row in rows]

    def save_trade_manager(self, trade_manager):
        self.save_trade(trade_manager)

        orders = getattr(trade_manager, "orders", {})

        for key, order in orders.items():
            order_data = dict(order)

            order_data.setdefault("order_id", key)
            order_data.setdefault(
                "trade_id",
                trade_manager.trade_id,
            )
            order_data.setdefault(
                "requested_quantity",
                trade_manager.requested_quantity,
            )
            order_data.setdefault("created_at", self._now())

            self.save_order(order_data)

        events = getattr(trade_manager, "execution_events", [])

        for event in events:
            event_data = dict(event)

            if event_data.get("type") == "ORDER_STATUS":
                continue

            required_fields = (
                "event_id",
                "order_id",
                "leg",
                "role",
                "quantity",
                "price",
                "event_time",
            )

            if any(
                event_data.get(field) is None
                for field in required_fields
            ):
                continue

            event_data["trade_id"] = trade_manager.trade_id

            self.save_execution_event(event_data)

    def load_trade_snapshot(self, trade_id):
        trade = self.connection.execute("""
            SELECT *
            FROM trades
            WHERE trade_id = ?
        """, (trade_id,)).fetchone()

        if trade is None:
            return None

        legs = self.connection.execute("""
            SELECT *
            FROM trade_legs
            WHERE trade_id = ?
            ORDER BY leg
        """, (trade_id,)).fetchall()

        orders = self.connection.execute("""
            SELECT *
            FROM orders
            WHERE trade_id = ?
            ORDER BY created_at
        """, (trade_id,)).fetchall()

        events = self.connection.execute("""
            SELECT *
            FROM execution_events
            WHERE trade_id = ?
            ORDER BY event_time
        """, (trade_id,)).fetchall()

        return {
            "trade": dict(trade),
            "legs": [dict(row) for row in legs],
            "orders": [dict(row) for row in orders],
            "execution_events": [
                dict(row) for row in events
            ],
        }

    def close(self):
        self.connection.close()
        
    def get_trade(self, trade_id):
        row = self.connection.execute(
            """
            SELECT *
            FROM trades
            WHERE trade_id = ?
            """,
            (trade_id,),
        ).fetchone()

        return dict(row) if row else None

    def get_trade_legs(self, trade_id):
        rows = self.connection.execute(
            """
            SELECT *
            FROM trade_legs
            WHERE trade_id = ?
            ORDER BY leg
            """,
            (trade_id,),
        ).fetchall()

        return [dict(row) for row in rows]

    def get_orders(self, trade_id):
        rows = self.connection.execute(
            """
            SELECT *
            FROM orders
            WHERE trade_id = ?
            ORDER BY created_at
            """,
            (trade_id,),
        ).fetchall()

        return [dict(row) for row in rows]

    def get_execution_events(self, trade_id):
        rows = self.connection.execute(
            """
            SELECT *
            FROM execution_events
            WHERE trade_id = ?
            ORDER BY event_time
            """,
            (trade_id,),
        ).fetchall()

        return [dict(row) for row in rows]