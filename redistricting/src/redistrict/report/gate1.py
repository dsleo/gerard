"""Gate 1 report: graph integrity and population flags, written as JSON and markdown.

Gate 1 does not pass on its own. It records what is connected, what is flagged, and what
blocks the next step. The next step (allocation sign-off, optimization) must read this report.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from redistrict.graph.subdivision import Flag


def gate1_summary(
    components_by_dept: dict[str, list[frozenset[str]]],
    flags: list[Flag],
    dept_population: dict[str, int],
    seats: dict[str, int],
    excluded_depts: list[str],
    forced_edges: list[tuple[str, str]],
    feasibility: dict[str, tuple[bool, str]],
    link_candidates: list[dict] | None = None,
) -> dict:
    infeasible = {d: reason for d, (ok, reason) in sorted(feasibility.items()) if not ok}
    disconnected = {
        d: [sorted(c) for c in comps[1:]] for d, comps in components_by_dept.items() if len(comps) > 1
    }
    counts: dict[str, int] = {}
    for f in flags:
        counts[f.status] = counts.get(f.status, 0) + 1
    link_candidates = link_candidates or []
    unapproved_links = [l for l in link_candidates if l.get("approval_status") != "approved"]
    has_disconnected = bool(disconnected)
    return {
        "departments": len(components_by_dept),
        "departments_excluded": excluded_depts,
        "forced_edges_applied": [list(e) for e in forced_edges],
        "link_candidates": link_candidates,
        "unapproved_link_count": len(unapproved_links),
        "contiguity_status": "UNRESOLVED" if has_disconnected or unapproved_links else "PASS",
        "disconnected_departments": disconnected,
        "infeasible_departments": infeasible,
        "flag_counts": counts,
        "flags": [asdict(f) for f in flags],
        "seats_sum": sum(seats.values()),
        "population_sum": sum(dept_population.values()),
        # A geometric heuristic is not evidence of a ferry, bridge, or legally acceptable
        # connection. A Gate 1 pass requires a connected physical/manual graph and no
        # unapproved inferred links in the generation graph.
        "passes": not infeasible and not disconnected and not unapproved_links
                  and not any(f.status != "OK" for f in flags),
    }


def write_gate1(summary: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "step1_graph_audit.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Gate 1: graph audit",
        "",
        f"- Departments checked: {summary['departments']} (excluded: {', '.join(summary['departments_excluded']) or 'none'})",
        f"- Seats sum: {summary['seats_sum']}",
        f"- Population sum: {summary['population_sum']:,}",
        f"- Explicit edges applied to the physical graph: {summary['forced_edges_applied']}",
        f"- Contiguity status: **{summary.get('contiguity_status', 'UNRESOLVED')}**",
        f"- Unapproved inferred-link candidates: {summary.get('unapproved_link_count', 0)}",
        f"- **Gate passes: {summary['passes']}**",
        "",
        "## Disconnected departments",
    ]
    if summary["disconnected_departments"]:
        for d, comps in summary["disconnected_departments"].items():
            lines.append(f"- {d}: {len(comps)} extra component(s), e.g. {comps[0][:5]}")
    else:
        lines.append("- none")
    if summary.get("link_candidates"):
        lines += ["", "## Link candidates (not treated as legal contiguity)", "",
                  "These links may be used only in exploratory planning until each is reviewed and approved with a source.", "",
                  "| unit A | unit B | department | gap (m) | kind | basis | status |",
                  "|---|---|---:|---:|---|---|---|"]
        for link in summary["link_candidates"]:
            lines.append(
                f"| {link['a']} | {link['b']} | {link['dept']} | {link['gap_m']} | "
                f"{link['kind']} | {link.get('basis', '')} | {link.get('approval_status', 'unapproved')} |"
            )
    lines += ["", "## Infeasible departments (component check)"]
    if summary["infeasible_departments"]:
        for d, reason in summary["infeasible_departments"].items():
            lines.append(f"- {d}: {reason}")
    else:
        lines.append("- none")
    lines += ["", "## Flags", "", f"Counts: {summary['flag_counts'] or 'none'}", ""]
    if summary["flags"]:
        lines += ["| unit | dept | population | target | ratio | status | note |", "|---|---|---|---|---|---|---|"]
        for f in summary["flags"]:
            ratio = "" if f["ratio"] is None else f"{f['ratio']:.2f}"
            target = "" if f["target"] != f["target"] else f"{f['target']:,.0f}"  # NaN check
            pop = "" if f["population"] is None else f"{f['population']:,}"
            lines.append(f"| {f['unit']} | {f['dept']} | {pop} | {target} | {ratio} | {f['status']} | {f['note']} |")
    (out_dir / "step1_graph_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
