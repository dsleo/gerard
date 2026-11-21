"""Weighted-sum simulated annealing over ReCom moves (v1 optimizer, see roadmap v2 for NSGA-II).

Objective (lower is better):
    L = w_pop * L_pop + w_comp * L_comp + w_epci * L_epci
where
    L_pop  = max over districts of |Pop - target| / target
    L_comp = mean over districts of (1 - Polsby-Popper), Polsby-Popper = 4 pi Area / Perimeter^2
    L_epci = avoidable excess EPCI splits normalized to [0, 1] (metrics/population.py)

Moves are ReCom steps with the hard tolerance, so every visited plan is contiguous and balanced.
The best valid plan seen is returned. Compactness per district is cached by the district's member
set, so a move only recomputes the two districts it changed.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Callable
from dataclasses import dataclass

from shapely import coverage_is_valid, coverage_union_all, wkb
from shapely.ops import unary_union

from redistrict.metrics.population import (
    epci_split_count,
    epci_split_lower_bound,
    epci_split_max_possible,
    epci_split_term,
    epci_missing_membership_count,
)
from redistrict.sample.recom import max_deviation, plan_population, recom_step
from redistrict.validate.constraints import check_contiguity


def assignment_fingerprint(plan: dict[str, int]) -> str:
    """Hash an assignment with district labels normalized away."""
    districts: dict[int, list[str]] = {}
    for unit, district in plan.items():
        districts.setdefault(int(district), []).append(str(unit))
    canonical_groups = sorted(tuple(sorted(units)) for units in districts.values())
    canonical = json.dumps(canonical_groups, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Weights:
    pop: float = 0.50
    comp: float = 0.30
    epci: float = 0.20


def polsby_popper(geoms: list, known_coverage: bool = False) -> float:
    # District pieces usually form a polygon coverage. GEOS can union a valid
    # coverage much faster than a general overlay. Keep the general union (and
    # its repair step) for overlaps, invalid rings, or mismatched boundaries.
    # The validity check is essential: coverage_union_all is not safe for
    # overlapping polygons.
    if geoms and (known_coverage or coverage_is_valid(geoms)):
        shape = coverage_union_all(geoms)
    else:
        shape = unary_union(geoms).buffer(0)
    perim = shape.length
    if perim <= 0:
        return 0.0
    return 4 * math.pi * shape.area / (perim * perim)


class Scorer:
    """Scores plans. Holds the geometry (WKB, Lambert-93) and caches compactness per district."""

    def __init__(self, geometry_wkb: dict[str, bytes], pops: dict[str, int], target: float,
                 epci_of: dict[str, str], weights: Weights):
        self._geom = {u: wkb.loads(b) for u, b in geometry_wkb.items()}
        self._pops = pops
        self._target = target
        self._epci = epci_of
        self._w = weights
        self._pp_cache: dict[frozenset, float] = {}
        # A valid full department coverage guarantees every district subset is
        # also a valid coverage, avoiding repeated GEOS validity checks.
        self._geometry_is_coverage = coverage_is_valid(list(self._geom.values()))

    def _pp(self, members: frozenset) -> float:
        if members not in self._pp_cache:
            self._pp_cache[members] = polsby_popper(
                [self._geom[u] for u in members], known_coverage=self._geometry_is_coverage
            )
        return self._pp_cache[members]

    def components(self, plan: dict[str, int]) -> dict[str, float]:
        members: dict[int, set[str]] = {}
        for u, d in plan.items():
            members.setdefault(d, set()).add(u)
        l_pop = max_deviation(plan, self._pops, self._target)
        pp = [self._pp(frozenset(m)) for m in members.values()]
        l_comp = sum(1 - p for p in pp) / len(pp)
        l_epci = epci_split_term(plan, self._epci)
        epci_excess, epci_count = epci_split_count(plan, self._epci)
        epci_max = epci_split_max_possible(plan, self._epci)
        epci_lower = epci_split_lower_bound(plan, self._epci)
        epci_missing = epci_missing_membership_count(plan, self._epci)
        return {"l_pop": l_pop, "l_comp": l_comp, "l_epci": l_epci,
                "epci_excess_splits": epci_excess,
                "epci_unavoidable_excess_splits": epci_lower,
                "epci_max_possible_excess_splits": epci_max,
                "epci_count": epci_count,
                "epci_missing_membership_units": epci_missing,
                "L": self._w.pop * l_pop + self._w.comp * l_comp + self._w.epci * l_epci}


def anneal(
    plan: dict[str, int],
    adjacency: dict[str, frozenset[str]],
    scorer: Scorer,
    pops: dict[str, int],
    target: float,
    tol: float,
    steps: int,
    rng: random.Random,
    t0: float = 0.02,
    t1: float = 0.0005,
    steps_per_round: int = 100,
    patience_rounds: int = 3,
    min_rounds: int = 4,
    min_improvement: float = 1e-4,
    trace_callback: Callable[[dict], None] | None = None,
) -> tuple[dict[str, int], dict[str, float], int, dict]:
    """Anneal from `plan`, recording every proposal and stopping after stale rounds.

    The number of proposals is capped by `steps`. At each completed round boundary, the
    best-so-far objective is compared with the start of that round. After `min_rounds`,
    stop when `patience_rounds` consecutive rounds improve the best objective by less
    than `min_improvement`. Set patience_rounds=0 to disable early stopping.

    `trace_callback`, when provided, receives one metrics record per proposal attempt.
    The callback is responsible for persisting records efficiently (for example JSONL+gzip).
    Returns (best valid plan, its components, accepted moves, run diagnostics).
    """
    if steps < 0 or steps_per_round <= 0 or min_rounds < 1 or patience_rounds < 0:
        raise ValueError("steps must be non-negative, round size/minimum rounds positive, patience non-negative")
    if min_improvement < 0:
        raise ValueError("min_improvement must be non-negative")
    current = dict(plan)
    cur = scorer.components(current)
    best, best_c = dict(current), dict(cur)
    accepted = 0
    rounds: list[dict] = []
    stale_rounds = 0
    round_start_best = best_c["L"]
    patience_reference = best_c["L"]
    round_start_accepted = accepted
    round_number = 1
    stop_reason = "max_steps"
    if trace_callback is not None:
        trace_callback({
            "event": "run_start",
            "assignment": dict(sorted(current.items())),
            "assignment_hash": assignment_fingerprint(current),
            "metrics": cur,
        })
    for i in range(steps):
        temp = t0 * (t1 / t0) ** (i / max(1, steps - 1))  # geometric cooling
        before = current
        cand = recom_step(current, adjacency, pops, target, tol, rng)
        candidate_delta = {
            unit: int(district)
            for unit, district in sorted(cand.items())
            if before.get(unit) != district
        }
        candidate_c = None
        status = "no_op"
        if cand == current:
            pass
        else:
            new = scorer.components(cand)
            candidate_c = new
            delta = new["L"] - cur["L"]
            if delta <= 0 or rng.random() < math.exp(-delta / temp):
                current, cur = cand, new
                accepted += 1
                status = "accepted"
                if cur["L"] < best_c["L"] and max_deviation(current, pops, target) <= tol + 1e-9 \
                        and not check_contiguity(current, adjacency):
                    best, best_c = dict(current), dict(cur)
            else:
                status = "rejected"

        step_number = i + 1
        round_number = (i // steps_per_round) + 1
        if trace_callback is not None:
            trace_callback({
                "event": "proposal",
                "step": step_number,
                "round": round_number,
                "temperature": temp,
                "proposal_status": status,
                "candidate": candidate_c,
                "candidate_delta": candidate_delta,
                "current_before_hash": assignment_fingerprint(before),
                "candidate_hash": assignment_fingerprint(cand),
                "current_hash": assignment_fingerprint(current),
                "best_hash": assignment_fingerprint(best),
                "current": cur,
                "best": best_c,
            })

        at_round_end = step_number % steps_per_round == 0 or step_number == steps
        if at_round_end:
            improvement = round_start_best - best_c["L"]
            patience_improvement = patience_reference - best_c["L"]
            if (patience_improvement > 1e-15 if min_improvement == 0
                    else patience_improvement + 1e-15 >= min_improvement):
                stale_rounds = 0
                patience_reference = best_c["L"]
            else:
                stale_rounds += 1
            round_record = {
                "round": round_number,
                "first_step": ((round_number - 1) * steps_per_round) + 1,
                "last_step": step_number,
                "best_L_at_start": round_start_best,
                "best_L_at_end": best_c["L"],
                "best_improvement": max(0.0, improvement),
                "accepted_moves": accepted - round_start_accepted,
                "stale_rounds": stale_rounds,
            }
            if patience_rounds and round_number >= min_rounds and stale_rounds >= patience_rounds:
                stop_reason = "best_score_patience_reached"
                round_record["stopped_early"] = True
            rounds.append(round_record)
            if trace_callback is not None:
                trace_callback({
                    "event": "round_checkpoint",
                    **round_record,
                    "current": cur,
                    "best": best_c,
                    "current_assignment": dict(sorted(current.items())),
                    "best_assignment": dict(sorted(best.items())),
                    "current_hash": assignment_fingerprint(current),
                    "best_hash": assignment_fingerprint(best),
                })
            if round_record.get("stopped_early"):
                break
            round_start_best = best_c["L"]
            round_start_accepted = accepted

    proposals_completed = rounds[-1]["last_step"] if rounds else 0
    diagnostics = {
        "max_proposals": steps,
        "proposals_completed": proposals_completed,
        "steps_per_round": steps_per_round,
        "patience_rounds": patience_rounds,
        "min_rounds": min_rounds,
        "min_improvement": min_improvement,
        "rounds_completed": len(rounds),
        "early_stopped": stop_reason != "max_steps",
        "stop_reason": stop_reason,
        "round_log": rounds,
    }
    if trace_callback is not None:
        trace_callback({
            "event": "run_end",
            "accepted_moves": accepted,
            "diagnostics": diagnostics,
            "best": best_c,
            "best_assignment": dict(sorted(best.items())),
            "best_hash": assignment_fingerprint(best),
        })
    return best, best_c, accepted, diagnostics
