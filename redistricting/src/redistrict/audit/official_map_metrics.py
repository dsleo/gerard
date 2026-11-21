"""Exact 2024 election metrics for the current official constituency map.

This audit reads quarantined Ministry constituency extracts. It never feeds
these results into generation or proposed-map scoring.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

import yaml

from redistrict.audit.round2 import eligible_candidates
from redistrict.sources import SOURCES


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def _count(value: object) -> int:
    raw = str(value or "").replace("\u00a0", "").replace(" ", "").strip()
    return int(raw) if raw else 0


def _slots(columns: list[str]) -> list[int]:
    return sorted({int(m.group(1)) for col in columns
                   if (m := re.fullmatch(r"Nuance candidat (\d+)", col))})


def _candidates(row: dict[str, str], slots: list[int]) -> list[dict]:
    result = []
    for slot in slots:
        first = str(row.get(f"Prénom candidat {slot}") or "").strip()
        last = str(row.get(f"Nom candidat {slot}") or "").strip()
        votes = _count(row.get(f"Voix {slot}"))
        nuance = str(row.get(f"Nuance candidat {slot}") or "").strip()
        if first or last or nuance or votes:
            result.append({
                "name": " ".join(x for x in (first, last) if x),
                "nuance": nuance or "DIV",
                "votes": votes,
                "elected": str(row.get(f"Elu {slot}") or "").strip().casefold() == "élu",
            })
    return result


def _district_id(row: dict[str, str]) -> str:
    dept = str(row.get("Code département") or "").strip().zfill(2)
    district = str(row.get("Code circonscription législative") or "").strip()
    return f"{dept}/{district}"


def _input_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _one_mapping(
    name: str,
    nuances: dict[str, str],
    t1: list[dict[str, str]],
    t2: list[dict[str, str]],
    slots1: list[int],
    slots2: list[int],
) -> dict:
    def bloc(nuance: str) -> str:
        return nuances.get(nuance, "other")

    # First-round bloc shares and L.162 candidate eligibility by official seat.
    first_round = []
    shutout_rows = defaultdict(lambda: {"eligible": 0, "high_share": 0})
    shutout_districts: set[str] = set()
    first_votes: dict[str, int] = defaultdict(int)
    expressed_total = registered_total = 0
    for row in t1:
        candidates = _candidates(row, slots1)
        expressed = _count(row.get("Exprimés"))
        registered = _count(row.get("Inscrits"))
        candidate_total = sum(c["votes"] for c in candidates)
        by_bloc: dict[str, int] = defaultdict(int)
        for candidate in candidates:
            key = bloc(candidate["nuance"])
            by_bloc[key] += candidate["votes"]
            first_votes[key] += candidate["votes"]
        eligible = {id(candidate) for candidate in eligible_candidates(
            {"registered": registered, "candidates": candidates}
        )}
        eligible_blocs = {bloc(candidate["nuance"]) for candidate in candidates if id(candidate) in eligible}
        for key, votes in by_bloc.items():
            item = shutout_rows[key]
            if expressed and votes / expressed >= 0.20:
                item["high_share"] += 1
                if key not in eligible_blocs:
                    item["eligible"] += 1
                    shutout_districts.add(_district_id(row))
        first_round.append({"votes": by_bloc, "expressed": expressed})
        expressed_total += expressed
        registered_total += registered

    m2 = {}
    for key in sorted(first_votes):
        shares = [row["votes"].get(key, 0) / row["expressed"]
                  for row in first_round if row["expressed"] > 0]
        m2[key] = {"districts": len(shares), "mean_share": mean(shares),
                   "median_share": median(shares), "mean_median_difference": mean(shares) - median(shares)}

    # M1 is intentionally restricted to actual two-candidate round-two contests.
    pair_stats = defaultdict(lambda: {"contests": 0, "expressed": 0, "wasted_a": 0, "wasted_b": 0})
    two_candidate = 0
    same_bloc = 0
    for row in t2:
        candidates = _candidates(row, slots2)
        if len(candidates) != 2:
            continue
        two_candidate += 1
        a, b = candidates
        bloc_a, bloc_b = bloc(a["nuance"]), bloc(b["nuance"])
        if bloc_a == bloc_b:
            same_bloc += 1
            continue
        winner = next((c for c in candidates if c["elected"]), None)
        if winner is None:
            raise ValueError(f"no elected candidate recorded for {_district_id(row)}")
        pair = tuple(sorted((bloc_a, bloc_b)))
        stats = pair_stats[pair]
        stats["contests"] += 1
        total = a["votes"] + b["votes"]
        stats["expressed"] += total
        threshold = total // 2 + 1
        for candidate, key in ((a, bloc_a), (b, bloc_b)):
            wasted = candidate["votes"] if candidate is not winner else max(0, candidate["votes"] - threshold)
            stats["wasted_a" if key == pair[0] else "wasted_b"] += wasted
    m1_pairs = {}
    for pair, stats in sorted(pair_stats.items()):
        gap = (stats["wasted_a"] - stats["wasted_b"]) / stats["expressed"] if stats["expressed"] else 0.0
        m1_pairs[f"{pair[0]} vs {pair[1]}"] = {**stats, "efficiency_gap": gap}
    m1_valid_contests = sum(v["contests"] for v in pair_stats.values())
    m1_total_expressed = sum(v["expressed"] for v in pair_stats.values())
    m1_max = max(m1_pairs.items(), key=lambda item: abs(item[1]["efficiency_gap"]), default=None)

    # Official seat winners come from the immediate T1 winners plus the T2 winners.
    winners = []
    for row in t1:
        elected = next((c for c in _candidates(row, slots1) if c["elected"]), None)
        if elected:
            winners.append(bloc(elected["nuance"]))
    for row in t2:
        elected = next((c for c in _candidates(row, slots2) if c["elected"]), None)
        if elected:
            winners.append(bloc(elected["nuance"]))
    if len(winners) != 577:
        raise ValueError(f"expected 577 official elected seats, found {len(winners)}")
    seats: dict[str, int] = defaultdict(int)
    for key in winners:
        seats[key] += 1
    m4 = {}
    for key in sorted(set(first_votes) | set(seats)):
        vote_share = first_votes.get(key, 0) / expressed_total if expressed_total else 0.0
        seat_share = seats.get(key, 0) / len(winners)
        m4[key] = {"seats": seats.get(key, 0), "seat_share": seat_share,
                   "first_round_vote_share": vote_share,
                   "seat_minus_first_round_vote_share": seat_share - vote_share}

    m5 = {key: {"districts_with_at_least_20pct_first_round_vote": value["high_share"],
                "districts_without_eligible_candidate": value["eligible"]}
          for key, value in sorted(shutout_rows.items())}

    return {
        "mapping": name,
        "m1_two_candidate_efficiency_gap": {
            "status": "COMPUTED_RESTRICTED_DIAGNOSTIC",
            "all_round_two_contests": len(t2), "two_candidate_contests": two_candidate,
            "same_bloc_contests_excluded": same_bloc,
            "different_bloc_contests_in_metric": m1_valid_contests,
            "expressed_votes_covered": m1_total_expressed,
            "contest_coverage_of_round_two": m1_valid_contests / len(t2) if t2 else 0.0,
            "bloc_pair_results": m1_pairs,
            "largest_absolute_pair_gap": ({"pair": m1_max[0], **m1_max[1]} if m1_max else None),
            "definition": "Only actual two-candidate round-two contests where the two candidates map to different blocs. Winner waste is votes above floor(total/2)+1; losing candidate votes are wasted.",
        },
        "m2_mean_median_difference": {"status": "COMPUTED_OBSERVED_T1", "denominator": "Exprimés",
                                       "districts": len(first_round), "by_bloc": m2},
        "m4_seat_vote_gap": {"status": "COMPUTED_DESCRIPTIVE_CROSS_ROUND",
                             "seat_basis": "Observed elected nuance in the 2024 official map: round-one elected candidates plus round-two winners (577 seats).",
                             "vote_basis": "Observed round-one bloc vote share among expressed votes; this is a descriptive cross-round comparison.",
                             "by_bloc": m4},
        "m5_shutout_count": {"status": "COMPUTED_L162_ELIGIBILITY_DIAGNOSTIC",
                             "districts": len(first_round), "registered_voters": registered_total,
                             "districts_with_any_block_shut_out": len(shutout_districts),
                             "expressed_votes": expressed_total,
                             "eligibility": "At least 12.5% of registered voters; if exactly one qualifies, include the next candidate (ties included); if none qualify, include the top two (ties included).",
                             "legal_review": "Provisional interpretation; legal item O9 remains open.",
                             "by_bloc": m5},
    }


def compute_official_map_metrics(project_root: Path) -> dict:
    electoral = project_root / "data/quarantine/electoral"
    t1_path = electoral / "legislatives_2024_t1_circonscriptions.csv"
    t2_path = electoral / "legislatives_2024_t2_circonscriptions.csv"
    mapping_path = project_root.parent / "docs/redistricting/blocs.draft.yaml"
    t1, t2 = _read(t1_path), _read(t2_path)
    hashes = {t1_path.name: _input_hash(t1_path), t2_path.name: _input_hash(t2_path)}
    for key, path in (("results_leg_2024_t1_constituencies", t1_path),
                      ("results_leg_2024_t2_constituencies", t2_path)):
        expected = SOURCES[key].sha256
        if expected and hashes[path.name] != expected:
            raise ValueError(f"checksum mismatch for official input {path.name}")
    if len(t1) != 577 or len(t2) != 501:
        raise ValueError(f"expected 577 T1 and 501 T2 constituency rows; found {len(t1)} and {len(t2)}")
    mappings = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))["mappings"]
    slots1, slots2 = _slots(list(t1[0])), _slots(list(t2[0]))
    outputs = {}
    for name, definition in mappings.items():
        nuance_to_bloc = {nuance: bloc for bloc, codes in definition["blocs"].items() for nuance in codes}
        outputs[name] = _one_mapping(name, nuance_to_bloc, t1, t2, slots1, slots2)
    vote_total_anomalies = []
    for round_name, rows, slots in (("round_one", t1, slots1), ("round_two", t2, slots2)):
        for row in rows:
            candidate_total = sum(c["votes"] for c in _candidates(row, slots))
            expressed = _count(row.get("Exprimés"))
            if candidate_total != expressed:
                vote_total_anomalies.append({"round": round_name, "constituency": _district_id(row),
                                             "candidate_vote_sum": candidate_total, "official_expressed": expressed,
                                             "difference": candidate_total - expressed})
    t1_expressed = sum(_count(row.get("Exprimés")) for row in t1)
    t1_registered = sum(_count(row.get("Inscrits")) for row in t1)
    return {
        "status": "OBSERVED_OFFICIAL_MAP_BASELINE",
        "election": "French legislative election 2024",
        "map": "Official legislative constituencies",
        "round_one_constituencies": len(t1), "round_two_constituencies": len(t2),
        "round_one_registered_voters": t1_registered, "round_one_expressed_votes": t1_expressed,
        "round_two_candidate_rows_are_runoffs_only": True,
        "input_sha256": hashes,
        "bloc_mapping_source": mapping_path.name,
        "mapping_note": "Both draft coarse and fine nuance-to-bloc mappings are shown; these are analytical groupings, not official Ministry blocs.",
        "source_count_anomalies": vote_total_anomalies,
        "mappings": outputs,
        "coverage": {"round_one": "577/577 circonscriptions officielles", "round_two": "501/501 circonscriptions de second tour",
                     "geography": "Official constituency totals; no commune/IRIS reallocation used."},
    }


def write_official_map_metrics(project_root: Path) -> dict:
    result = compute_official_map_metrics(project_root)
    electoral = project_root / "data/quarantine/electoral/derived"
    electoral.mkdir(parents=True, exist_ok=True)
    audit_path = electoral / "official_map_metrics_2024.json"
    audit_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    public_path = project_root / "export/browser/official-map-metrics.js"
    public_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.write_text(
        "window.REDISTRICTING_DATA=window.REDISTRICTING_DATA||{};"
        + "window.REDISTRICTING_DATA['official-map-metrics']="
        + json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + ";\n",
        encoding="utf-8",
    )
    return result
