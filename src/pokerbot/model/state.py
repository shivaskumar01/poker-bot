"""Canonical game-state snapshot — pure data, no browser dependency.

The scraper builds one `GameState` per decision point; the strategy engine consumes it.
All money is `Decimal` (never float). Derived values (positions, live opponents, pot odds)
are exposed as read-only properties so the snapshot stays the single source of truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, IntEnum

from .cards import Card
from .positions import assign_positions

ZERO = Decimal("0")


class Street(IntEnum):
    PREFLOP = 0
    FLOP = 1
    TURN = 2
    RIVER = 3
    SHOWDOWN = 4


class SeatStatus(Enum):
    EMPTY = "empty"
    SITTING_OUT = "sitting_out"
    AWAY = "away"
    ACTIVE = "active"
    FOLDED = "folded"
    ALL_IN = "all_in"


class ActionType(Enum):
    POST_SB = "post_sb"
    POST_BB = "post_bb"
    POST_ANTE = "post_ante"
    POST_STRADDLE = "post_straddle"
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"


# A seat is "in the hand" (still contesting the pot) when ACTIVE or ALL_IN.
IN_HAND = frozenset({SeatStatus.ACTIVE, SeatStatus.ALL_IN})
# A seat was "dealt in" (and so holds a fixed position for the hand) when not folded yet
# AND not sitting out — i.e. it received cards. Folding does NOT change your position.
DEALT = frozenset({SeatStatus.ACTIVE, SeatStatus.ALL_IN, SeatStatus.FOLDED})


@dataclass(frozen=True, slots=True)
class Seat:
    seat_id: int
    name: str | None
    stack: Decimal
    committed: Decimal = ZERO        # chips put in this street
    total_committed: Decimal = ZERO  # chips put in this hand
    status: SeatStatus = SeatStatus.EMPTY
    cards: tuple[Card, ...] = ()
    is_button: bool = False
    is_hero: bool = False

    @property
    def in_hand(self) -> bool:
        return self.status in IN_HAND

    @property
    def can_act(self) -> bool:
        return self.status is SeatStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class Action:
    seat_id: int
    action: ActionType
    amount: Decimal
    street: Street


@dataclass(frozen=True, slots=True)
class TableConfig:
    small_blind: Decimal
    big_blind: Decimal
    ante: Decimal = ZERO
    straddle: Decimal = ZERO
    max_seats: int = 9
    currency: str = "chips"
    run_it_twice: bool = False
    bomb_pot: bool = False
    game_type: str = "NLH"


@dataclass(frozen=True, slots=True)
class GameState:
    config: TableConfig
    seats: tuple[Seat, ...]
    board: tuple[Card, ...]
    street: Street
    button_seat_id: int
    hero_seat_id: int
    pot: Decimal                      # total already in the middle (prior streets + this one)
    to_call: Decimal                  # what hero must add to continue
    min_raise: Decimal                # minimum legal raise-to increment
    hand_id: str | None = None
    actions: tuple[Action, ...] = ()

    # --- lookups ---
    def seat(self, seat_id: int) -> Seat:
        for s in self.seats:
            if s.seat_id == seat_id:
                return s
        raise KeyError(f"no seat {seat_id}")

    @property
    def hero(self) -> Seat:
        return self.seat(self.hero_seat_id)

    @property
    def in_hand_seats(self) -> list[Seat]:
        return [s for s in self.seats if s.in_hand]

    @property
    def live_opponents(self) -> list[Seat]:
        return [s for s in self.in_hand_seats if s.seat_id != self.hero_seat_id]

    @property
    def num_live_opponents(self) -> int:
        return len(self.live_opponents)

    # --- position / strategy context ---
    @property
    def dealt_seats(self) -> list[Seat]:
        """Seats dealt into this hand (live or folded) — position is fixed at deal time."""
        return [s for s in self.seats if s.status in DEALT]

    @property
    def seats_clockwise_dealt(self) -> list[int]:
        """Dealt seat ids in clockwise order (ascending seat index)."""
        return sorted(s.seat_id for s in self.dealt_seats)

    @property
    def positions(self) -> dict[int, str]:
        """Map dealt seat id -> position label; stays fixed for the hand even after folds."""
        order = self.seats_clockwise_dealt
        if len(order) < 2 or self.button_seat_id not in order:
            return {}
        return assign_positions(order, self.button_seat_id)

    @property
    def hero_position(self) -> str | None:
        return self.positions.get(self.hero_seat_id)

    # --- money helpers ---
    @property
    def pot_after_call(self) -> Decimal:
        return self.pot + self.to_call

    @property
    def pot_odds(self) -> float:
        """Fraction of the post-call pot hero must contribute (0 if checking is free)."""
        denom = self.pot + self.to_call
        if self.to_call <= ZERO or denom <= ZERO:
            return 0.0
        return float(self.to_call / denom)

    def effective_stack(self, opponent_id: int) -> Decimal:
        """Smaller of hero's and the opponent's stack — the chips actually at risk."""
        return min(self.hero.stack, self.seat(opponent_id).stack)

    @property
    def spr(self) -> float:
        """Stack-to-pot ratio using hero's stack (0 pot -> inf)."""
        if self.pot <= ZERO:
            return float("inf")
        return float(self.hero.stack / self.pot)

    def big_blinds(self, amount: Decimal) -> float:
        bb = self.config.big_blind
        return float(amount / bb) if bb > ZERO else 0.0
