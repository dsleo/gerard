"""Hard constraints for one department's plan (Module 2A, D5).

A plan is a mapping  unit_id -> district_id  for one department, where units are
communes or sub-commune pieces (arrondissements, IRIS). Adjacency is a mapping
unit_id -> set of neighbour unit_ids, restricted to this department.

These are pure functions. The optimizer, the sampler, the manual recalculator and
the compliance report all call this module, so there is exactly one definition
of "valid".
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Violation:
    rule: str  # partition | contiguity | population
    detail: str


@dataclass
class ValidationResult:
    violations: list[Violation] = field(default_factory=list)
    district_population: dict[int, int] = field(default_factory=dict)
    max_deviation: float = 0.0  # max |Pop(D_j) - target| / target

    @property
    def ok(self) -> bool:
        return not self.violations


def check_partition(plan: dict[str, int], units: set[str]) -> list[Violation]:
    """Every unit assigned exactly once, and no unknown units."""
    out: list[Violation] = []
    missing = units - plan.keys()
    extra = plan.keys() - units
    if missing:
        out.append(Violation("partition", f"unassigned units: {sorted(missing)[:5]}"))
    if extra:
        out.append(Violation("partition", f"unknown units: {sorted(extra)[:5]}"))
    return out


def check_contiguity(plan: dict[str, int], adjacency: dict[str, set[str]]) -> list[Violation]:
    """Each district induces a connected subgraph."""
    out: list[Violation] = []
    members: dict[int, set[str]] = {}
    for unit, district in plan.items():
        members.setdefault(district, set()).add(unit)
    for district, units in sorted(members.items()):
        start = min(units)
        seen = {start}
        queue = deque([start])
        while queue:
            u = queue.popleft()
            for v in adjacency.get(u, ()):
                if v in units and v not in seen:
                    seen.add(v)
                    queue.append(v)
        if seen != units:
            out.append(Violation("contiguity", f"district {district} has {len(units) - len(seen)} unreachable units"))
    return out


def check_population(
    plan: dict[str, int],
    population: dict[str, int],
    target: float,
    hard_tolerance: float,
) -> tuple[list[Violation], dict[int, int], float]:
    """Each district within +/- hard_tolerance of the target. Returns (violations, pops, max_dev)."""
    pops: dict[int, int] = {}
    for unit, district in plan.items():
        pops[district] = pops.get(district, 0) + population[unit]
    out: list[Violation] = []
    max_dev = 0.0
    for district, pop in sorted(pops.items()):
        dev = abs(pop - target) / target
        max_dev = max(max_dev, dev)
        if dev > hard_tolerance:
            out.append(Violation("population", f"district {district}: {dev:.2%} deviation exceeds {hard_tolerance:.0%}"))
    return out, pops, max_dev


def validate_plan(
    plan: dict[str, int],
    units: set[str],
    population: dict[str, int],
    adjacency: dict[str, set[str]],
    target: float,
    hard_tolerance: float,
) -> ValidationResult:
    """Run all hard checks for one department. Reports every violation, not just the first."""
    violations = check_partition(plan, units)
    if not violations:  # the remaining checks assume a valid partition
        violations += check_contiguity(plan, adjacency)
        pop_violations, pops, max_dev = check_population(plan, population, target, hard_tolerance)
        violations += pop_violations
        return ValidationResult(violations, pops, max_dev)
    return ValidationResult(violations)
