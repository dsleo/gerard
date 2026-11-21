"""Project seat-allocation policies grounded in the 2009 constituency ordinance."""

from __future__ import annotations

from redistrict.allocate.apportion import apportion, apportion_with_fixed

# Current official seats in the 12 departments carried forward under D53.
# Counts follow Table 1 (department totals) and Table 2 (constituency numbering)
# of Ordinance 2009-935, which define the boundaries still used in 2024.
D53_FIXED_SEATS: dict[str, int] = {
    "17": 5,
    "21": 5,
    "22": 5,
    "29": 8,
    "54": 6,
    "56": 6,
    "59": 21,
    "65": 2,
    "84": 5,
    "85": 5,
    "971": 4,
    "976": 2,
}
D53_FIXED_SEAT_TOTAL = 74
DEPARTMENTAL_SEAT_TOTAL = 558

if sum(D53_FIXED_SEATS.values()) != D53_FIXED_SEAT_TOTAL:
    raise RuntimeError("D53 fixed department seat counts must sum to 74")


def project_dhondt_allocation(populations: dict[str, int], total_seats: int) -> dict[str, int]:
    """Apply D53 at the 558-seat project size; use ordinary D'Hondt otherwise."""
    if total_seats == DEPARTMENTAL_SEAT_TOTAL:
        return apportion_with_fixed(
            populations,
            total_seats,
            "dhondt",
            fixed_seats=D53_FIXED_SEATS,
            min_seats=1,
        )
    return apportion(populations, total_seats, "dhondt", min_seats=1)
