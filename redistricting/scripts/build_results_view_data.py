"""Package the latest saved national draft and its 2024 vote scenario for the webapp.

This is a read-only export step: it never starts or changes an optimizer run.
"""

from __future__ import annotations

import base64
import csv
import gzip
import hashlib
import json
import math
import random
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

import yaml
from shapely import make_valid
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "20261120T001804Z-6d568ab9"
RUN = ROOT / "data/processed/pipeline_runs" / RUN_ID
DRAFT = RUN / "artifacts/national_draft/national_mixed_assignment_draft.geojson.gz"
SUMMARY = RUN / "artifacts/national_draft/assembly_summary.json"
ANALYSIS = ROOT / "data/processed/optimizer_monitor/runs/20261120T001804Z-3bed7d8e/analysis/summary.json"
HEURISTIC = RUN / "artifacts/national_draft/heuristic_national_comparison.json"
ELECTORAL = ROOT / "data/quarantine/electoral"
CROSSWALK = ELECTORAL / "liaison_iris_bureaux_de_vote_2024.csv"
POLLING_RESULTS = ELECTORAL / "legislatives_2024_t1_bureaux.csv"
CONSTITUENCY_RESULTS = ELECTORAL / "legislatives_2024_t1_circonscriptions.csv"
CONSTITUENCY_RESULTS_T2 = ELECTORAL / "legislatives_2024_t2_circonscriptions.csv"
BLOCS = ROOT.parent / "docs/redistricting/blocs.draft.yaml"
OUT = ROOT / "export/browser/projection-2026.js"


def department(value: object) -> str:
    value = str(value or "").strip().upper()
    return value.zfill(2) if value.isdigit() and len(value) < 3 else value


def in_department_scope(value: str) -> bool:
    return value in {"2A", "2B"} or (value.isdigit() and (int(value) <= 95 or 971 <= int(value) <= 976))


def is_metropolitan_department(value: str) -> bool:
    return value in {"2A", "2B"} or (value.isdigit() and int(value) <= 95)


def department_for_iris(iris: str) -> str:
    if iris.startswith(("971", "972", "973", "974", "976")):
        return iris[:3]
    return department(iris[:2])


def number(value: object) -> float:
    return float(str(value or "0").replace(" ", "").replace(",", ".") or 0)


def bureau_key(commune: object, bureau: object) -> str:
    return str(commune or "").strip().zfill(5) + str(bureau or "").strip().zfill(4)


def metric_summary(votes_by_district: dict[str, dict[str, float]]) -> dict:
    blocs = sorted({bloc for votes in votes_by_district.values() for bloc in votes})
    valid = {key: votes for key, votes in votes_by_district.items() if sum(votes.values()) > 0}
    seats = defaultdict(int)
    shares = {bloc: [] for bloc in blocs}
    total_votes = defaultdict(float)
    for votes in valid.values():
        total = sum(votes.values())
        for bloc in blocs:
            value = votes.get(bloc, 0.0)
            shares[bloc].append(value / total)
            total_votes[bloc] += value
        seats[max(votes, key=votes.get)] += 1
    count = len(valid)
    pooled_votes = sum(total_votes.values())
    return {
        "districts": count,
        "blocks": {
            bloc: {
                "seats": seats[bloc],
                "seat_share": seats[bloc] / count if count else 0,
                "vote_share": total_votes[bloc] / pooled_votes if pooled_votes else 0,
                "seat_minus_vote": (seats[bloc] / count - total_votes[bloc] / pooled_votes)
                if count and pooled_votes else 0,
                "mmd": mean(shares[bloc]) - median(shares[bloc]) if shares[bloc] else 0,
            }
            for bloc in blocs
        },
    }


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def polygonal(geometry):
    """Drop line and point remnants left by repairing a few island polygons."""
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return geometry
    parts = [part for child in getattr(geometry, "geoms", [])
             if (part := polygonal(child)) is not None and not part.is_empty]
    return unary_union(parts) if parts else None


def clean_display_geometry(geometry, minimum_area: float = 0.0001):
    """Drop tiny polygon parts and holes that show as artifact strokes nationally."""
    polygons = [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)
    cleaned = []
    for polygon in polygons:
        if polygon.area < minimum_area:
            continue
        holes = [ring.coords for ring in polygon.interiors
                 if Polygon(ring).area >= minimum_area]
        candidate = Polygon(polygon.exterior.coords, holes)
        if not candidate.is_empty:
            cleaned.append(candidate)
    if not cleaned:
        largest = max(polygons, key=lambda polygon: polygon.area)
        return Polygon(largest.exterior.coords)
    return unary_union(cleaned)


def quantile(values: list[float], probability: float) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def block_shares(votes_by_nuance: dict[str, float], nuance_to_block: dict[str, str], blocks: list[str]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for nuance, votes in votes_by_nuance.items():
        totals[nuance_to_block.get(nuance, "other")] += float(votes)
    total = sum(totals.values())
    return {block: totals.get(block, 0.0) / total if total else 0.0 for block in blocks}


def nearest_prediction(query: tuple[float, ...], candidates: list[dict], count: int = 20) -> tuple[float, float]:
    ranked = sorted(
        ((math.sqrt(sum((left - right) ** 2 for left, right in zip(query, row["features"]))), row)
         for row in candidates), key=lambda item: item[0]
    )[:count]
    weighted = [(1.0 / (distance + 0.015), row["target"]) for distance, row in ranked]
    total_weight = sum(weight for weight, _ in weighted)
    prediction = sum(weight * target for weight, target in weighted) / total_weight
    return prediction, ranked[0][0] if ranked else 1.0


def round_two_mapping_model(official_first_round: list[dict], second_round_results: list[dict],
                            projected_districts: list[dict], nuance_to_block: dict[str, str],
                            blocks: list[str], seed: int) -> dict:
    """Analog model for hypothetical two-bloc runoffs, calibrated on 2024 duels."""
    first_by_id = {(row["department"], int(row["district_number"])): row for row in official_first_round}
    training = []
    for runoff in second_round_results:
        if runoff["candidate_count"] != 2:
            continue
        pair_rows = [(nuance_to_block.get(nuance, "other"), votes)
                     for nuance, votes in runoff["votes_by_nuance"].items()]
        candidates = [(bloc, votes) for bloc, votes in pair_rows if votes >= 0]
        candidate_blocks = sorted({bloc for bloc, _ in candidates})
        if len(candidate_blocks) != 2 or runoff["expressed"] <= 0:
            continue
        first = first_by_id.get((runoff["department"], runoff["district_number"]))
        if not first:
            continue
        features_by_block = block_shares(first["votes_by_nuance"], nuance_to_block, blocks)
        pair = tuple(candidate_blocks)
        target = sum(votes for bloc, votes in candidates if bloc == pair[0]) / runoff["expressed"]
        training.append({
            "department": runoff["department"],
            "pair": pair,
            "features": tuple(features_by_block[block] for block in blocks),
            "target": target,
        })

    by_pair: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in training:
        by_pair[row["pair"]].append(row)

    # Cross-validation leaves out every official constituency in the held-out
    # department. These out-of-fold errors also measure and correct systematic
    # bias against the observed official second-round results.
    validation = []
    residuals_by_pair: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in training:
        peers = [candidate for candidate in by_pair[row["pair"]]
                 if candidate["department"] != row["department"]]
        if len(peers) < 5:
            continue
        predicted, _ = nearest_prediction(row["features"], peers)
        error = row["target"] - predicted
        validation.append({"department": row["department"], "prediction": predicted,
                           "observed": row["target"], "error": error, "pair": row["pair"]})
        residuals_by_pair[row["pair"]].append(error)

    # Estimate the correction on other held-out departments only when scoring
    # a validation row. This checks a global offset without using that row's truth.
    for row in validation:
        peers = [candidate for candidate in validation
                 if candidate["department"] != row["department"]]
        bias = mean(candidate["error"] for candidate in peers) if peers else 0.0
        row["calibration_bias"] = bias
        row["calibrated_prediction"] = min(1.0, max(0.0, row["prediction"] + bias))
        row["calibrated_error"] = row["observed"] - row["calibrated_prediction"]
        pair_peers = [candidate for candidate in validation
                      if candidate["department"] != row["department"]
                      and candidate["pair"] == row["pair"]]
        pair_bias = (mean(candidate["error"] for candidate in pair_peers)
                     if len(pair_peers) >= 20 else bias)
        row["pair_calibrated_prediction"] = min(1.0, max(0.0, row["prediction"] + pair_bias))
        row["pair_calibrated_error"] = row["observed"] - row["pair_calibrated_prediction"]

    global_bias = mean(row["error"] for row in validation) if validation else 0.0
    raw_validation_mae = (mean(abs(row["error"]) for row in validation) if validation else 0.0)
    candidate_validation_mae = (mean(abs(row["calibrated_error"]) for row in validation)
                                if validation else 0.0)
    raw_validation_match = (sum((row["prediction"] >= 0.5) == (row["observed"] >= 0.5)
                                for row in validation) / len(validation) if validation else 0.0)
    candidate_validation_match = (
        sum((row["calibrated_prediction"] >= 0.5) == (row["observed"] >= 0.5)
            for row in validation) / len(validation) if validation else 0.0
    )
    pair_candidate_mae = (mean(abs(row["pair_calibrated_error"]) for row in validation)
                          if validation else 0.0)
    pair_candidate_match = (
        sum((row["pair_calibrated_prediction"] >= 0.5) == (row["observed"] >= 0.5)
            for row in validation) / len(validation) if validation else 0.0
    )
    # Only retain the global correction if the held-out backtest improves MAE
    # without reducing winner accuracy. Otherwise, expose the diagnosis and
    # keep the raw center estimate while retaining empirical error bounds.
    apply_calibration = (candidate_validation_mae < raw_validation_mae
                         and candidate_validation_match >= raw_validation_match)
    applied_bias = global_bias if apply_calibration else 0.0
    for row in validation:
        row["selected_prediction"] = min(1.0, max(0.0, row["prediction"] + applied_bias))
        row["selected_error"] = row["observed"] - row["selected_prediction"]
    pair_bias_diagnostics = {
        pair: mean(rows)
        for pair, rows in residuals_by_pair.items()
        if len(rows) >= 20
    }
    # Recenter historical residuals around the estimated bias before deriving
    # uncertainty bounds and seat-count simulations.
    raw_errors_by_pair: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in validation:
        raw_errors_by_pair[row["pair"]].append(row["error"])
    centered_residuals_by_pair = {
        pair: [row["error"] - applied_bias
               for row in validation if row["pair"] == pair]
        for pair in raw_errors_by_pair
    }
    global_residuals = [row["selected_error"] for row in validation] or [0.0]
    global_half_width = quantile([abs(value) for value in global_residuals], 0.8) or 0.18
    fallback_half_width = quantile([abs(value) for value in global_residuals], 0.9) or global_half_width

    predictions = []
    for district in projected_districts:
        base = {"department": district["department"],
                "district_number": int(district["district_number"]),
                "estimated": False, "winner_bloc": None}
        if not district.get("estimated") or sum(district.get("votes_by_nuance", {}).values()) <= 0:
            predictions.append(base)
            continue
        shares = block_shares(district["votes_by_nuance"], nuance_to_block, blocks)
        ordered = sorted(blocks, key=lambda block: shares[block], reverse=True)
        if len(ordered) < 2 or shares[ordered[0]] + shares[ordered[1]] <= 0:
            predictions.append(base)
            continue
        pair = tuple(sorted(ordered[:2]))
        a, b = pair
        historical = by_pair.get(pair, [])
        if len(historical) >= 5:
            predicted, nearest_distance = nearest_prediction(tuple(shares[block] for block in blocks), historical)
            model_basis = "matched_2024_duels"
        else:
            predicted = shares[a] / (shares[a] + shares[b])
            nearest_distance = None
            model_basis = "no_transfer_fallback"
        calibration_bias = applied_bias
        predicted = min(1.0, max(0.0, predicted + applied_bias))
        pair_errors = centered_residuals_by_pair.get(pair, [])
        half_width = (quantile([abs(value) for value in pair_errors], 0.8)
                      if len(pair_errors) >= 20 else global_half_width)
        if model_basis == "no_transfer_fallback":
            half_width = max(half_width, fallback_half_width)
        low = max(0.0, predicted - half_width)
        high = min(1.0, predicted + half_width)
        support = len(historical)
        confidence = "élevée" if support >= 30 and (nearest_distance is None or nearest_distance <= 0.18) else (
            "moyenne" if support >= 10 else "faible"
        )
        predictions.append({
            **base,
            "estimated": True,
            "bloc_a": a,
            "bloc_b": b,
            "bloc_a_share": predicted,
            "calibration_bias": calibration_bias,
            "bloc_a_interval_low": low,
            "bloc_a_interval_high": high,
            "winner_bloc": a if predicted >= 0.5 else b,
            "historical_duels": support,
            "nearest_profile_distance": nearest_distance,
            "confidence": confidence,
            "model_basis": model_basis,
        })

    rng = random.Random(seed)
    samples = []
    sample_winners = []
    for _ in range(1000):
        seats: dict[str, int] = defaultdict(int)
        winners = []
        for row in predictions:
            if not row["estimated"]:
                winners.append(None)
                continue
            pair = tuple(sorted((row["bloc_a"], row["bloc_b"])))
            pool = centered_residuals_by_pair.get(pair, [])
            if len(pool) < 10:
                pool = global_residuals
            error = rng.choice(pool) if pool else 0.0
            share_a = min(1.0, max(0.0, row["bloc_a_share"] + error))
            winner = row["bloc_a"] if share_a >= 0.5 else row["bloc_b"]
            seats[winner] += 1
            winners.append(winner)
        samples.append(dict(seats))
        sample_winners.append(winners)
    medians = {block: quantile([sample.get(block, 0) for sample in samples], .5) for block in blocks}
    representative_index = min(range(len(samples)), key=lambda i: sum(abs(samples[i].get(block, 0) - medians[block]) for block in blocks))
    for row, winner in zip(predictions, sample_winners[representative_index]):
        row['representative_winner_bloc'] = winner
    central_seats: dict[str, int] = defaultdict(int)
    expected_seats: dict[str, float] = defaultdict(float)
    for row in predictions:
        if row["estimated"]:
            central_seats[row["winner_bloc"]] += 1
            pair = tuple(sorted((row["bloc_a"], row["bloc_b"])))
            pool = centered_residuals_by_pair.get(pair, [])
            if len(pool) < 10:
                pool = global_residuals
            probability_a = sum(row["bloc_a_share"] + error >= .5 for error in pool) / len(pool) if pool else float(row["bloc_a_share"] >= .5)
            expected_seats[row["bloc_a"]] += probability_a
            expected_seats[row["bloc_b"]] += 1 - probability_a
    seat_projection = {}
    for block in blocks:
        seat_values = [sample.get(block, 0) for sample in samples]
        seat_projection[block] = {
            "seats": central_seats.get(block, 0),
            "low": quantile(seat_values, 0.1),
            "high": quantile(seat_values, 0.9),
            "representative": samples[representative_index].get(block, 0),
            "expected": expected_seats.get(block, 0.0),
        }

    winner_matches = sum((row["selected_prediction"] >= 0.5) == (row["observed"] >= 0.5)
                         for row in validation)
    raw_winner_matches = sum((row["prediction"] >= 0.5) == (row["observed"] >= 0.5)
                             for row in validation)
    absolute_errors = [abs(row["selected_error"]) for row in validation]
    raw_absolute_errors = [abs(row["error"]) for row in validation]
    interval_coverage = (sum(abs(row["selected_error"]) <= global_half_width for row in validation)
                         / len(validation)
                         if validation else None)
    return {
        "mapping": "fine" if "ecologist" in blocks else "coarse",
        "blocks": blocks,
        "districts": predictions,
        "seat_projection": seat_projection,
        "validation": {
            "method": "leave_one_department_out_nearest_2024_duels",
            "duels_used": len(training),
            "held_out_predictions": len(validation),
            "bloc_winner_match_rate": winner_matches / len(validation) if validation else None,
            "mean_absolute_vote_share_error": sum(absolute_errors) / len(absolute_errors) if absolute_errors else None,
            "raw_bloc_winner_match_rate": raw_winner_matches / len(validation) if validation else None,
            "raw_mean_absolute_vote_share_error": sum(raw_absolute_errors) / len(raw_absolute_errors) if raw_absolute_errors else None,
            "measured_global_bias": global_bias,
            "applied_calibration_bias": applied_bias,
            "calibration_applied": apply_calibration,
            "candidate_calibrated_bloc_winner_match_rate": candidate_validation_match,
            "candidate_calibrated_mean_absolute_vote_share_error": candidate_validation_mae,
            "pair_calibrated_bloc_winner_match_rate": pair_candidate_match,
            "pair_calibrated_mean_absolute_vote_share_error": pair_candidate_mae,
            "80pct_interval_half_width": global_half_width,
            "80pct_interval_coverage": interval_coverage,
        },
        "calibration": {
            "historical_duels_by_pair": {" + ".join(pair): len(rows) for pair, rows in by_pair.items()},
            "pair_bias_diagnostics_not_applied": {" + ".join(pair): bias
                                                   for pair, bias in pair_bias_diagnostics.items()},
            "centered_residuals_by_pair": {" + ".join(pair): values
                                           for pair, values in centered_residuals_by_pair.items()},
            "global_residuals": global_residuals,
        },
    }


def build_round_two_projection(official_first_round: list[dict], second_round_results: list[dict],
                               projected_districts: list[dict], coarse_mapping: dict[str, str],
                               fine_mapping: dict[str, str]) -> dict:
    coarse_blocks = ["lfi", "left", "centre", "right", "far_right", "other"]
    fine_blocks = ["far_left", "left", "ecologist", "centre", "right", "far_right", "other"]
    coarse = round_two_mapping_model(official_first_round, second_round_results, projected_districts,
                                     coarse_mapping, coarse_blocks, 2024)
    fine = round_two_mapping_model(official_first_round, second_round_results, projected_districts,
                                   fine_mapping, fine_blocks, 2025)
    fine_to_family = {"far_left": "lfi", "left": "left", "ecologist": "left",
                      "centre": "centre", "right": "right", "far_right": "far_right", "other": "other"}
    combined_seats = {}
    for family_name in coarse_blocks:
        fine_rows = [fine["seat_projection"][block] for block, family_name2 in fine_to_family.items()
                     if family_name2 == family_name]
        fine_seats = {
            "seats": sum(row["seats"] for row in fine_rows),
            "low": sum(row["low"] for row in fine_rows),
            "high": sum(row["high"] for row in fine_rows),
        }
        headline = coarse["seat_projection"][family_name]
        combined_seats[family_name] = {
            "seats": headline["seats"],
            "representative": headline["representative"],
            "low": min(headline["low"], fine_seats["low"]),
            "high": max(headline["high"], fine_seats["high"]),
        }
    fine_validation = fine["validation"]
    coarse_validation = coarse["validation"]
    estimated = sum(row["estimated"] for row in coarse["districts"])
    modeled = sum(row["estimated"] and row["model_basis"] == "matched_2024_duels"
                  for row in coarse["districts"])
    return {
        "method": "coarse_bloc_nearest_2024_duel_analogs",
        "finalist_assumption": "top_two_first_round_blocs_as_hypothetical_duel",
        "interval": "10th-90th percentile; calibrated on leave-one-department-out residuals and widened across coarse/fine bloc mappings",
        "estimated_districts": estimated,
        "matched_historical_pair_districts": modeled,
        "districts": coarse["districts"],
        "seat_projection": combined_seats,
        "coarse": coarse,
        "fine_sensitivity": fine,
        "validation": coarse_validation,
    }


def territorial_metrics() -> dict:
    report = json.loads(HEURISTIC.read_text(encoding="utf-8"))
    fields = (
        "districts",
        "national_target_population_per_district",
        "population_mean_abs_deviation_from_national_target",
        "population_max_abs_deviation_from_national_target",
        "population_worst_district_by_national_target",
        "population_max_department_local_deviation",
        "compactness_loss_mean_1_minus_polsby_popper",
        "epci_excess_splits",
        "epci_unavoidable_lower_bound",
        "epci_max_possible_excess",
        "epci_pooled_avoidable_ratio",
    )
    worst_department = report["proposed_metrics"]["population_worst_district_by_national_target"]["department"]
    official_department = next(row for row in report["official_metrics"]["department_details"]
                               if row["department"] == worst_department)
    proposed_department = next(row for row in report["proposed_metrics"]["department_details"]
                               if row["department"] == worst_department)
    return {
        "scope": "558 circonscriptions départementales, outre-mer inclus",
        "official": {key: report["official_metrics"][key] for key in fields},
        "proposal": {key: report["proposed_metrics"][key] for key in fields},
        "assignment_coverage": report["assignment_coverage"],
        "worst_department_seats": {
            "department": worst_department,
            "official": official_department["districts"],
            "proposal": proposed_department["districts"],
        },
        "metrics_method": report["metrics_method"],
        "disclaimer": report["disclaimer"],
    }


def main() -> None:
    from partisan_affiliations import load_affiliations, affiliation_for, PARTY_LFI
    affiliations = load_affiliations(ELECTORAL / 'rattachement-candidats-leg-2024.xlsx', CONSTITUENCY_RESULTS)
    mappings = yaml.safe_load(BLOCS.read_text(encoding="utf-8"))["mappings"]
    nuance_to_bloc = {
        nuance: bloc
        for bloc, nuances in mappings["coarse"]["blocs"].items()
        for nuance in nuances
    }
    nuance_to_fine = {
        nuance: bloc
        for bloc, nuances in mappings["fine"]["blocs"].items()
        for nuance in nuances
    }
    nuance_to_bloc.update({'EXG': 'lfi', 'LFI_ATTACHMENT': 'lfi'})
    nuance_to_fine['LFI_ATTACHMENT'] = 'far_left'

    # The run draft carries the audited unit assignment. Dissolve its unit
    # geometries to the displayed constituency level and retain the 12
    # carry-forward departments from the same run.
    with gzip.open(DRAFT, "rt", encoding="utf-8") as stream:
        draft = json.load(stream)
    units: dict[str, str] = {}
    grouped_geometry: dict[str, list] = defaultdict(list)
    district_props: dict[str, dict] = {}
    generated_departments: set[str] = set()
    carry_departments: set[str] = set()
    for feature in draft["features"]:
        prop = feature["properties"]
        key = f"{department(prop['department'])}-{int(prop['district_number']):02d}"
        grouped_geometry[key].append(shape(feature["geometry"]))
        if prop["map_source"] == "audited_optimized_unit_assignment":
            units[str(prop["unit_id"])] = key
            generated_departments.add(department(prop["department"]))
            district_props.setdefault(key, {"department": department(prop["department"]),
                                            "district_number": int(prop["district_number"]),
                                            "map_source": "optimized"})
        else:
            carry_departments.add(department(prop["department"]))
            district_props[key] = {"department": department(prop["department"]),
                                   "district_number": int(prop["district_number"]),
                                   "map_source": "carried_forward"}

    # Collapse each bureau's IRIS weights to the current draft district. Each
    # vote is still an estimate because bureau totals are apportioned by
    # population weights, not observed at the IRIS level.
    district_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    with CROSSWALK.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            iris = str(row["iris"]).strip()
            dep = department_for_iris(iris)
            if dep not in generated_departments:
                continue
            key = units.get(iris) or units.get(iris[:5])
            if key:
                district_weights[str(row["bureau"]).zfill(9)][key] += number(row["poids_dans_bureau"])

    proposed_votes: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    proposed_votes_by_nuance: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    result_total_registered = assigned_registered = 0.0
    candidate_slots_re = re.compile(r"Nuance candidat (\d+)")
    with POLLING_RESULTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            dep = department(row.get("Code département"))
            if dep not in generated_departments:
                continue
            registered = number(row.get("Inscrits"))
            result_total_registered += registered
            links = district_weights.get(bureau_key(row.get("Code commune"), row.get("Code BV")), {})
            if not links:
                continue
            weight_total = sum(links.values())
            assigned_registered += registered * min(weight_total, 1.0)
            for field, nuance in list(row.items()):
                match = candidate_slots_re.fullmatch(field or "")
                if not match:
                    continue
                slot = match.group(1)
                nuance = str(nuance or "").strip()
                votes = number(row.get(f"Voix {slot}"))
                if votes <= 0:
                    continue
                if affiliation_for(affiliations, row, slot) == PARTY_LFI:
                    nuance = 'LFI_ATTACHMENT'
                bloc = nuance_to_bloc.get(nuance, "other")
                for district_id, weight in links.items():
                    proposed_votes[district_id][bloc] += votes * weight
                    proposed_votes_by_nuance[district_id][nuance] += votes * weight

    # Carry-forward departments have not changed boundaries, so their actual
    # 2024 constituency totals can be retained directly.
    official_votes: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    official_votes_by_nuance: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    official_registered: dict[str, float] = {}
    department_names: dict[str, str] = {}
    official_code_re = re.compile(r"Nuance candidat (\d+)")
    with CONSTITUENCY_RESULTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            dep = department(row.get("Code département"))
            if not in_department_scope(dep):
                continue
            department_names[dep] = str(row.get("Libellé département") or dep).strip()
            code = str(row.get("Code circonscription législative") or "").strip()
            try:
                district_number = int(code[len(dep):])
            except ValueError:
                continue
            key = f"{dep}-{district_number:02d}"
            official_registered[key] = number(row.get("Inscrits"))
            for field, nuance in list(row.items()):
                match = official_code_re.fullmatch(field or "")
                if not match:
                    continue
                slot = match.group(1)
                nuance = str(nuance or "").strip()
                votes = number(row.get(f"Voix {slot}"))
                if votes > 0 and affiliation_for(affiliations, row, slot) == PARTY_LFI:
                    nuance = 'LFI_ATTACHMENT'
                bloc = nuance_to_bloc.get(nuance, "other")
                official_votes[key][bloc] += votes
                official_votes_by_nuance[key][nuance] += votes

    # Combine bureau-based estimates for optimized departments with direct
    # official results in the departments kept unchanged.
    for key in list(district_props):
        dep = district_props[key]["department"]
        if dep in carry_departments and key in official_votes:
            proposed_votes[key] = official_votes[key]
            proposed_votes_by_nuance[key] = official_votes_by_nuance[key]

    # Same first-round, bloc-plurality basis on both maps. The current national
    # result totals form the reference; proposed values retain their estimated
    # coverage and are never described as candidate/second-round forecasts.
    official_scope = {key: votes for key, votes in official_votes.items()
                      if in_department_scope(key.split("-")[0])}
    official_metrics_all_departments = metric_summary(official_scope)
    proposed_metrics_all_departments = metric_summary(proposed_votes)
    # The map and the comparison table are metropolitan-only. Keep overseas
    # departmental results available for the Assembly projection, but calculate
    # the displayed official/proposed comparison on the same geographic scope.
    official_metro = {key: votes for key, votes in official_scope.items()
                      if is_metropolitan_department(key.split("-")[0])}
    proposed_metro = {key: votes for key, votes in proposed_votes.items()
                      if is_metropolitan_department(key.split("-")[0])}
    official_metrics = metric_summary(official_metro)
    proposed_metrics = metric_summary(proposed_metro)

    official_first_round = []
    for key, votes in sorted(official_scope.items()):
        if not votes or sum(votes.values()) <= 0:
            continue
        ordered_votes = sorted(votes.values(), reverse=True)
        bloc = max(votes, key=votes.get)
        dep, district_number = key.rsplit("-", 1)
        total_votes = sum(votes.values())
        official_first_round.append({
            "department": dep,
            "district_number": int(district_number),
            "bloc": bloc,
            "vote_share": votes[bloc] / total_votes,
            "margin": (ordered_votes[0] - ordered_votes[1]) / total_votes
            if len(ordered_votes) > 1 else None,
            "votes_by_bloc": dict(votes),
            "votes_by_nuance": dict(official_votes_by_nuance[key]),
            "registered": official_registered.get(key, 0),
        })

    # Observed second-round outcomes are used only to calibrate the descriptive
    # bloc-level scenario. They never feed the map generator or the optimizer.
    second_round_results = []
    with CONSTITUENCY_RESULTS_T2.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            dep = department(row.get("Code département"))
            if not in_department_scope(dep):
                continue
            code = str(row.get("Code circonscription législative") or "").strip()
            try:
                district_number = int(code[len(dep):])
            except ValueError:
                continue
            votes_by_nuance: dict[str, float] = defaultdict(float)
            candidate_count = 0
            for field, nuance in row.items():
                match = official_code_re.fullmatch(field or "")
                if not match:
                    continue
                slot = match.group(1)
                has_candidate = bool((row.get(f"Nom candidat {slot}") or row.get(f"Prénom candidat {slot}") or "").strip())
                if not has_candidate:
                    continue
                candidate_count += 1
                candidate_nuance = 'LFI_ATTACHMENT' if affiliation_for(affiliations, row, slot) == PARTY_LFI else str(nuance or "").strip()
                votes_by_nuance[candidate_nuance] += number(row.get(f"Voix {slot}"))
            second_round_results.append({
                "department": dep,
                "district_number": district_number,
                "candidate_count": candidate_count,
                "expressed": number(row.get("Exprimés")),
                "votes_by_nuance": dict(votes_by_nuance),
            })

    map_features = []
    projected_districts = []
    for key in sorted(grouped_geometry):
        props = district_props[key]
        votes = proposed_votes.get(key, {})
        estimated = bool(votes and sum(votes.values()) > 0)
        bloc = max(votes, key=votes.get) if estimated else None
        total = sum(votes.values())
        ordered = sorted(votes.values(), reverse=True)
        item = {
            **props,
            "department_name": department_names.get(props["department"], props["department"]),
            "bloc": bloc,
            "estimated": estimated,
            "vote_share": votes.get(bloc, 0) / total if estimated else None,
            "margin": (ordered[0] - ordered[1]) / total if estimated and len(ordered) > 1 else None,
            "votes_by_bloc": dict(votes),
            "votes_by_nuance": dict(proposed_votes_by_nuance.get(key, {})),
        }
        projected_districts.append(item)
        parts = [part if part.is_valid else make_valid(part) for part in grouped_geometry[key]]
        geometry = clean_display_geometry(
            polygonal(unary_union(parts)).simplify(0.0007, preserve_topology=True)
        )
        map_features.append({"type": "Feature", "properties": item, "geometry": mapping(geometry)})

    round_two = build_round_two_projection(
        official_first_round, second_round_results, projected_districts,
        nuance_to_bloc, nuance_to_fine,
    )

    official_by_department: dict[str, list[dict]] = defaultdict(list)
    proposal_by_department: dict[str, list[dict]] = defaultdict(list)
    for row in official_first_round:
        if is_metropolitan_department(row["department"]):
            official_by_department[row["department"]].append(row)
    for row in projected_districts:
        if is_metropolitan_department(row["department"]):
            proposal_by_department[row["department"]].append(row)
    department_comparison = []
    for dep in sorted(set(official_by_department) | set(proposal_by_department)):
        official_rows = official_by_department.get(dep, [])
        proposal_rows = proposal_by_department.get(dep, [])
        official_votes_by_bloc: dict[str, float] = defaultdict(float)
        proposal_votes_by_bloc: dict[str, float] = defaultdict(float)
        official_seats: dict[str, int] = defaultdict(int)
        proposal_seats: dict[str, int] = defaultdict(int)
        for row in official_rows:
            for bloc, votes in row["votes_by_bloc"].items():
                official_votes_by_bloc[bloc] += votes
            official_seats[row["bloc"]] += 1
        for row in proposal_rows:
            for bloc, votes in row["votes_by_bloc"].items():
                proposal_votes_by_bloc[bloc] += votes
            if row["estimated"]:
                proposal_seats[row["bloc"]] += 1
        official_total = sum(official_votes_by_bloc.values())
        proposal_total = sum(proposal_votes_by_bloc.values())
        all_blocs = sorted(set(official_votes_by_bloc) | set(proposal_votes_by_bloc))
        department_comparison.append({
            "department": dep,
            "name": department_names.get(dep, dep),
            "official_districts": len(official_rows),
            "proposal_districts": len(proposal_rows),
            "proposal_estimated_districts": sum(bool(row["estimated"]) for row in proposal_rows),
            "official_votes": official_total,
            "proposal_votes": proposal_total,
            "vote_coverage": proposal_total / official_total if official_total else 0,
            "official_vote_shares": {bloc: official_votes_by_bloc.get(bloc, 0) / official_total
                                      if official_total else 0 for bloc in all_blocs},
            "proposal_vote_shares": {bloc: proposal_votes_by_bloc.get(bloc, 0) / proposal_total
                                     if proposal_total else 0 for bloc in all_blocs},
            "official_bloc_seats": dict(official_seats),
            "proposal_bloc_seats": dict(proposal_seats),
        })

    # Seats without mapped vote estimates remain uncolored in the projected hemicycle.
    estimated_rows = sum(1 for row in projected_districts if row["estimated"])
    projection = {
        "status": "ASSEMBLED_DRAFT_NOT_CERTIFIED",
        "run_id": RUN_ID,
        "run_summary": json.loads(SUMMARY.read_text(encoding="utf-8")),
        "analysis": json.loads(ANALYSIS.read_text(encoding="utf-8")),
        "territorial_comparison": territorial_metrics(),
        "map": {"type": "FeatureCollection", "features": map_features},
        "districts": projected_districts,
        "official": official_metrics,
        "official_assembly": official_metrics_all_departments,
        "official_first_round": official_first_round,
        "department_comparison": department_comparison,
        "proposal": proposed_metrics,
        "assembly_projection": proposed_metrics_all_departments,
        "round_two": round_two,
        "coverage": {
            "generated_scope_registered_coverage": assigned_registered / result_total_registered
            if result_total_registered else 0,
            "estimated_districts": estimated_rows,
            "departmental_districts": len(projected_districts),
        },
        "alternatives": [],
        "input_sha256": {"national_draft": digest(DRAFT), "run_summary": digest(SUMMARY),
                          "analysis": digest(ANALYSIS), "heuristic_metrics": digest(HEURISTIC),
                          "candidate_financial_attachments": digest(ELECTORAL / 'rattachement-candidats-leg-2024.xlsx'),
                          "official_first_round_results": digest(CONSTITUENCY_RESULTS),
                          "official_second_round_results": digest(CONSTITUENCY_RESULTS_T2)},
        "caveat": "Scénario descriptif : voix du premier tour 2024 réparties par pondération bureau–IRIS sur les circonscriptions optimisées; les départements conservés reprennent leurs résultats observés. Les sièges indiquent une pluralité de blocs au premier tour, pas des députés qui auraient été élus. Carte de travail non certifiée.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(projection, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    packed = base64.b64encode(gzip.compress(raw, compresslevel=9, mtime=0)).decode("ascii")
    OUT.write_text(
        "window.REDISTRICTING_DATA=window.REDISTRICTING_DATA||{};"
        "window.REDISTRICTING_DATA['projection-2026']=(async()=>{"
        f"const b=Uint8Array.from(atob({json.dumps(packed)}),c=>c.charCodeAt(0));"
        "if(typeof DecompressionStream==='undefined')throw new Error('Gzip decompression is unavailable');"
        "const stream=new Blob([b]).stream().pipeThrough(new DecompressionStream('gzip'));"
        "return JSON.parse(await new Response(stream).text())})();\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT}: {len(map_features)} districts; {estimated_rows} with vote estimates; "
          f"{official_metrics['districts']} official metropolitan districts; "
          f"coverage {projection['coverage']['generated_scope_registered_coverage']:.1%}")


if __name__ == "__main__":
    main()
