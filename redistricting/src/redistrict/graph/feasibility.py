"""Can a department be partitioned at all, given its connected components? (Gate 1)

Districts are connected within a department (D2). So every connected component of the
department's graph must be covered by whole districts of its own: a component cannot
share a district with another component. A component holding `pop` people can hold `k`
districts only if its population is within the hard tolerance of `k` targets:

    (1 - tol) * k * target  <=  pop  <=  (1 + tol) * k * target

The department is feasible only if every component has a valid `k`, and the components'
k values can add up to the department's seats.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SeatRange:
    k_min: int
    k_max: int  # k_min > k_max means the component cannot be covered by valid districts


def component_seat_range(pop: int, target: float, tol: float) -> SeatRange:
    if pop <= 0 or target <= 0:
        raise ValueError("population and target must be positive")
    k_min = max(1, math.ceil(pop / ((1 + tol) * target)))
    k_max = math.floor(pop / ((1 - tol) * target))
    return SeatRange(k_min, k_max)


def department_feasible(component_pops: list[int], target: float, tol: float, seats: int) -> tuple[bool, str]:
    """Return (feasible, reason). Reason is empty when feasible."""
    ranges = [component_seat_range(p, target, tol) for p in component_pops]
    for i, r in enumerate(ranges):
        if r.k_min > r.k_max:
            return False, (f"component {i} ({component_pops[i]:,} people) cannot be split into "
                           f"whole districts within ±{tol:.0%} of {target:,.0f}")
    lo = sum(r.k_min for r in ranges)
    hi = sum(r.k_max for r in ranges)
    if not lo <= seats <= hi:
        return False, f"{seats} seats outside feasible range [{lo}, {hi}] given the components"
    return True, ""
