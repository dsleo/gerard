"""Historical diagnostics for the French two-round legislative system.

This module reads quarantined election data and must never be imported by
generation code. Historical validation is performed at the existing
constituency level; it does not imply that results can be transferred to a
proposed map.
"""

from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from collections import Counter
from pathlib import Path


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _dept(value: str) -> str:
    value = value.strip().upper()
    return value.zfill(2) if value.isdigit() and len(value) < 3 else value


def _constituency_key(row: dict[str, str]) -> tuple[str, int]:
    code = re.sub(r"\s+", "", row["Code circonscription législative"])
    match = re.search(r"(\d{2})$", code)
    if not match:
        raise ValueError(f"cannot parse constituency code: {code!r}")
    return _dept(row["Code département"]), int(match.group(1))


def _integer(value: str) -> int:
    return int((value or "").strip().replace(" ", "") or "0")


def _candidates(row: dict[str, str]) -> list[dict[str, object]]:
    candidates = []
    for key in row:
        m = re.fullmatch(r"Nom candidat (\d+)", key)
        if not m:
            continue
        i = m.group(1)
        surname = (row.get(f"Nom candidat {i}") or "").strip()
        first_name = (row.get(f"Prénom candidat {i}") or "").strip()
        if not surname and not first_name:
            continue
        candidates.append({
            "id": (_norm(surname), _norm(first_name), _norm(row.get(f"Sexe candidat {i}", ""))),
            "name": f"{first_name} {surname}".strip(),
            "nuance": (row.get(f"Nuance candidat {i}") or "").strip(),
            "votes": _integer(row.get(f"Voix {i}", "")),
            "elected": bool((row.get(f"Elu {i}") or "").strip()),
        })
    return candidates


def _read(path: Path) -> dict[tuple[str, int], dict[str, object]]:
    rows = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            key = _constituency_key(row)
            if key in rows:
                raise ValueError(f"duplicate constituency row: {key}")
            candidates = _candidates(row)
            rows[key] = {
                "registered": _integer(row["Inscrits"]),
                "candidates": candidates,
                "winner": next((c for c in candidates if c["elected"]), None),
                "votes_total": _integer(row["Exprimés"]),
            }
    return rows


def eligible_candidates(first: dict[str, object]) -> list[dict[str, object]]:
    """Apply L.162 eligibility and its one/zero-qualifier fallback.

    Include every candidate tied at the fallback cutoff. This avoids making
    legal eligibility depend on the source row order when votes are tied.
    """
    registered = int(first["registered"])
    candidates = sorted(first["candidates"], key=lambda c: int(c["votes"]), reverse=True)
    qualified = [c for c in candidates if int(c["votes"]) * 8 >= registered]
    if len(qualified) == 1 and len(candidates) > 1:
        fallback = max(int(c["votes"]) for c in candidates if c is not qualified[0])
        qualified.extend(c for c in candidates
                         if c is not qualified[0] and int(c["votes"]) == fallback)
    elif len(qualified) == 0:
        if len(candidates) > 2:
            cutoff = int(candidates[1]["votes"])
            qualified = [c for c in candidates if int(c["votes"]) >= cutoff]
        else:
            qualified = candidates
    return qualified


def validate_2024(data_dir: Path) -> dict[str, object]:
    """Check L.162 against observed runoffs and score a conditional no-transfer baseline."""
    from redistrict.sources import SOURCES

    input_paths = {
        "round1": data_dir / "legislatives_2024_t1_circonscriptions.csv",
        "round2": data_dir / "legislatives_2024_t2_circonscriptions.csv",
    }
    input_sources = {
        "round1": SOURCES["results_leg_2024_t1_constituencies"],
        "round2": SOURCES["results_leg_2024_t2_constituencies"],
    }
    input_hashes = {}
    for key, path in input_paths.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        expected = input_sources[key].sha256
        if expected and digest != expected:
            raise ValueError(f"checksum mismatch for quarantined {key} input: {path.name}")
        input_hashes[path.name] = digest
    first = _read(input_paths["round1"])
    second = _read(input_paths["round2"])
    eligible_violations = []
    unmatched_candidates = []
    winner_predictions = []
    winner_ties = []
    candidate_count_histogram: Counter[int] = Counter()

    for key, runoff in second.items():
        if key not in first:
            raise ValueError(f"round-two constituency missing in round one: {key}")
        r1 = first[key]
        eligible = {c["id"] for c in eligible_candidates(r1)}
        first_by_id: dict[tuple[str, str, str], list[dict[str, object]]] = {}
        for candidate in r1["candidates"]:
            first_by_id.setdefault(candidate["id"], []).append(candidate)
        actual = runoff["candidates"]
        candidate_count_histogram[len(actual)] += 1
        actual_r1 = []
        for candidate in actual:
            matches = first_by_id.get(candidate["id"], [])
            if len(matches) != 1:
                unmatched_candidates.append({"constituency": f"{key[0]}-{key[1]}", "candidate": candidate["name"]})
                continue
            match = matches[0]
            actual_r1.append(match)
            if match["id"] not in eligible:
                eligible_violations.append({"constituency": f"{key[0]}-{key[1]}", "candidate": candidate["name"]})
        observed_winner = runoff["winner"]
        if observed_winner is None or len(actual) < 2 or len(actual_r1) != len(actual):
            continue
        winner_matches = first_by_id.get(observed_winner["id"], [])
        if len(winner_matches) != 1 or not actual_r1:
            continue
        predicted = max(actual_r1, key=lambda c: int(c["votes"]))
        if sum(int(c["votes"]) == int(predicted["votes"]) for c in actual_r1) > 1:
            winner_ties.append(f"{key[0]}-{key[1]}")
            continue
        winner_predictions.append({
            "constituency": f"{key[0]}-{key[1]}",
            "match": predicted["id"] == observed_winner["id"],
            "predicted": predicted["name"],
            "observed": observed_winner["name"],
            "predicted_nuance": predicted["nuance"],
            "observed_nuance": observed_winner["nuance"],
            "runoff_candidates": len(actual),
        })

    matched = len(winner_predictions)
    correct = sum(bool(r["match"]) for r in winner_predictions)
    grouped: dict[int, list[dict[str, object]]] = {}
    for row in winner_predictions:
        grouped.setdefault(int(row["runoff_candidates"]), []).append(row)
    return {
        "method": "conditional_no_transfer_actual_runoff_slate",
        "input_sha256": input_hashes,
        "round1_constituencies": len(first),
        "round2_constituencies": len(second),
        "eligible_candidate_violations": eligible_violations,
        "eligible_candidate_violation_count": len(eligible_violations),
        "unmatched_or_ambiguous_candidates": unmatched_candidates,
        "candidate_identity_mismatch_count": len(unmatched_candidates),
        "winner_validation_coverage": matched,
        "winner_match_count": correct,
        "winner_match_rate": correct / matched if matched else None,
        "winner_tie_count": len(winner_ties),
        "winner_match_by_runoff_candidate_count": {
            str(n): {
                "constituencies": len(rows),
                "matches": sum(bool(r["match"]) for r in rows),
                "match_rate": sum(bool(r["match"]) for r in rows) / len(rows),
            }
            for n, rows in sorted(grouped.items())
        },
        "runoff_candidate_count_histogram": {str(k): v for k, v in sorted(candidate_count_histogram.items())},
        "winner_predictions": winner_predictions,
        "interpretation": (
            "Historical diagnostic conditional on the candidates who actually stood in round two. "
            "It does not predict who files or withdraws and is not a forecast for proposed maps."
        ),
    }
