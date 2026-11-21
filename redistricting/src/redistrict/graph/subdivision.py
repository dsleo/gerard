"""Which units exceed the hard population ceiling, and what the current rule says about them (D4-r).

A unit is a candidate for splitting when its population is above
`subdivision_factor × P̄_d` (P̄_d = department population / seats). Under the current
rule only Paris, Lyon and Marseille may be split, and only into their arrondissements.
Anything else above the ceiling is reported as INFEASIBLE_UNDER_RULE, not hidden:
the decision on how to handle it is a human one (see O13).
"""

from __future__ import annotations

from dataclasses import dataclass

from redistrict.allocate.departments import department_of

SPLIT_BY_ARRONDISSEMENT = {"75", "69", "13"}  # Paris, Lyon, Marseille


@dataclass(frozen=True)
class Flag:
    unit: str
    dept: str
    population: int | None
    target: float
    ratio: float | None
    status: str  # OK | INFEASIBLE_UNDER_RULE | UNRESOLVED
    note: str


def target_population(dept_population: int, seats: int) -> float:
    if seats < 1:
        raise ValueError("a department needs at least one seat")
    return dept_population / seats


def classify_units(
    unit_population: dict[str, int | None],
    unit_is_arrondissement: set[str],
    dept_population: dict[str, int],
    seats: dict[str, int],
    subdivision_factor: float,
    unresolved: set[str],
) -> list[Flag]:
    """One flag per unit above the ceiling or unresolved. Units within the ceiling are not listed."""
    flags: list[Flag] = []
    for unit, pop in sorted(unit_population.items()):
        dept = department_of(unit)
        if unit in unresolved or pop is None:
            flags.append(Flag(unit, dept, pop, float("nan"), None, "UNRESOLVED",
                              "2021 population cannot be assigned to this unit (O12 or similar)"))
            continue
        target = target_population(dept_population[dept], seats[dept])
        ratio = pop / target
        if ratio <= subdivision_factor:
            continue
        if unit in unit_is_arrondissement:
            note = "arrondissement above ceiling; splitting below arrondissement is not allowed by the current rule"
        elif dept in SPLIT_BY_ARRONDISSEMENT:
            note = "commune above ceiling in a city split only by arrondissement; needs a decision"
        else:
            note = "commune above ceiling; sub-commune split not allowed by the current rule (decision needed)"
        flags.append(Flag(unit, dept, pop, target, ratio, "INFEASIBLE_UNDER_RULE", note))
    return flags
