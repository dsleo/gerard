"""Reallocate 2024 first-round legislative votes to the exploratory proposed map.

This is an audit-only sensitivity routine. It reads the quarantined Ministry
polling-station results and the estimated data.gouv.fr bureau-to-IRIS weights.
It does not model candidate filing, withdrawals, turnout changes, vote transfers,
or second-round winners.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from redistrict.sources import SOURCES  # noqa: E402

ELECTORAL = ROOT / "data/quarantine/electoral"
CROSSWALK = ELECTORAL / "liaison_iris_bureaux_de_vote_2024.csv"
RESULTS = ELECTORAL / "legislatives_2024_t1_bureaux.csv"
CURRENT_MAP_RESULTS = ELECTORAL / "legislatives_2024_t1_circonscriptions.csv"
OPTIMIZED = ROOT / "data/processed/optimized"
BLOCS = ROOT.parent / "docs/redistricting/blocs.draft.yaml"
OUT = ELECTORAL / "derived"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def department(value: object) -> str:
    value = str(value or "").strip().upper()
    return value.zfill(2) if value.isdigit() and len(value) < 3 else value


def count_series(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values.fillna("").astype(str).str.replace(" ", "", regex=False), errors="coerce").fillna(0)


def normalized_bureau_key(commune: pd.Series, bureau: pd.Series) -> pd.Series:
    """The published crosswalk key is COG commune code + four-digit bureau code."""
    return commune.fillna("").astype(str).str.zfill(5) + bureau.fillna("").astype(str).str.zfill(4)


def load_assignments() -> dict[str, dict[str, int]]:
    assignments: dict[str, dict[str, int]] = {}
    for path in OPTIMIZED.glob("*.json"):
        result = json.loads(path.read_text(encoding="utf-8"))
        assignments[str(result["dept"])] = {str(u): int(d) for u, d in result["assignment"].items()}
    if len(assignments) != 101:
        raise ValueError(f"expected optimized assignments for 101 departments, found {len(assignments)}")
    return assignments


def map_iris_to_district(iris: str, dept: str, assignments: dict[str, dict[str, int]]) -> int | None:
    units = assignments.get(dept, {})
    if iris in units:
        return units[iris]
    parent = iris[:5]
    return units.get(parent)


def main() -> None:
    source = SOURCES["liaison_iris_bureaux_2024"]
    result_source = SOURCES["results_leg_2024_t1_polling_stations"]
    current_map_source = SOURCES["results_leg_2024_t1_constituencies"]
    crosswalk_hash = digest(CROSSWALK)
    results_hash = digest(RESULTS)
    current_map_hash = digest(CURRENT_MAP_RESULTS)
    if source.sha256 and crosswalk_hash != source.sha256:
        raise ValueError("crosswalk checksum does not match src/redistrict/sources.py")
    if result_source.sha256 and results_hash != result_source.sha256:
        raise ValueError("quarantined Ministry result checksum does not match the source registry")
    if current_map_source.sha256 and current_map_hash != current_map_source.sha256:
        raise ValueError("quarantined constituency result checksum does not match the source registry")

    # Exact 2024 first-round constituency totals provide a same-territory
    # baseline for a descriptive bloc-plurality seat comparison. The new-map
    # side below remains a population-weighted estimate, not an actual result.
    current_map = pd.read_csv(CURRENT_MAP_RESULTS, sep=";", dtype=str, encoding="utf-8-sig")
    current_map["dept"] = current_map["Code département"].map(department)
    current_map = current_map[current_map["dept"].str.match(r"^(?:0[1-9]|[1-8][0-9]|9[0-5]|2A|2B)$")].copy()
    current_map_slots = sorted({
        int(match.group(1)) for column in current_map.columns
        if (match := re.fullmatch(r"Nuance candidat (\d+)", column))
    })
    current_map_district_count = int(current_map[["dept", "Code circonscription législative"]].drop_duplicates().shape[0])

    crosswalk = pd.read_csv(CROSSWALK, dtype={"iris": str, "bureau": str})
    crosswalk["weight"] = pd.to_numeric(crosswalk["poids_dans_bureau"], errors="raise")
    weight_sums = crosswalk.groupby("bureau")["weight"].sum()
    if not ((weight_sums - 1).abs() <= 1e-8).all():
        raise ValueError("poids_dans_bureau must sum to 1 for each crosswalk bureau")

    results = pd.read_csv(RESULTS, sep=";", dtype=str, encoding="utf-8-sig")
    required = {"Code département", "Code commune", "Code BV", "Inscrits", "Exprimés"}
    if not required.issubset(results.columns):
        raise ValueError(f"Ministry file is missing required columns: {sorted(required - set(results.columns))}")
    results["dept"] = results["Code département"].map(department)
    results["bureau"] = normalized_bureau_key(results["Code commune"], results["Code BV"])
    # Some Ministry rows use a shared placeholder key (e.g. bureau 0 in
    # Montbéliard) for multiple distinct voting sections. They must not be
    # fuzzy-matched or multiplied through a crosswalk join. Keep them in the
    # denominator, but allow duplicate keys only when the key has no crosswalk
    # entry; a duplicated key that could be joined is ambiguous and fails closed.
    crosswalk_bureau_ids = set(pd.read_csv(CROSSWALK, usecols=["bureau"], dtype={"bureau": str})["bureau"])
    duplicate_mask = results["bureau"].duplicated(keep=False)
    ambiguous_duplicates = set(results.loc[duplicate_mask, "bureau"]) & crosswalk_bureau_ids
    if ambiguous_duplicates:
        raise ValueError(f"duplicate Ministry bureau keys are present in the crosswalk: {sorted(ambiguous_duplicates)[:10]}")
    results["registered"] = count_series(results["Inscrits"])
    results["expressed"] = count_series(results["Exprimés"])

    assignments = load_assignments()
    crosswalk["iris"] = crosswalk["iris"].astype(str)
    crosswalk["bureau"] = crosswalk["bureau"].astype(str)
    crosswalk["dept"] = crosswalk["iris"].map(lambda x: department(x[:2]) if x[:2].isdigit() else x[:2])
    # IRIS overseas codes include 3-digit department prefixes, while metropolitan
    # and Corsican codes use two characters.
    crosswalk.loc[crosswalk["iris"].str.startswith(("971", "972", "973", "974", "976")), "dept"] = crosswalk["iris"].str[:3]
    crosswalk["district0"] = [map_iris_to_district(i, d, assignments) for i, d in zip(crosswalk["iris"], crosswalk["dept"])]

    all_bureau_ids = set(crosswalk["bureau"])
    results["matched_crosswalk"] = results["bureau"].isin(all_bureau_ids)
    result_totals = results.groupby("dept", as_index=False).agg(
        result_bureaus=("bureau", "count"), total_registered=("registered", "sum"), total_expressed=("expressed", "sum")
    )
    matched = results[results["matched_crosswalk"]].copy()
    matched_totals = matched.groupby("dept", as_index=False).agg(
        matched_bureaus=("bureau", "count"), matched_registered=("registered", "sum"), matched_expressed=("expressed", "sum")
    )

    # Join matched station results to estimated IRIS shares, then collapse the
    # shares to the optimized districts. No fuzzy ID repair is attempted.
    links = matched[["bureau", "dept"]].merge(
        crosswalk[["bureau", "iris", "dept", "district0", "weight"]],
        on="bureau", how="left", suffixes=("_result", "_iris"), validate="one_to_many",
    )
    links = links[links["district0"].notna()].copy()
    links["dept"] = links["dept_result"]
    links["district"] = links["district0"].astype(int) + 1
    district_weights = links.groupby(["bureau", "dept", "district"], as_index=False)["weight"].sum()
    weights_per_bureau = district_weights.groupby(["bureau", "dept"])["weight"].sum()
    if (weights_per_bureau > 1 + 1e-8).any():
        raise ValueError("assigned IRIS weights exceed 1 for at least one bureau")

    allocated = matched[["bureau", "dept", "registered", "expressed"]].merge(
        district_weights, on=["bureau", "dept"], how="inner", validate="one_to_many"
    )
    allocated["estimated_registered"] = allocated["registered"] * allocated["weight"]
    allocated["estimated_expressed"] = allocated["expressed"] * allocated["weight"]
    district_totals = allocated.groupby(["dept", "district"], as_index=False).agg(
        estimated_registered=("estimated_registered", "sum"),
        estimated_expressed=("estimated_expressed", "sum"),
    )
    allocated_department = allocated.groupby("dept", as_index=False).agg(
        assigned_registered=("estimated_registered", "sum"), assigned_expressed=("estimated_expressed", "sum")
    )
    coverage = result_totals.merge(matched_totals, on="dept", how="left").merge(
        allocated_department, on="dept", how="left"
    ).fillna(0)
    coverage["crosswalk_registered_coverage"] = coverage["matched_registered"] / coverage["total_registered"].replace(0, pd.NA)
    coverage["mapped_plan_registered_coverage"] = coverage["assigned_registered"] / coverage["total_registered"].replace(0, pd.NA)
    coverage = coverage.fillna(0)

    # Candidate votes are allocated by the published bureau-level share, then
    # collapsed to nuance and the two documented draft bloc mappings.
    candidate_slots = sorted({
        int(match.group(1)) for column in results.columns
        if (match := re.fullmatch(r"Nuance candidat (\d+)", column))
    })
    nuance_parts = []
    for slot in candidate_slots:
        nuance_col, votes_col = f"Nuance candidat {slot}", f"Voix {slot}"
        if votes_col not in results.columns:
            continue
        part = results[["bureau", "dept", nuance_col, votes_col]].copy()
        part["votes"] = count_series(part[votes_col])
        part["nuance"] = part[nuance_col].fillna("").astype(str).str.strip()
        part = part[part["nuance"].ne("") & part["votes"].gt(0)]
        if part.empty:
            continue
        part = part[["bureau", "dept", "nuance", "votes"]].merge(
            district_weights, on=["bureau", "dept"], how="inner", validate="many_to_many"
        )
        part["estimated_votes"] = part["votes"] * part["weight"]
        nuance_parts.append(part.groupby(["dept", "district", "nuance"], as_index=False)["estimated_votes"].sum())
    if not nuance_parts:
        raise ValueError("no candidate vote columns were found in the Ministry input")
    nuance_votes = pd.concat(nuance_parts, ignore_index=True).groupby(
        ["dept", "district", "nuance"], as_index=False
    )["estimated_votes"].sum()

    bloc_yaml = yaml.safe_load(BLOCS.read_text(encoding="utf-8"))
    mappings = bloc_yaml["mappings"]
    mapping_outputs = {}
    long_rows = []
    for mapping_name, definition in mappings.items():
        nuance_to_bloc = {
            nuance: bloc
            for bloc, nuances in definition["blocs"].items()
            for nuance in nuances
        }
        values = nuance_votes.copy()
        values["bloc"] = values["nuance"].map(nuance_to_bloc).fillna("other")
        bloc_votes = values.groupby(["dept", "district", "bloc"], as_index=False)["estimated_votes"].sum()
        district_votes = bloc_votes.groupby(["dept", "district"], as_index=False)["estimated_votes"].sum().rename(
            columns={"estimated_votes": "estimated_candidate_votes"}
        )
        bloc_votes = bloc_votes.merge(district_votes, on=["dept", "district"], how="left")
        bloc_votes["vote_share"] = bloc_votes["estimated_votes"] / bloc_votes["estimated_candidate_votes"].replace(0, pd.NA)
        bloc_votes = bloc_votes.merge(district_totals, on=["dept", "district"], how="left")
        leaders = bloc_votes.sort_values(["dept", "district", "estimated_votes", "bloc"], ascending=[True, True, False, True]).drop_duplicates(["dept", "district"])
        leader_counts = leaders.groupby("bloc").size().sort_values(ascending=False).to_dict()
        actual_parts = []
        for slot in current_map_slots:
            nuance_col, votes_col = f"Nuance candidat {slot}", f"Voix {slot}"
            if votes_col not in current_map.columns:
                continue
            part = current_map[["dept", "Code circonscription législative", nuance_col, votes_col]].copy()
            part["votes"] = count_series(part[votes_col])
            part["nuance"] = part[nuance_col].fillna("").astype(str).str.strip()
            part = part[part["nuance"].ne("") & part["votes"].gt(0)]
            part["bloc"] = part["nuance"].map(nuance_to_bloc).fillna("other")
            actual_parts.append(part.groupby(["dept", "Code circonscription législative", "bloc"], as_index=False)["votes"].sum())
        actual_bloc_votes = pd.concat(actual_parts, ignore_index=True).groupby(
            ["dept", "Code circonscription législative", "bloc"], as_index=False
        )["votes"].sum()
        actual_leaders = actual_bloc_votes.sort_values(
            ["dept", "Code circonscription législative", "votes", "bloc"], ascending=[True, True, False, True]
        ).drop_duplicates(["dept", "Code circonscription législative"])
        actual_leader_counts = actual_leaders.groupby("bloc").size().sort_values(ascending=False).to_dict()
        all_blocs = set(actual_leader_counts) | set(leader_counts)
        mmd_rows = []
        for dept, group in bloc_votes.groupby("dept"):
            for bloc, subset in group.groupby("bloc"):
                shares = subset["vote_share"].dropna()
                if len(shares):
                    mmd_rows.append({"dept": dept, "bloc": bloc, "districts": int(len(shares)),
                                     "mean_share": float(shares.mean()), "median_share": float(shares.median()),
                                     "mean_median_difference": float(shares.mean() - shares.median())})
        mapping_outputs[mapping_name] = {
            "description": definition.get("description", ""),
            "districts_with_estimates": int(district_totals.shape[0]),
            "current_map_2024_first_round_bloc_plurality_districts_metropolitan": {
                str(k): int(v) for k, v in actual_leader_counts.items()
            },
            "first_round_bloc_plurality_districts": {str(k): int(v) for k, v in leader_counts.items()},
            "change_in_bloc_plurality_district_count": {
                str(bloc): int(leader_counts.get(bloc, 0) - actual_leader_counts.get(bloc, 0))
                for bloc in sorted(all_blocs)
            },
            "m2_mean_median_difference_by_department": mmd_rows,
        }
        bloc_votes["mapping"] = mapping_name
        long_rows.extend(bloc_votes[["dept", "district", "mapping", "bloc", "estimated_votes", "vote_share",
                                     "estimated_registered", "estimated_expressed"]].to_dict(orient="records"))

    # Mainland means department codes 01–95, including Corsica; the public
    # crosswalk metadata describes metropolitan France coverage.
    mainland_mask = coverage["dept"].str.match(r"^(?:0[1-9]|[1-8][0-9]|9[0-5]|2A|2B)$")
    mainland = coverage[mainland_mask]
    all_totals = {
        "result_bureaus": int(coverage["result_bureaus"].sum()),
        "matched_bureaus": int(coverage["matched_bureaus"].sum()),
        "total_registered": int(coverage["total_registered"].sum()),
        "matched_registered": int(coverage["matched_registered"].sum()),
        "assigned_registered": float(coverage["assigned_registered"].sum()),
        "registered_coverage": float(coverage["assigned_registered"].sum() / coverage["total_registered"].sum()),
    }
    mainland_totals = {
        "result_bureaus": int(mainland["result_bureaus"].sum()),
        "matched_bureaus": int(mainland["matched_bureaus"].sum()),
        "total_registered": int(mainland["total_registered"].sum()),
        "matched_registered": int(mainland["matched_registered"].sum()),
        "assigned_registered": float(mainland["assigned_registered"].sum()),
        "registered_coverage": float(mainland["assigned_registered"].sum() / mainland["total_registered"].sum()),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(OUT / "first_round_map_sensitivity_2024_coverage.csv", index=False)
    pd.DataFrame(long_rows).to_csv(OUT / "first_round_map_sensitivity_2024_blocs.csv", index=False)
    report = {
        "status": "ESTIMATED_FIRST_ROUND_MAP_SENSITIVITY_ONLY",
        "election": "French legislative election, 2024 first round",
        "method": "Apply poids_dans_bureau to observed polling-station registered-voter and candidate-vote counts, aggregate IRIS contributions to the optimized candidate district assignment, and group candidate votes by the two draft nuance-to-bloc mappings.",
        "input_sha256": {CROSSWALK.name: crosswalk_hash, RESULTS.name: results_hash,
                         CURRENT_MAP_RESULTS.name: current_map_hash},
        "crosswalk": {"rows": int(len(crosswalk)), "unique_bureaus": int(crosswalk["bureau"].nunique()),
                       "unique_iris": int(crosswalk["iris"].nunique()), "weight_column": "poids_dans_bureau"},
        "metropolitan_district_count_comparison": {
            "observed_2024_current_map": current_map_district_count,
            "proposed_optimized_map_with_estimates": int(district_totals.shape[0]),
            "difference": int(district_totals.shape[0] - current_map_district_count),
        },
        "coverage_all_result_rows": all_totals,
        "coverage_metropolitan_rows": mainland_totals,
        "departments": coverage.to_dict(orient="records"),
        "bloc_mappings": mapping_outputs,
        "interpretation": [
            "The comparison reports current-map observed first-round bloc plurality counts and proposed-map estimated first-round bloc plurality counts for the same metropolitan territory.",
            "A difference in bloc-leading district counts is a scenario result, not a prediction of elected candidates or final seats: the proposed boundaries would change candidate slates, and the sensitivity step pools nuance votes by bloc.",
            "The linkage weights estimate population distribution and are not observed IRIS vote or registered-voter counts.",
            "No fuzzy bureau-ID repair was attempted. Unmatched and unmapped polling-station results are excluded and coverage is reported.",
            "Candidate filing, withdrawal, turnout changes, voter transfers, and second-round winners are not simulated.",
            "The 2024 French nuance-to-bloc mappings are draft political groupings; coarse and fine results are both reported.",
            "Do not issue national neutrality PASS/FAIL or ensemble-percentile conclusions from this sensitivity analysis.",
        ],
    }
    (OUT / "first_round_map_sensitivity_2024.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    low = mainland.sort_values("mapped_plan_registered_coverage").head(10)
    lines = [
        "# 2024 first-round map reallocation sensitivity",
        "",
        "**Status: estimated, partial-coverage first-round scenario only.** This reaggregates observed first-round bureau votes using the data.gouv.fr bureau-to-IRIS population weights and the optimized candidate map, then compares first-round bloc pluralities with the observed 2024 metropolitan constituency map. It does not simulate second-round winners or candidate-level winners.",
        "",
        "## Coverage",
        "",
        f"- Mainland polling-station rows matched to the table: {mainland_totals['matched_bureaus']:,}/{mainland_totals['result_bureaus']:,}.",
        f"- Mainland registered-voter total assigned to proposed districts: {mainland_totals['assigned_registered']:,.0f}/{mainland_totals['total_registered']:,} ({mainland_totals['registered_coverage']:.1%}).",
        f"- Across all Ministry bureau rows, registered-voter coverage is {all_totals['registered_coverage']:.1%}; the liaison table is metropolitan coverage, so overseas departments/territories are not represented.",
        "",
        "Lowest-coverage mainland departments (registered voters assigned to plan units / Ministry total):",
        "",
        "| Department | Assigned coverage | Matched bureau rows / total |",
        "|---|---:|---:|",
    ]
    for row in low.to_dict(orient="records"):
        lines.append(f"| {row['dept']} | {row['mapped_plan_registered_coverage']:.1%} | {int(row['matched_bureaus'])}/{int(row['result_bureaus'])} |")
    lines += ["", "## First-round geographic replay", ""]
    for name, value in mapping_outputs.items():
        lines.append(f"### {name}")
        lines.append("")
        lines.append(f"Districts with mapped first-round estimates: {value['districts_with_estimates']}.")
        lines.append("")
        lines.append(f"Observed current-map 2024 first-round bloc pluralities ({current_map_district_count} metropolitan constituencies) vs estimated proposed-map bloc pluralities ({value['districts_with_estimates']} districts). The proposal has {value['districts_with_estimates'] - current_map_district_count:+d} metropolitan seats, so these changes reflect both boundary changes and the seat-allocation scenario:")
        lines.append("")
        lines.append("| Bloc | Current map | Proposed map estimate | Change |")
        lines.append("|---|---:|---:|---:|")
        for bloc in sorted(set(value["current_map_2024_first_round_bloc_plurality_districts_metropolitan"]) | set(value["first_round_bloc_plurality_districts"])):
            current_n = value["current_map_2024_first_round_bloc_plurality_districts_metropolitan"].get(bloc, 0)
            proposed_n = value["first_round_bloc_plurality_districts"].get(bloc, 0)
            lines.append(f"| {bloc} | {current_n} | {proposed_n} | {proposed_n-current_n:+d} |")
        lines.append("")
        lines.append("Proposed districts whose largest estimated first-round bloc is each bloc (descriptive plurality counts, not elected seats):")
        lines.append("")
        lines.append("| Bloc | Districts |")
        lines.append("|---|---:|")
        for bloc, count in sorted(value["first_round_bloc_plurality_districts"].items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"| {bloc} | {count} |")
        lines.append("")
    lines += [
        "## Limits",
        "",
        "`poids_dans_bureau` distributes each bureau's observed counts across IRIS according to an estimated population share. That assumes votes and registrations follow the population weights inside each bureau. Exact bureau-ID matches were required; known mismatches and unmatched areas remain uncovered. The comparison groups candidates by draft political bloc, so it can show how geographic reallocation changes bloc pluralities under this assumption. It cannot identify which candidates would run, estimate new candidate-specific votes, or predict second-round winners.",
        "",
        "Outputs: `first_round_map_sensitivity_2024.json`, `first_round_map_sensitivity_2024_coverage.csv`, and `first_round_map_sensitivity_2024_blocs.csv`.",
    ]
    (OUT / "first_round_map_sensitivity_2024.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"mainland registered-voter coverage: {mainland_totals['registered_coverage']:.1%}")
    print(f"all-territory registered-voter coverage: {all_totals['registered_coverage']:.1%}")
    print(f"wrote {OUT / 'first_round_map_sensitivity_2024.md'}")


if __name__ == "__main__":
    main()
