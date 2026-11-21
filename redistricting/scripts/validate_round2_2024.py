"""Run the quarantine-only D11 historical diagnostic for 2024."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from redistrict.audit.round2 import validate_2024  # noqa: E402


def main() -> None:
    audit_dir = ROOT / "data/quarantine/electoral"
    result = validate_2024(audit_dir)
    output = audit_dir / "derived"
    output.mkdir(parents=True, exist_ok=True)
    (output / "round2_validation_2024.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    coverage = result["winner_validation_coverage"]
    matches = result["winner_match_count"]
    rate = result["winner_match_rate"]
    rate_text = "not available" if rate is None else f"{rate:.1%}"
    report = f"""# 2024 second-round historical diagnostic

This audit-only report uses official constituency-level result extracts. It is
conditional on the actual candidates who stood in round two; it does not
predict candidacy or withdrawal and is not a forecast for proposed maps.

- Round-one constituencies: {result['round1_constituencies']}
- Round-two constituencies: {result['round2_constituencies']}
- Observed round-two candidates failing L.162 eligibility/fallback: {result['eligible_candidate_violation_count']}
- Candidate identities unmatched or ambiguous across rounds: {result['candidate_identity_mismatch_count']}
- Conditional no-transfer winner matches: {matches}/{coverage} ({rate_text})
- No-transfer winner match by observed runoff slate size: `{json.dumps(result['winner_match_by_runoff_candidate_count'], sort_keys=True)}`
- Tied first-round leaders within observed slate (not scored): {result['winner_tie_count']}
- Runoff candidate-count distribution: `{json.dumps(result['runoff_candidate_count_histogram'], sort_keys=True)}`

Single-candidate round-two records are checked for eligibility but excluded from
winner-match scoring because they have no runoff opponent.

This is a historical descriptive check, not evidence that the same heuristic
predicts voter behavior under a different district map. Read the detailed
candidate-level comparison in `round2_validation_2024.json`.
"""
    (output / "round2_validation_2024.md").write_text(report, encoding="utf-8")
    print(f"round-two constituencies: {result['round2_constituencies']}")
    print(f"L.162 eligibility violations: {result['eligible_candidate_violation_count']}")
    print(f"candidate identity mismatches: {result['candidate_identity_mismatch_count']}")
    print(f"conditional no-transfer winner matches: {matches}/{coverage} ({rate_text})")
    print(f"winner match by runoff slate: {result['winner_match_by_runoff_candidate_count']}")
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
