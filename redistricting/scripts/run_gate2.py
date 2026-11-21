"""Build a reproducible seat-allocation comparison (Gate 2 arithmetic report).

The report allocates departmental seats to all 101 modeled departments. The 19
COM and French-abroad seats are outside the departmental allocation (D3).
Run from redistricting/: .venv/bin/python scripts/run_blind.py run_gate2.py
"""

from __future__ import annotations

import csv
import pickle
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from redistrict.allocate.apportion import apportion
from redistrict.allocate.policy import D53_FIXED_SEATS, DEPARTMENTAL_SEAT_TOTAL, project_dhondt_allocation
from redistrict.ingest.generation import install_generation_guard

ROOT = Path(__file__).resolve().parents[1]
install_generation_guard(ROOT, "run_gate2.py")
STATE = ROOT / "data/processed/gate1/sampler_state.pkl"
OUT = ROOT / "data/processed/gate2"
TOTAL_NATIONAL = (577, 400)
OVERSEAS_FIXED = 19


def main() -> None:
    with open(STATE, "rb") as fh:
        state = pickle.load(fh)
    populations = {str(d): int(p) for d, p in state["dept_pop"].items()}
    if "976" not in populations:
        raise ValueError("Gate 1 state must include Mayotte's official 2017 population")
    n = len(populations)
    scenarios = []
    for total in TOTAL_NATIONAL:
        proportional = round(OVERSEAS_FIXED * total / 577)
        for mode, overseas in (("fixed", OVERSEAS_FIXED), ("proportional", proportional)):
            departmental_all = total - overseas
            if departmental_all < n:
                raise ValueError(f"scenario {total}/{mode} cannot give one seat to each of {n} departments")
            scenarios.append((total, mode, overseas, departmental_all))

    rows = []
    report = [
        "# Gate 2: seat allocation comparison",
        "",
        "Arithmetic comparison only. D’Hondt/Webster results are proposals, not legal allocations or approvals.",
        "All 101 modeled departments, including Mayotte, receive divisor allocations. Mayotte (976) uses its latest official commune population (INSEE reference 2017). The 19 COM and French-abroad seats remain outside the departmental allocation.",
        "",
        "| National seats | Overseas mode | Overseas/abroad | Departmental seats | D’Hondt sum | Webster sum | Different departments | D’Hondt Mayotte | Webster Mayotte | D’Hondt allocation | Check |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for total, mode, overseas, departmental_all in scenarios:
        d53 = total == 577 and mode == "fixed"
        dh = project_dhondt_allocation(populations, departmental_all) if d53 else apportion(
            populations, departmental_all, "dhondt", min_seats=1
        )
        web = apportion(populations, departmental_all, "webster", min_seats=1)
        differences = sum(dh[d] != web[d] for d in populations)
        ok = (sum(dh.values()) == departmental_all and sum(web.values()) == departmental_all
              and min(dh.values()) >= 1 and min(web.values()) >= 1)
        policy = "D53 fixed 12" if d53 else "Standard"
        report.append(
            f"| {total} | {mode} | {overseas} | {departmental_all} | "
            f"{sum(dh.values())} | {sum(web.values())} | {differences} | {dh['976']} | {web['976']} | {policy} | {'PASS' if ok else 'FAIL'} |"
        )
        for dept, population in populations.items():
            rows.append({
                "national_seats": total,
                "overseas_mode": mode,
                "overseas_abroad_seats": overseas,
                "departmental_seats_including_mayotte": departmental_all,
                "divisor_allocated_seats": departmental_all,
                "department": dept,
                "population": population,
                "population_reference_year": 2017 if dept == "976" else 2021,
                "dhondt_seats": dh[dept],
                "dhondt_policy": "D53_FIXED_12" if d53 else "STANDARD_DHONDT",
                "webster_seats": web[dept],
                "difference_webster_minus_dhondt": web[dept] - dh[dept],
                "target_dhondt": round(population / dh[dept], 3),
                "target_webster": round(population / web[dept], 3),
            })
        if not ok:
            raise RuntimeError(f"seat-sum or minimum-seat check failed for {total}/{mode}")

    report += [
        "",
        f"For the 577-seat / fixed-overseas scenario, D53 preserves {sum(D53_FIXED_SEATS.values())} seats in the 12 carry-forward departments and apportions the other {DEPARTMENTAL_SEAT_TOTAL - sum(D53_FIXED_SEATS.values())} departmental seats across the remaining 89 with D’Hondt. This allocates seats only; it does not certify unit assignments or district geometry.",
        "",
        f"Modeled scope: {n} departments; 100 use INSEE 2021 population and Mayotte uses INSEE 2017 population ({sum(populations.values()):,} residents total).",
        "PASS means only that the deterministic allocation sums to the modeled seat count and respects the one-seat floor.",
        f"The standard 577-seat D’Hondt comparison assigns {apportion(populations, scenarios[0][3], 'dhondt')['976']} seats to Mayotte; the D53 scenario preserves its two official seats.",
        "Gate 2 is not an approval of the allocation policy. Upstream Gate 1 and legal review remain separate blockers.",
        "",
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "seat_allocation_comparison.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "gate2_report.md").write_text("\n".join(report), encoding="utf-8")
    print(f"wrote {OUT}; scenarios={len(scenarios)}; modeled_departments={n}")


if __name__ == "__main__":
    main()
