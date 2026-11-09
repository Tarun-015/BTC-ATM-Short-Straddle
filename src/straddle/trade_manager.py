
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from src.straddle.trade_state import TradeState, LegState


def to_decimal(value):
    """Safely convert a value to a finite Decimal."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None

    if not result.is_finite():
        return None

    return result


@dataclass
class TradeManager:
    trade_id: str

    state: TradeState = TradeState.CREATED

    legs: dict = field(default_factory=lambda: {
        "CALL": LegState.PENDING,
        "PUT": LegState.PENDING,
    })

    exit_requested: bool = False

    requested_quantity: Decimal = Decimal("0.01")

    filled_quantities: dict = field(default_factory=lambda: {
        "CALL": Decimal("0"),
        "PUT": Decimal("0"),
    })

    exit_filled_quantities: dict = field(default_factory=lambda: {
        "CALL": Decimal("0"),
        "PUT": Decimal("0"),
    })

    max_exit_retries: int = 3

    exit_retry_counts: dict = field(default_factory=lambda: {
        "CALL": 0,
        "PUT": 0,
    })

    # Local order and execution tracking.
    orders: dict = field(default_factory=dict)
    order_slots: dict = field(default_factory=dict)

    execution_events: list = field(default_factory=list)
    execution_event_ids: set = field(default_factory=set)
    recovery_required: bool = False
    recovery_reason: str | None = None
    
    def mark_recovery_required(self, reason):
        """Record that an unfinished trade needs manual recovery."""
        if self.state in (TradeState.CLOSED, TradeState.FAILED):
            return False

        self.recovery_required = True
        self.recovery_reason = str(reason)
        return True

    def __post_init__(self):
        self.requested_quantity = to_decimal(
            self.requested_quantity
        )

        if (
            not self.trade_id
            or self.requested_quantity is None
            or self.requested_quantity <= 0
            or self.max_exit_retries < 0
        ):
            raise ValueError("Invalid trade configuration")

    def start_entry(self):
        if self.state != TradeState.CREATED:
            return False

        self.state = TradeState.ENTRY_PENDING
        return True

    def update_leg(self, leg, new_state):
        """Update a leg while enforcing valid state transitions."""

        if leg not in self.legs:
            return False

        if not isinstance(new_state, LegState):
            return False

        current = self.legs[leg]

        allowed = {
            LegState.PENDING: {
                LegState.PENDING,
                LegState.PARTIALLY_FILLED,
                LegState.FILLED,
                LegState.FAILED,
            },
            LegState.PARTIALLY_FILLED: {
                LegState.PARTIALLY_FILLED,
                LegState.FILLED,
                LegState.FAILED,
            },
            LegState.FILLED: {
                LegState.FILLED,
            },
        }

        if new_state not in allowed.get(current, set()):
            return False

        if self.state not in (
            TradeState.ENTRY_PENDING,
            TradeState.PARTIALLY_FILLED,
        ):
            return False

        self.legs[leg] = new_state

        # A direct FILLED update represents a complete fill.
        if new_state == LegState.FILLED:
            self.filled_quantities[leg] = self.requested_quantity

        self._update_trade_state()
        return True

    def record_entry_fill(self, leg, fill_quantity):
        """Record an incremental entry fill."""

        if leg not in self.legs:
            return False

        if self.state not in (
            TradeState.ENTRY_PENDING,
            TradeState.PARTIALLY_FILLED,
        ):
            return False

        if self.legs[leg] not in (
            LegState.PENDING,
            LegState.PARTIALLY_FILLED,
        ):
            return False

        quantity = to_decimal(fill_quantity)

        if quantity is None or quantity <= 0:
            return False

        new_total = self.filled_quantities[leg] + quantity

        if new_total > self.requested_quantity:
            return False

        self.filled_quantities[leg] = new_total

        if new_total == self.requested_quantity:
            self.legs[leg] = LegState.FILLED
        else:
            self.legs[leg] = LegState.PARTIALLY_FILLED

        self._update_trade_state()
        return True

    def remaining_quantity(self, leg):
        if leg not in self.legs:
            return None

        return (
            self.requested_quantity
            - self.filled_quantities[leg]
        )

    def remaining_exposure(self, leg):
        if leg not in self.legs:
            return None

        return (
            self.filled_quantities[leg]
            - self.exit_filled_quantities[leg]
        )

    def _update_trade_state(self):
        states = list(self.legs.values())

        if self.state == TradeState.RECOVERY_PENDING:
            if all(
                state != LegState.EXIT_PENDING
                for state in states
            ):
                self.state = TradeState.FAILED
            return

        if LegState.FAILED in states:
            exposed = any(
                state in (
                    LegState.PARTIALLY_FILLED,
                    LegState.FILLED,
                    LegState.EXIT_PENDING,
                )
                for state in states
            )

            self.state = (
                TradeState.RECOVERY_REQUIRED
                if exposed
                else TradeState.FAILED
            )
            return

        if all(state == LegState.CLOSED for state in states):
            self.state = TradeState.CLOSED

        elif all(state == LegState.FILLED for state in states):
            self.state = TradeState.OPEN

        elif any(
            state in (
                LegState.PARTIALLY_FILLED,
                LegState.FILLED,
            )
            for state in states
        ):
            self.state = TradeState.PARTIALLY_FILLED

    def request_exit(self):
        """Request a normal exit exactly once."""

        if self.state != TradeState.OPEN:
            return False

        if self.exit_requested:
            return False

        self.exit_requested = True

        for leg, state in self.legs.items():
            if state == LegState.FILLED:
                self.legs[leg] = LegState.EXIT_PENDING

        self.state = TradeState.EXIT_PENDING
        return True

    def request_recovery_exit(self):
        """Request exit of all exposed legs after entry failure."""

        if self.state != TradeState.RECOVERY_REQUIRED:
            return False

        exposed_legs = [
            leg
            for leg, state in self.legs.items()
            if state in (
                LegState.PARTIALLY_FILLED,
                LegState.FILLED,
            )
        ]

        if not exposed_legs:
            self.state = TradeState.FAILED
            return False

        for leg in exposed_legs:
            self.legs[leg] = LegState.EXIT_PENDING

        self.state = TradeState.RECOVERY_PENDING
        return True

    def record_exit_fill(self, leg, fill_quantity):
        """Record an incremental buyback fill."""

        if leg not in self.legs:
            return False

        if self.state not in (
            TradeState.EXIT_PENDING,
            TradeState.RECOVERY_PENDING,
        ):
            return False

        if self.legs[leg] != LegState.EXIT_PENDING:
            return False

        quantity = to_decimal(fill_quantity)

        if quantity is None or quantity <= 0:
            return False

        new_total = self.exit_filled_quantities[leg] + quantity

        if new_total > self.filled_quantities[leg]:
            return False

        self.exit_filled_quantities[leg] = new_total

        if new_total == self.filled_quantities[leg]:
            self.legs[leg] = LegState.CLOSED
            self._update_trade_state()

        return True

    def confirm_leg_closed(self, leg):
        """Confirm closure only after complete quantity reconciliation."""

        if leg not in self.legs:
            return False

        if self.state not in (
            TradeState.EXIT_PENDING,
            TradeState.RECOVERY_PENDING,
        ):
            return False

        if self.legs[leg] != LegState.EXIT_PENDING:
            return False

        entry_filled = self.filled_quantities[leg]
        exit_filled = self.exit_filled_quantities[leg]

        if entry_filled <= 0 or exit_filled != entry_filled:
            return False

        self.legs[leg] = LegState.CLOSED
        self._update_trade_state()
        return True

    def record_exit_failure(self, leg):
        """Record an exit failure without removing open exposure."""

        if leg not in self.legs:
            return False

        if self.state not in (
            TradeState.EXIT_PENDING,
            TradeState.RECOVERY_PENDING,
        ):
            return False

        if self.legs[leg] != LegState.EXIT_PENDING:
            return False

        if self.exit_retry_counts[leg] >= self.max_exit_retries:
            return False

        self.exit_retry_counts[leg] += 1
        return True

    def can_retry_exit(self, leg):
        if leg not in self.legs:
            return False

        return (
            self.legs[leg] == LegState.EXIT_PENDING
            and self.exit_retry_counts[leg] < self.max_exit_retries
            and self.state in (
                TradeState.EXIT_PENDING,
                TradeState.RECOVERY_PENDING,
            )
        )

    # -------------------------------------------------
    # Order tracking
    # -------------------------------------------------

    def register_order(self, leg, role, order_id):
        """Register a local order record."""

        if leg not in self.legs:
            return False

        if role not in ("ENTRY", "EXIT"):
            return False

        if not isinstance(order_id, str) or not order_id.strip():
            return False

        if order_id in self.orders:
            return False

        slot = (leg, role)
        previous_id = self.order_slots.get(slot)

        if previous_id is not None:
            previous_status = self.orders[previous_id]["status"]

            if previous_status not in (
                "FILLED",
                "CANCELLED",
                "REJECTED",
            ):
                return False

        self.orders[order_id] = {
            "order_id": order_id,
            "leg": leg,
            "role": role,
            "status": "NEW",
            "filled_quantity": Decimal("0"),
        }

        self.order_slots[slot] = order_id
        return True

    def update_order_status(self, order_id, new_status):
        """Update a registered order's status."""

        allowed_statuses = {
            "NEW",
            "OPEN",
            "PARTIALLY_FILLED",
            "FILLED",
            "CANCELLED",
            "REJECTED",
        }

        if order_id not in self.orders:
            return False

        if new_status not in allowed_statuses:
            return False

        order = self.orders[order_id]
        current = order["status"]

        transitions = {
            "NEW": {
                "NEW",
                "OPEN",
                "PARTIALLY_FILLED",
                "FILLED",
                "CANCELLED",
                "REJECTED",
            },
            "OPEN": {
                "OPEN",
                "PARTIALLY_FILLED",
                "FILLED",
                "CANCELLED",
                "REJECTED",
            },
            "PARTIALLY_FILLED": {
                "PARTIALLY_FILLED",
                "FILLED",
                "CANCELLED",
                "REJECTED",
            },
            "FILLED": {"FILLED"},
            "CANCELLED": {"CANCELLED"},
            "REJECTED": {"REJECTED"},
        }

        if new_status not in transitions[current]:
            return False

        order["status"] = new_status

        self.execution_events.append({
            "type": "ORDER_STATUS",
            "order_id": order_id,
            "leg": order["leg"],
            "role": order["role"],
            "status": new_status,
        })

        return True

    def record_execution_event(
        self,
        order_id,
        event_id,
        fill_quantity,
        price=None,
    ):
        """Record a unique fill event against a registered order."""

        if order_id not in self.orders:
            return False

        if not isinstance(event_id, str) or not event_id.strip():
            return False

        if event_id in self.execution_event_ids:
            return False

        order = self.orders[order_id]

        if order["status"] in (
            "FILLED",
            "CANCELLED",
            "REJECTED",
        ):
            return False

        quantity = to_decimal(fill_quantity)

        if quantity is None or quantity <= 0:
            return False

        parsed_price = None

        if price is not None:
            parsed_price = to_decimal(price)

            if parsed_price is None or parsed_price <= 0:
                return False

        leg = order["leg"]

        if order["role"] == "ENTRY":
            accepted = self.record_entry_fill(leg, quantity)
        else:
            accepted = self.record_exit_fill(leg, quantity)

        if not accepted:
            return False

        order["filled_quantity"] += quantity

        target_quantity = (
            self.requested_quantity
            if order["role"] == "ENTRY"
            else self.filled_quantities[leg]
        )

        order["status"] = (
            "FILLED"
            if order["filled_quantity"] == target_quantity
            else "PARTIALLY_FILLED"
        )

        self.execution_event_ids.add(event_id)

        self.execution_events.append({
            "type": "EXECUTION",
            "event_id": event_id,
            "order_id": order_id,
            "leg": leg,
            "role": order["role"],
            "quantity": quantity,
            "price": parsed_price,
        })

        return True