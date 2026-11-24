"""ReCom: random redistricting moves that keep every district contiguous and balanced.

Algorithm (DeFord, Duchin, Solomon 2019, adapted to this engine):
  1. Initial plan: grow k districts from seeds inside each connected component, always
     extending the smallest district, until all units are assigned. Components get their seats
     from the feasibility ranges (see graph/feasibility.py).
  2. ReCom step: pick two adjacent districts, merge them, draw a uniform random spanning tree
     of the merged subgraph, and cut one tree edge that splits the merged population into two
     parts, each within the hard tolerance of the target. Both parts are connected by
     construction (they are subtrees). If no balanced cut exists in the drawn tree, redraw.

Everything here is pure: the caller passes the graph, populations and a random generator.
"""

from __future__ import annotations

import math
import random
from collections import deque

from redistrict.graph.feasibility import component_seat_range


def component_seats(pops: list[int], target: float, tol: float, seats: int) -> list[int]:
    """Split the department's seats across its components, respecting each component's feasible range."""
    ranges = [component_seat_range(p, target, tol) for p in pops]
    if any(r.k_min > r.k_max for r in ranges):
        raise ValueError("a component cannot hold whole districts; check feasibility first")
    ks = [r.k_min for r in ranges]
    # give the remaining seats to the components with the largest population per seat
    while sum(ks) < seats:
        best = max(
            (i for i in range(len(ks)) if ks[i] < ranges[i].k_max),
            key=lambda i: pops[i] / ks[i],
            default=None,
        )
        if best is None:
            raise ValueError("seats cannot be placed within the component ranges")
        ks[best] += 1
    return ks


def grow_initial(
    adjacency: dict[str, frozenset[str]],
    units: list[str],
    pops: dict[str, int],
    k: int,
    target: float,
    tol: float,
    rng: random.Random,
    first_label: int,
    attempts: int = 2000,
) -> dict[str, int]:
    """Region growing inside one connected component. Returns unit -> district label.

    No district may exceed (1 + tol) * target while growing, so the start is never grossly
    unbalanced (a single overfull leftover district cannot be repaired by pairwise ReCom moves).
    If a unit cannot be placed, the growth restarts from new seeds. If every attempt fails, the
    last attempt is returned and the caller's validity check reports it.
    """
    if k == 1:
        return {u: first_label for u in units}
    cap = (1 + tol) * target
    best: dict[str, int] | None = None
    best_dev = float("inf")
    for _ in range(attempts):
        plan, _ok = _grow_once(adjacency, units, pops, k, cap, rng, first_label)
        if len(plan) != len(units):
            continue  # never accept a plan that leaves units unassigned
        dpop: dict[int, int] = {}
        for u, d in plan.items():
            dpop[d] = dpop.get(d, 0) + pops[u]
        dev = max(abs(p - target) / target for p in dpop.values())
        if dev < best_dev:
            best, best_dev = plan, dev
        if best_dev <= tol:
            break  # within the hard tolerance: good enough as a start
    return best  # type: ignore[return-value]


def _grow_once(
    adjacency: dict[str, frozenset[str]],
    units: list[str],
    pops: dict[str, int],
    k: int,
    cap: float,
    rng: random.Random,
    first_label: int,
) -> tuple[dict[str, int], bool]:
    seeds = rng.sample(units, k)
    plan: dict[str, int] = {}
    pop_of = [0] * k
    frontier: list[set[str]] = [set() for _ in range(k)]
    for i, s_ in enumerate(seeds):
        plan[s_] = first_label + i
        pop_of[i] = pops[s_]
        frontier[i] = {v for v in adjacency.get(s_, ()) if v in units and v not in plan}
    while len(plan) < len(units):
        progressed = False
        for i in sorted(range(k), key=lambda j: pop_of[j]):
            cands = sorted(v for v in frontier[i] if v not in plan and pop_of[i] + pops[v] <= cap)
            frontier[i] = {v for v in frontier[i] if v not in plan}
            if not cands:
                continue
            v = rng.choice(cands)
            plan[v] = first_label + i
            pop_of[i] += pops[v]
            frontier[i].discard(v)
            frontier[i] |= {w for w in adjacency.get(v, ()) if w in units and w not in plan}
            progressed = True
            break
        if not progressed:
            # every district is at the cap: attach the remaining units, one at a time, to the
            # smallest adjacent district. The component is connected, so this always finishes.
            while len(plan) < len(units):
                frontier_units = [u for u in units if u not in plan and any(w in plan for w in adjacency.get(u, ()))]
                if not frontier_units:
                    return plan, False
                u = min(frontier_units)
                nbr = [plan[w] for w in adjacency.get(u, ()) if w in plan]
                lab = min(nbr, key=lambda x: pop_of[x - first_label])
                plan[u] = lab
                pop_of[lab - first_label] += pops[u]
            return plan, False
    return plan, True


def _district_members(plan: dict[str, int]) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    for u, d in plan.items():
        out.setdefault(d, set()).add(u)
    return out


def _random_spanning_tree(nodes: set[str], adjacency: dict[str, frozenset[str]], rng: random.Random) -> dict[str, set[str]]:
    """Uniform-ish random spanning tree by randomised Kruskal over the induced subgraph."""
    edges = sorted({tuple(sorted((u, v))) for u in nodes for v in adjacency.get(u, ()) if v in nodes})
    rng.shuffle(edges)
    parent = {u: u for u in nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    tree: dict[str, set[str]] = {u: set() for u in nodes}
    for u, v in edges:
        ru, rv = find(u), find(v)
        if ru != rv:
            parent[ru] = rv
            tree[u].add(v)
            tree[v].add(u)
    return tree


def _subtree(tree: dict[str, set[str]], root: str, cut: tuple[str, str]) -> set[str]:
    """Nodes reachable from `root` without crossing the cut edge."""
    a, b = cut
    seen = {root}
    queue = deque([root])
    while queue:
        u = queue.popleft()
        for v in tree[u]:
            if {u, v} == {a, b}:
                continue
            if v not in seen:
                seen.add(v)
                queue.append(v)
    return seen


def recom_step(
    plan: dict[str, int],
    adjacency: dict[str, frozenset[str]],
    pops: dict[str, int],
    target: float,
    tol: float,
    rng: random.Random,
    max_tries: int = 300,
    preferred_pair: tuple[int, int] | None = None,
) -> dict[str, int]:
    """One ReCom move. Returns a new plan, or the same plan if no balanced cut was found."""
    members = _district_members(plan)
    # adjacent district pairs
    pairs = sorted({
        tuple(sorted((plan[u], plan[v])))
        for u in plan for v in adjacency.get(u, ()) if v in plan and plan[u] != plan[v]
    })
    if not pairs:
        return plan
    # bias toward pairs that contain a district outside the tolerance: those are the ones to repair
    dpop = {d: sum(pops[u] for u in m) for d, m in members.items()}
    bad = {d for d, p_ in dpop.items() if abs(p_ - target) / target > tol}
    repair = [pr for pr in pairs if pr[0] in bad or pr[1] in bad]
    if repair and rng.random() < 0.9:
        a, b = rng.choice(repair)
        max_tries = max(max_tries, 3000)  # repair moves: balanced cuts are rare, draw more trees
    elif preferred_pair is not None and tuple(sorted(preferred_pair)) in pairs:
        a, b = tuple(sorted(preferred_pair))
    else:
        a, b = rng.choice(pairs)
    merged = members[a] | members[b]
    lo = (1 - tol) * target
    hi = (1 + tol) * target
    total = sum(pops[u] for u in merged)
    for _ in range(max_tries):
        tree = _random_spanning_tree(merged, adjacency, rng)
        root = min(merged)
        parent, order = _root_tree(tree, root)
        # subtree population, one pass from the leaves up
        sub = {u: pops[u] for u in merged}
        for u in reversed(order):
            if u != root:
                sub[parent[u]] += sub[u]
        cuts = [v for v in order if v != root and lo <= sub[v] <= hi and lo <= total - sub[v] <= hi]
        if cuts:
            v = rng.choice(cuts)
            side = _descendants(tree, parent, v)
            other = merged - side
            new = dict(plan)
            for u in side:
                new[u] = a
            for u in other:
                new[u] = b
            return new
    return plan


def _root_tree(tree: dict[str, set[str]], root: str) -> tuple[dict[str, str], list[str]]:
    """Parent pointers and a BFS order of a tree, rooted at `root`."""
    parent: dict[str, str] = {root: root}
    order = [root]
    queue = deque([root])
    while queue:
        u = queue.popleft()
        for v in sorted(tree[u]):
            if v not in parent:
                parent[v] = u
                order.append(v)
                queue.append(v)
    return parent, order


def _descendants(tree: dict[str, set[str]], parent: dict[str, str], v: str) -> set[str]:
    """All nodes in the subtree below v (including v)."""
    out = {v}
    stack = [v]
    while stack:
        u = stack.pop()
        for w in tree[u]:
            if parent.get(w) == u and w not in out:
                out.add(w)
                stack.append(w)
    return out


def plan_population(plan: dict[str, int], pops: dict[str, int]) -> dict[int, int]:
    out: dict[int, int] = {}
    for u, d in plan.items():
        out[d] = out.get(d, 0) + pops[u]
    return out


def max_deviation(plan: dict[str, int], pops: dict[str, int], target: float) -> float:
    dp = plan_population(plan, pops)
    return max(abs(p - target) / target for p in dp.values())


def _stays_connected(units: set[str], adjacency: dict[str, frozenset[str]]) -> bool:
    if not units:
        return False
    start = next(iter(units))
    seen = {start}
    stack = [start]
    while stack:
        u = stack.pop()
        for v in adjacency.get(u, ()):
            if v in units and v not in seen:
                seen.add(v)
                stack.append(v)
    return len(seen) == len(units)


def flip_repair(
    plan: dict[str, int],
    adjacency: dict[str, frozenset[str]],
    pops: dict[str, int],
    target: float,
    tol: float,
    max_passes: int = 200,
) -> dict[str, int]:
    """Repair overfull districts by shifting units along a chain of neighbouring districts.

    For an overfull district, find the shortest chain of adjacent districts to an underfull one.
    Each hop moves one boundary unit to the next district in the chain, keeping the giver
    connected. The overfull district loses a unit and the underfull district gains one.
    This is the step ReCom lacks when all neighbours are overfull too.
    """
    plan = dict(plan)
    hi = (1 + tol) * target
    for _ in range(max_passes):
        dpop = plan_population(plan, pops)
        over = sorted((d for d, p_ in dpop.items() if p_ > hi), key=lambda d: -dpop[d])
        if not over:
            break
        moved = False
        for donor in over:
            if _shift_chain(plan, adjacency, pops, dpop, donor, target, hi):
                moved = True
                break
        if not moved:
            break
    return plan


def _shift_chain(plan, adjacency, pops, dpop, donor, target, hi) -> bool:
    """BFS over districts from donor to the nearest underfull one, then shift one unit along the chain."""
    members = _district_members(plan)
    # district adjacency
    dadj: dict[int, set[int]] = {}
    for u, d in plan.items():
        for v in adjacency.get(u, ()):
            e = plan.get(v)
            if e is not None and e != d:
                dadj.setdefault(d, set()).add(e)
    parent: dict[int, int | None] = {donor: None}
    queue = deque([donor])
    target_d = None
    while queue and target_d is None:
        d = queue.popleft()
        for e in sorted(dadj.get(d, ())):
            if e in parent:
                continue
            parent[e] = d
            if dpop[e] < target:
                target_d = e
                break
            queue.append(e)
    if target_d is None:
        return False
    # the chain, from donor to target
    chain = [target_d]
    while parent[chain[-1]] is not None:
        chain.append(parent[chain[-1]])
    chain.reverse()  # donor ... target
    # shift one unit along each hop, from the far end back, so each hop's giver stays connected
    for giver, receiver in zip(chain, chain[1:]):
        movable = None
        for u in sorted(members[giver]):
            if any(plan.get(v) == receiver for v in adjacency.get(u, ())) and _stays_connected(members[giver] - {u}, adjacency):
                movable = u
                break
        if movable is None:
            return False
        plan[movable] = receiver
        members[giver].discard(movable)
        members.setdefault(receiver, set()).add(movable)
        dpop[giver] -= pops[movable]
        dpop[receiver] += pops[movable]
    return True
