"""Accumulate PlayerStats from parsed hands — this is how the bot *learns* reads.

Walks each hand's action sequence and attributes HUD opportunities/made-counts: VPIP, PFR,
3-bet & fold-to-3-bet (opener vs a re-raise), flop c-bet & fold-to-c-bet, postflop
aggression, and WTSD. Stats are keyed by player id. The same function consumes hands from
the PokerNow log parser, the live scraper, and the self-play harness.
"""
from __future__ import annotations

from .aliases import canonical
from .stats import PlayerStats

_STAT_FIELDS = ["vpip", "pfr", "threebet", "fold_to_3bet", "cbet_flop", "fold_to_cbet_flop", "wtsd"]


def _get(stats: dict[str, PlayerStats], pid: str, name: str) -> PlayerStats:
    ps = stats.get(pid)
    if ps is None:
        ps = PlayerStats(name=name or pid)
        stats[pid] = ps
    elif name:
        ps.name = name  # keep the most recent display name
    return ps


def merge_aliases(stats: dict[str, PlayerStats]) -> dict[str, PlayerStats]:
    """Combine id-keyed stats into one entry per CANONICAL name, so a person who sits under a
    different nickname/id (e.g. 'Hungry horse' = bizz) or capitalization keeps a single profile.
    Returns a dict keyed by canonical name. Use this once, just before persisting."""
    out: dict[str, PlayerStats] = {}
    for ps in stats.values():
        key = canonical(ps.name) or ps.name
        cur = out.get(key)
        if cur is None:
            ps.name = key
            out[key] = ps
            continue
        cur.hands += ps.hands
        cur.agg_actions += ps.agg_actions
        cur.call_actions += ps.call_actions
        for f in _STAT_FIELDS:
            d, s = getattr(cur, f), getattr(ps, f)
            d.made += s.made
            d.opp += s.opp
    return out


def accumulate(stats: dict[str, PlayerStats], hand) -> dict[str, PlayerStats]:
    # one name per pid (from the hand header + every action) so EVERY _get for a pid resolves to
    # the same canonical key — otherwise empty-name calls would split a player into an id-keyed stub
    names = dict(hand.names or {})
    for a in hand.actions:
        if a.pid and a.name:
            names.setdefault(a.pid, a.name)

    def g(pid):
        return _get(stats, pid, names.get(pid, ""))

    dealt = list(hand.stacks.keys()) or list({a.pid for a in hand.actions})
    for pid in dealt:
        g(pid).hands += 1

    # --- preflop: vpip / pfr / 3bet / fold-to-3bet ---
    pre = [a for a in hand.actions if a.street == "preflop"]
    raises = 0
    opener = None
    last_raiser = None
    vpip: set[str] = set()
    pfr: set[str] = set()
    folded_pre: set[str] = set()
    for a in pre:
        if a.kind in ("sb", "bb", "post"):
            continue
        if raises == 1 and a.pid != opener and a.kind in ("call", "raise", "fold"):
            g(a.pid).threebet.observe(a.kind == "raise")
        if a.pid == opener and raises >= 2 and a.kind in ("fold", "call", "raise"):
            g(a.pid).fold_to_3bet.observe(a.kind == "fold")
        if a.kind in ("call", "raise"):
            vpip.add(a.pid)
        if a.kind == "raise":
            pfr.add(a.pid)
            last_raiser = a.pid
            if raises == 0:
                opener = a.pid
            raises += 1
        elif a.kind == "fold":
            folded_pre.add(a.pid)
    for pid in dealt:
        ps = g(pid)
        ps.vpip.observe(pid in vpip)
        ps.pfr.observe(pid in pfr)

    # --- flop: c-bet by the last preflop raiser, and folds to it ---
    pf_aggressor = last_raiser
    saw_flop = set(dealt) - folded_pre
    flop = [a for a in hand.actions if a.street == "flop"]
    if pf_aggressor is not None and pf_aggressor in saw_flop and flop:
        first_aggr = next((a.pid for a in flop if a.kind in ("bet", "raise")), None)
        g(pf_aggressor).cbet_flop.observe(first_aggr == pf_aggressor)
        if first_aggr == pf_aggressor:
            idx = next(i for i, a in enumerate(flop)
                       if a.kind in ("bet", "raise") and a.pid == pf_aggressor)
            responded: set[str] = set()
            for a in flop[idx + 1:]:
                if a.pid != pf_aggressor and a.pid not in responded and a.kind in ("fold", "call", "raise"):
                    g(a.pid).fold_to_cbet_flop.observe(a.kind == "fold")
                    responded.add(a.pid)

    # --- postflop aggression factor ---
    for a in hand.actions:
        if a.street in ("flop", "turn", "river"):
            ps = g(a.pid)
            if a.kind in ("bet", "raise"):
                ps.agg_actions += 1
            elif a.kind == "call":
                ps.call_actions += 1

    # --- WTSD: of those who saw the flop, who reached showdown ---
    folded_all = {a.pid for a in hand.actions if a.kind == "fold"}
    reached_showdown = len(set(dealt) - folded_all) >= 2
    for pid in saw_flop:
        g(pid).wtsd.observe(reached_showdown and pid not in folded_all)

    return stats
