"""Sample legal plans for one department (the unit of parallel work, see parallel.py).

Input: the department's units, populations, adjacency (already restricted to the department),
EPCI of each unit, seats, and a random generator. Output: plans with their metrics and a
validity check. Pure: no file I/O here.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field

from redistrict.graph.feasibility import department_feasible
from redistrict.metrics.population import epci_split_term
from redistrict.sample.recom import component_seats, flip_repair, grow_initial, max_deviation, recom_step
from redistrict.validate.constraints import check_contiguity


@dataclass
class SampledPlan:
    replicate: int
    chain_seed: int
    attempts_run: int
    steps_requested: int
    changed_steps: int
    unique_states_visited: int
    tolerance_schedule: str
    assignment: dict[str, int]
    max_deviation: float
    l_epci: float
    valid: bool
    notes: list[str] = field(default_factory=list)
    source: str = "sampled_recom"


def connected_pieces(units: list[str], adjacency: dict[str, frozenset[str]]) -> list[list[str]]:
    """Connected components of the department's graph, largest first."""
    members = set(units)
    seen: set[str] = set()
    out: list[list[str]] = []
    for start in sorted(units):
        if start in seen:
            continue
        comp = [start]
        seen.add(start)
        stack = [start]
        while stack:
            u = stack.pop()
            for v in adjacency.get(u, ()):
                if v in members and v not in seen:
                    seen.add(v)
                    comp.append(v)
                    stack.append(v)
        out.append(sorted(comp))
    return sorted(out, key=lambda c: (-len(c), c[0]))


def initial_plan(
    pieces: list[list[str]],
    adjacency: dict[str, frozenset[str]],
    pops: dict[str, int],
    target: float,
    tol: float,
    seats: int,
    rng: random.Random,
) -> dict[str, int]:
    piece_pops = [sum(pops[u] for u in p) for p in pieces]
    ks = component_seats(piece_pops, target, tol, seats)
    plan: dict[str, int] = {}
    label = 0
    for comp, k in zip(pieces, ks):
        plan.update(grow_initial(adjacency, comp, pops, k, target, tol, rng, first_label=label))
        label += k
    return plan


def sample_department(
    units: list[str],
    pops: dict[str, int],
    adjacency: dict[str, frozenset[str]],
    epci_of: dict[str, str],
    seats: int,
    tol: float,
    replicates: int,
    steps: int,
    seed: int,
    max_attempts: int = 5,
) -> dict:
    """Return a summary dict: feasibility, and `replicates` sampled plans with metrics."""
    total = sum(pops[u] for u in units)
    target = total / seats
    pieces = connected_pieces(units, adjacency)
    feasible, reason = department_feasible([sum(pops[u] for u in p) for p in pieces], target, tol, seats)
    if not feasible:
        return {"feasible": False, "reason": reason, "target": target, "plans": [],
                "sampling_status": "EXPLORATORY_CANDIDATES_NOT_A_VALIDATED_ENSEMBLE",
                "reference_use_allowed": False, "convergence_status": "NOT_ASSESSED",
                "sampling_method": "ReCom candidate generation with tolerance schedule and bounded restart selection",
                "chains_requested": replicates, "steps_per_attempt": steps, "chains": []}

    plans: list[SampledPlan] = []
    chain_diagnostics: list[dict] = []
    for r in range(replicates):
        # These restarts are for finding usable candidate plans, not independent draws from a
        # validated stationary distribution. Preserve the restart/selection details explicitly.
        best: SampledPlan | None = None
        attempts = 0
        attempts_diagnostics: list[dict] = []
        for attempt in range(max_attempts):
            attempts += 1
            chain_seed = seed * 100_000 + r * 1_000 + attempt
            rng = random.Random(chain_seed)
            plan = initial_plan(pieces, adjacency, pops, target, tol, seats, rng)
            plan = flip_repair(plan, adjacency, pops, target, tol)
            changed_steps = 0
            states = {frozenset(plan.items())}
            for i in range(steps):
                loose = 0.5
                t = max(tol, loose - (loose - tol) * i / max(1, int(0.7 * steps)))
                candidate = recom_step(plan, adjacency, pops, target, t, rng)
                if candidate != plan:
                    changed_steps += 1
                plan = candidate
                states.add(frozenset(plan.items()))
            contiguity_ok = not check_contiguity(plan, adjacency)
            dev = max_deviation(plan, pops, target)
            valid = contiguity_ok and dev <= tol + 1e-9
            attempts_diagnostics.append({
                "attempt": attempt + 1,
                "chain_seed": chain_seed,
                "steps_requested": steps,
                "changed_steps": changed_steps,
                "unique_states_visited": len(states),
                "final_valid": valid,
                "final_max_deviation": round(dev, 6),
            })
            cand = SampledPlan(
                replicate=r,
                chain_seed=chain_seed,
                attempts_run=attempts,
                steps_requested=steps,
                changed_steps=changed_steps,
                unique_states_visited=len(states),
                tolerance_schedule="0.50_to_hard_tolerance_over_first_70_percent",
                assignment=dict(sorted(plan.items())),
                max_deviation=round(dev, 6),
                l_epci=round(epci_split_term(plan, epci_of), 6),
                valid=valid,
                notes=[f"attempts={attempts}"],
            )
            if best is None or (valid and not best.valid) or (valid == best.valid and dev < best.max_deviation):
                best = cand
            if valid:
                break
        if not best.valid:
            best.notes.append(f"no valid plan after {max_attempts} attempts")
        best.attempts_run = attempts
        plans.append(best)
        chain_diagnostics.append({
            "replicate": r,
            "selection_rule": "first_valid_attempt_else_lowest_final_max_deviation",
            "attempts": attempts_diagnostics,
            "selected_attempt": attempts_diagnostics.index(next(
                (d for d in attempts_diagnostics if d["chain_seed"] == best.chain_seed),
                attempts_diagnostics[-1],
            )) + 1,
        })
    return {"feasible": True, "reason": "", "target": target,
            "sampling_status": "EXPLORATORY_CANDIDATES_NOT_A_VALIDATED_ENSEMBLE",
            "reference_use_allowed": False,
            "convergence_status": "NOT_ASSESSED",
            "sampling_method": "ReCom candidate generation with tolerance schedule and bounded restart selection",
            "chains_requested": replicates,
            "steps_per_attempt": steps,
            "chains": chain_diagnostics,
            "plans": [asdict(p) for p in plans]}
