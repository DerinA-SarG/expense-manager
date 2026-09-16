"""Working out where money set aside for goals should land.

Two rules live here and nowhere else:

1. **A goal never holds more than its target.** Once it is full, the share it
   would have taken goes to the goals that still have room, split between them
   in proportion to the share of income each one claims. A goal that has filled
   up is not a reason for money to stop being saved.
2. **Nothing here writes anything.** Every function returns a plan. The page
   shows the plan, and the money only moves when someone presses the button.
   Goals are updated by a person, not by a side effect of logging a payslip.

Amounts are integer cents throughout, and a split always adds up to exactly
what went into it: whatever cannot be placed is returned as `unplaced` rather
than quietly rounded away. Money is being *moved* here, never recalculated.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Bucket:
    """One goal, as far as a split is concerned.

    `room` is what the goal can still take before it reaches its target, or
    None for a goal with no target at all -- nothing to overflow, so it absorbs
    whatever it is given.
    """

    id: int
    name: str
    pct: float
    room: int | None
    taken: int = 0

    @property
    def open(self) -> bool:
        return self.room is None or self.room > 0

    def take(self, cents: int) -> int:
        """Accept as much of `cents` as fits, and report how much that was."""
        if cents <= 0:
            return 0
        fits = cents if self.room is None else min(cents, self.room)
        if fits <= 0:
            return 0
        self.taken += fits
        if self.room is not None:
            self.room -= fits
        return fits


def buckets_from(goals, pct_override: dict[int, float] | None = None) -> list[Bucket]:
    """Turn goal rows into buckets.

    `pct_override` re-cuts an income entry at the rates it was originally split
    at rather than at whatever the goals claim today -- see `Database.
    allocate_income`. A goal named in it takes part even if it claims nothing
    now, which is the only way a correction to an old payslip can find the
    goals that payslip actually fed.
    """
    override = pct_override or {}
    buckets = []
    for goal in goals:
        target = int(goal["target_cents"])
        saved = int(goal["saved_cents"])
        buckets.append(
            Bucket(
                id=int(goal["id"]),
                name=goal["name"],
                pct=float(override.get(int(goal["id"]), goal["allocation_pct"] or 0)),
                # A goal already over its target has no room, not negative room.
                room=max(target - saved, 0) if target > 0 else None,
            )
        )
    return buckets


def share_out(amount: int, buckets: list[Bucket]) -> tuple[dict[int, int], int]:
    """Hand `amount` out between buckets in proportion to the share of income
    each claims, capped by room, re-sharing what will not fit.

    The percentages are scaled to hand out all of it rather than applied
    literally: this is money that already exists being placed somewhere, so
    cutting it at shares that add up to less than 100% would leave part of it
    with nowhere to go.

    Returns the cents each bucket took, and whatever could not be placed
    because every goal that takes a share is full.
    """
    placed: dict[int, int] = {}
    left = int(amount)
    if left <= 0:
        return placed, 0

    # Each pass fills some buckets to their target; what spilled is shared out
    # again among those that are still open. It terminates because every pass
    # either places money or finds nowhere left to place it.
    while left > 0:
        open_buckets = [b for b in buckets if b.open and b.pct > 0]
        total_pct = sum(b.pct for b in open_buckets)
        if total_pct <= 0:
            break

        exact = {b.id: left * b.pct / total_pct for b in open_buckets}
        cents = {key: int(value) for key, value in exact.items()}
        # Whole cents only, so the rounding loss goes out a cent at a time,
        # largest fraction first, and the split still adds up exactly.
        short = left - sum(cents.values())
        by_fraction = sorted(
            open_buckets, key=lambda b: exact[b.id] - cents[b.id], reverse=True
        )
        for bucket in by_fraction[:short]:
            cents[bucket.id] += 1

        moved = 0
        for bucket in open_buckets:
            took = bucket.take(cents[bucket.id])
            if took:
                placed[bucket.id] = placed.get(bucket.id, 0) + took
                moved += took
        if moved == 0:
            break
        left -= moved

    return placed, left


def split_income(amount: int, buckets: list[Bucket]) -> tuple[dict[int, int], int]:
    """Carve one income entry up between the goals that take a share of it.

    Each goal takes its own literal percentage -- 10% means 10% of what came in,
    not a tenth of the pot -- and what the goals do not claim between them is
    simply not set aside. Only the part a *full* goal cannot hold is shared out,
    and that part is shared out in full, because it is money that was already
    going to be saved.
    """
    placed: dict[int, int] = {}
    overflow = 0
    for bucket in buckets:
        if bucket.pct <= 0:
            continue
        share = round(int(amount) * bucket.pct / 100)
        if share <= 0:
            continue
        took = bucket.take(share)
        if took:
            placed[bucket.id] = placed.get(bucket.id, 0) + took
        overflow += share - took

    unplaced = 0
    if overflow > 0:
        spilled, unplaced = share_out(overflow, buckets)
        for goal_id, cents in spilled.items():
            placed[goal_id] = placed.get(goal_id, 0) + cents
    return placed, unplaced


def split_contribution(
    amount: int, goal_id: int, buckets: list[Bucket]
) -> tuple[dict[int, int], int]:
    """Money handed to one goal by name, capped the same way.

    The named goal fills up first -- it is the one being paid into, whether or
    not it takes a share of income -- and only what will not fit moves on.
    """
    placed: dict[int, int] = {}
    target = next((b for b in buckets if b.id == int(goal_id)), None)
    left = int(amount)
    if target is not None:
        took = target.take(left)
        if took:
            placed[target.id] = took
        left -= took

    if left > 0:
        spilled, left = share_out(left, [b for b in buckets if b.id != int(goal_id)])
        for gid, cents in spilled.items():
            placed[gid] = placed.get(gid, 0) + cents
    return placed, left
