"""Fitness terms that need only populations, plan and EPCI membership.

Geometry-based terms (Polsby-Popper compactness) and the audit metrics (neutrality)
are not here yet: compactness needs the polygon layer from ingest, and the audit
needs quarantined results. Those go in later modules, with the same pure-function style.
"""

from __future__ import annotations


def max_population_deviation(district_population: dict[int, int], target: float) -> float:
    """L_pop: max over districts of |Pop(D_j) - target| / target."""
    if not district_population:
        return 0.0
    return max(abs(p - target) / target for p in district_population.values())


def _valid_epci(value: str | None) -> str | None:
    """Treat absent/blank membership values as no EPCI, never as a shared EPCI."""
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized or normalized.lower() in {"nan", "none", "null"}:
        return None
    return normalized


def _districts_by_epci(plan: dict[str, int], epci_of: dict[str, str | None]) -> dict[str, set[int]]:
    districts_by_epci: dict[str, set[int]] = {}
    for unit, district in plan.items():
        epci = _valid_epci(epci_of.get(unit))
        if epci is not None:
            districts_by_epci.setdefault(epci, set()).add(district)
    return districts_by_epci


def epci_split_count(plan: dict[str, int], epci_of: dict[str, str | None]) -> tuple[int, int]:
    """Excess EPCI splits (D7): sum over EPCIs of (number of districts touching it - 1).

    Returns (raw excess_splits, represented_epci_count); the optimization
    normalization is handled by epci_split_term using the bounds below.
    """
    districts_by_epci = _districts_by_epci(plan, epci_of)
    excess = sum(len(ds) - 1 for ds in districts_by_epci.values())
    return excess, len(districts_by_epci)


def epci_missing_membership_count(plan: dict[str, int], epci_of: dict[str, str | None]) -> int:
    """Number of plan units without a valid EPCI membership."""
    return sum(1 for unit in plan if _valid_epci(epci_of.get(unit)) is None)


def epci_split_max_possible(plan: dict[str, int], epci_of: dict[str, str | None]) -> int:
    """Maximum excess splits possible with this plan's seats and units.

    An EPCI can touch at most one district per constituent unit and at most one
    per district in the plan. Therefore its maximum excess is
    ``min(unit_count, district_count) - 1``.
    """
    district_count = len(set(plan.values()))
    unit_count_by_epci: dict[str, int] = {}
    for unit in plan:
        epci = _valid_epci(epci_of.get(unit))
        if epci is not None:
            unit_count_by_epci[epci] = unit_count_by_epci.get(epci, 0) + 1
    return sum(max(0, min(unit_count, district_count) - 1)
               for unit_count in unit_count_by_epci.values())


def epci_split_lower_bound(plan: dict[str, int], epci_of: dict[str, str | None]) -> int:
    """Theoretical unavoidable excess splits given districts, units and EPCI coverage.

    Each valid EPCI can absorb one district without a split, and each unit with
    missing EPCI membership can potentially absorb one additional district.
    Any remaining districts imply at least one excess EPCI split each. The bound
    is capped by the maximum possible excess. It depends only on the unit set,
    membership coverage, and district count, so it is constant across plans with
    the same inputs.
    """
    district_count = len(set(plan.values()))
    districts_by_epci = _districts_by_epci(plan, epci_of)
    missing_units = epci_missing_membership_count(plan, epci_of)
    theoretical = max(0, district_count - missing_units - len(districts_by_epci))
    maximum = epci_split_max_possible(plan, epci_of)
    return min(theoretical, maximum)


def epci_split_term(plan: dict[str, int], epci_of: dict[str, str | None]) -> float:
    """Normalized avoidable excess EPCI splits, bounded to [0, 1].

    The numerator removes a theoretical lower bound: each valid EPCI and each
    unit lacking a valid membership can cover one district without a split. The
    remaining avoidable excess is divided by the remaining attainable maximum.
    Raw counts and bounds remain available through the companion functions.
    """
    excess, _ = epci_split_count(plan, epci_of)
    maximum = epci_split_max_possible(plan, epci_of)
    lower = epci_split_lower_bound(plan, epci_of)
    if excess < lower:
        raise ValueError(
            f"observed EPCI excess ({excess}) is below theoretical lower bound ({lower}); "
            "check partition completeness and EPCI membership"
        )
    denominator = maximum - lower
    return max(0.0, min(1.0, (excess - lower) / denominator)) if denominator else 0.0
