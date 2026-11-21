"""Compute and publish audit-only 2024 baseline metrics for the official map."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from redistrict.audit.official_map_metrics import write_official_map_metrics  # noqa: E402


if __name__ == "__main__":
    result = write_official_map_metrics(ROOT)
    print(json.dumps({
        "status": result["status"],
        "round_one_constituencies": result["round_one_constituencies"],
        "round_two_constituencies": result["round_two_constituencies"],
        "output": "data/quarantine/electoral/derived/official_map_metrics_2024.json",
        "webapp": "export/browser/official-map-metrics.js",
    }, ensure_ascii=False))
