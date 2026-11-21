"""Seat allocation across departments (Module 1, D8).

Highest averages with a configurable divisor:
    dhondt  : next seat goes to argmax  P_d / (k_d + 1)
    webster : next seat goes to argmax  P_d / (k_d + 0.5)

Every department starts at `min_seats` (constitutional floor), then seats are added
one at a time until the total is K. Ties are broken by department code, so the
result is deterministic.

Pure function: no I/O, no randomness.
"""

from __future__ import annotations

from fractions import Fraction

DIVISOR_OFFSET = {"dhondt": Fraction(1), "webster": Fraction(1, 2)}


def apportion(
    populations: dict[str, int],
    total_seats: int,
    method: str,
    min_seats: int = 1,
) -> dict[str, int]:
    """Return seats per department summing to `total_seats`."""
    if method not in DIVISOR_OFFSET:
        raise ValueError(f"unknown method: {method}")
    if min_seats < 1:
        raise ValueError("min_seats must be at least 1")
    n = len(populations)
    if total_seats < n * min_seats:
        raise ValueError(f"{total_seats} seats cannot give {min_seats} to each of {n} departments")
    if any(p <= 0 for p in populations.values()):
        raise ValueError("all populations must be positive")

    offset = DIVISOR_OFFSET[method]
    seats = {d: min_seats for d in populations}
    order = sorted(populations)  # ties go to the first code in this order
    for _ in range(total_seats - n * min_seats):
        best, best_quotient = order[0], None
        for d in order:
            quotient = Fraction(populations[d]) / (seats[d] + offset)
            if best_quotient is None or quotient > best_quotient:
                best, best_quotient = d, quotient
        seats[best] += 1
    return dict(sorted(seats.items()))


def apportion_with_fixed(
    populations: dict[str, int],
    total_seats: int,
    method: str,
    fixed_seats: dict[str, int],
    min_seats: int = 1,
) -> dict[str, int]:
    """Apportion the remaining seats while preserving specified department counts.

    Fixed departments are removed from the divisor competition. Every other
    department starts at ``min_seats`` and competes for the remaining allocation.
    This supports the D53 policy of carrying forward incumbent constituencies;
    callers must validate the fixed counts against the official map first.
    """
    if method not in DIVISOR_OFFSET:
        raise ValueError(f"unknown method: {method}")
    if min_seats < 1:
        raise ValueError("min_seats must be at least 1")
    if any(p <= 0 for p in populations.values()):
        raise ValueError("all populations must be positive")
    if not set(fixed_seats).issubset(populations):
        raise ValueError("fixed-seat departments must exist in populations")
    if any(not isinstance(k, int) or k < min_seats for k in fixed_seats.values()):
        raise ValueError("fixed seats must be integers at least min_seats")

    free = {d: p for d, p in populations.items() if d not in fixed_seats}
    remaining = total_seats - sum(fixed_seats.values())
    if remaining < len(free) * min_seats:
        raise ValueError("remaining seats cannot give min_seats to every non-fixed department")
    if not free and remaining != 0:
        raise ValueError("all departments are fixed but seats remain unallocated")

    result = dict(fixed_seats)
    if free:
        result.update(apportion(free, remaining, method=method, min_seats=min_seats))
    if sum(result.values()) != total_seats:
        raise AssertionError("fixed-seat apportionment did not conserve total seats")
    return dict(sorted(result.items()))
