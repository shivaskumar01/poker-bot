"""Self-play harness — validate the brain on full hands and measure bb/100.

Uses pokerkit as the dealer/rules engine (betting rounds, all-ins, side pots, showdown —
all correct and tested) and plugs our `decide()` in as the agent for every seat. Each hand
starts from equal stacks (chip-EV style) so we can run thousands of hands without bust/rebuy
bookkeeping; the button rotates each hand for fairness. Every action is fed to the stats
accumulator so the bot also exercises the learning path.
"""
from __future__ import annotations

import random
from decimal import Decimal

import pokerkit as pk
from pokerkit import Automation, NoLimitTexasHoldem

from ..io.log_parser import ParsedAction, ParsedHand
from ..model.cards import Card
from ..model.state import (
    Action,
    ActionType,
    GameState,
    Seat,
    SeatStatus,
    Street,
    TableConfig,
)
from ..opponents.tracking import accumulate
from ..strategy.decision import Decision
from ..strategy.engine import decide

_AUTOMATIONS = (
    Automation.ANTE_POSTING, Automation.BET_COLLECTION, Automation.BLIND_OR_STRADDLE_POSTING,
    Automation.CARD_BURNING, Automation.HOLE_DEALING, Automation.BOARD_DEALING,
    Automation.RUNOUT_COUNT_SELECTION, Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
    Automation.HAND_KILLING, Automation.CHIPS_PUSHING, Automation.CHIPS_PULLING,
)
_KIND_TO_ACTION = {
    "raise": ActionType.RAISE, "bet": ActionType.BET, "call": ActionType.CALL,
    "check": ActionType.CHECK, "fold": ActionType.FOLD,
}
_STREETS = ["preflop", "flop", "turn", "river", "river"]


def _to_card(c) -> Card:
    s = str(c)                       # pokerkit str is verbose, e.g. 'TEN OF HEARTS (Th)'
    if "(" in s and ")" in s:
        s = s[s.rfind("(") + 1:s.rfind(")")]
    return Card.parse(s)


# --- agents: callables (game_state, rng, iterations) -> Decision ---
def engine_agent(gs, rng, iterations):
    return decide(gs, rng, iterations)


def station_agent(gs, rng, iterations):
    """Calling station: never folds, never raises — calls any bet, else checks."""
    if gs.to_call > 0:
        return Decision(ActionType.CALL, gs.to_call, "station calls")
    return Decision(ActionType.CHECK, Decimal("0"), "station checks")


def _board(state) -> list[Card]:
    out: list[Card] = []
    for c in state.board_cards:
        if isinstance(c, (list, tuple)):
            out.extend(_to_card(x) for x in c)
        else:
            out.append(_to_card(c))
    return out


def _build_gamestate(state, button_index, sb, bb, start_stacks, records, folded) -> GameState:
    actor = state.actor_index
    n = len(state.stacks)
    bets = list(state.bets)
    stacks = list(state.stacks)
    hero_hole = tuple(_to_card(c) for c in state.hole_cards[actor])

    seats = []
    for p in range(n):
        if p in folded:
            status = SeatStatus.FOLDED
        elif stacks[p] == 0:
            status = SeatStatus.ALL_IN
        else:
            status = SeatStatus.ACTIVE
        seats.append(Seat(
            seat_id=p, name=f"P{p}", stack=Decimal(stacks[p]),
            committed=Decimal(bets[p]),
            status=status, cards=hero_hole if p == actor else (),
            is_button=(p == button_index), is_hero=(p == actor),
        ))

    street_idx = state.street_index if state.street_index is not None else 0
    max_bet = max(bets) if bets else 0
    min_to = state.min_completion_betting_or_raising_to_amount or (max_bet + bb)
    actions = tuple(
        Action(seat_id=r[0], action=_KIND_TO_ACTION[r[2]], amount=Decimal(r[3]),
               street=Street(["preflop", "flop", "turn", "river"].index(r[4])))
        for r in records if r[2] in _KIND_TO_ACTION
    )
    return GameState(
        config=TableConfig(small_blind=Decimal(sb), big_blind=Decimal(bb), max_seats=n),
        seats=tuple(seats), board=tuple(_board(state)), street=Street(min(street_idx, 3)),
        button_seat_id=button_index, hero_seat_id=actor,
        pot=Decimal(sum(start_stacks) - sum(stacks)),
        to_call=Decimal(state.checking_or_calling_amount),
        min_raise=Decimal(max(min_to - max_bet, bb)), actions=actions,
    )


def play_hand(start_stacks, button_index, rng, sb=1, bb=2, iterations=800, agents=None):
    """Play one hand from equal-ish start stacks; return (deltas, records, board).

    `agents` is a per-seat list of callables (gs, rng, iterations) -> Decision; defaults to
    the full engine at every seat.
    """
    if agents is None:
        agents = [engine_agent] * len(start_stacks)
    state = NoLimitTexasHoldem.create_state(
        _AUTOMATIONS, True, 0, (sb, bb), bb, tuple(start_stacks), len(start_stacks),
    )
    records = []          # (idx, name, kind, amount, street_str, all_in)
    folded: set[int] = set()

    while state.status and state.actor_index is not None:
        actor = state.actor_index
        street = _STREETS[min(state.street_index or 0, 4)]
        to_call = state.checking_or_calling_amount
        prior_max = max(state.bets) if state.bets else 0
        gs = _build_gamestate(state, button_index, sb, bb, start_stacks, records, folded)
        d = agents[actor](gs, rng, iterations)

        if d.action == ActionType.FOLD and state.can_fold():
            state.fold()
            folded.add(actor)
            records.append((actor, f"P{actor}", "fold", 0, street, False))
        elif d.action in (ActionType.CHECK, ActionType.CALL) or d.action == ActionType.FOLD:
            allin = to_call >= state.stacks[actor]
            state.check_or_call()
            records.append((actor, f"P{actor}", "check" if to_call == 0 else "call",
                            int(to_call), street, allin))
        else:  # BET / RAISE
            hi = state.stacks[actor] + state.bets[actor]
            lo = state.min_completion_betting_or_raising_to_amount or hi
            amt = min(max(int(round(float(d.amount))), lo), hi)
            if state.can_complete_bet_or_raise_to(amt):
                kind = "raise" if (state.street_index == 0 or prior_max > 0) else "bet"
                state.complete_bet_or_raise_to(amt)
                records.append((actor, f"P{actor}", kind, amt, street, amt >= hi))
            else:
                allin = to_call >= state.stacks[actor]
                state.check_or_call()
                records.append((actor, f"P{actor}", "check" if to_call == 0 else "call",
                                int(to_call), street, allin))

    final = list(state.stacks)
    deltas = [final[i] - start_stacks[i] for i in range(len(start_stacks))]
    return deltas, records, _board(state)


def run(num_hands=500, players=6, start=200, sb=1, bb=2, seed=0, iterations=800,
        learn=True, agents_by_stable=None):
    """Run a self-play session; return per-player net chips, bb/100, and learned stats.

    `agents_by_stable` optionally assigns an agent to each stable player (index 0..players-1);
    seats rotate each hand so a fixed stable player sees every position.
    """
    rng = random.Random(seed)
    net = [0] * players
    stats: dict = {}

    for h in range(num_hands):
        # rotate seats so the button moves: pokerkit index i is stable player (i + h) % players
        agents = None
        if agents_by_stable is not None:
            agents = [agents_by_stable[(i + h) % players] for i in range(players)]
        deltas, records, board = play_hand([start] * players, players - 1 if players > 2 else 0,
                                            rng, sb, bb, iterations, agents=agents)
        for i in range(players):
            net[(i + h) % players] += deltas[i]
        if learn:
            stable = lambda i: f"P{(i + h) % players}"  # noqa: E731
            hand = ParsedHand(
                number=h,
                names={stable(i): stable(i) for i in range(players)},
                stacks={stable(i): Decimal(start) for i in range(players)},
                actions=[ParsedAction(stable(r[0]), stable(r[0]), r[2], Decimal(r[3]), r[4], r[5])
                         for r in records],
                board=board,
            )
            accumulate(stats, hand)

    bb100 = {f"P{i}": (net[i] / bb) / num_hands * 100 for i in range(players)}
    return {"net": net, "bb_per_100": bb100, "hands": num_hands, "stats": stats,
            "total_net": sum(net)}
