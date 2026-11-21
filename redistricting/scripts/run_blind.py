"""Run one generation entry point with the electoral quarantine OS-inaccessible.

macOS only for now: invokes Apple's sandbox-exec, probes that an existing
quarantine file cannot be read, and aggregates each Python process manifest.
Direct script invocations remain guarded but are reported as NOT CERTIFIED.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = {
    "run_next_optimization_series.py",
    "run_evolution_campaign.py",
    "benchmark_optimization.py",
    "map_to_cog2024.py",
    "run_gate1.py",
    "run_gate2.py",
    "sample_departments.py",
    "optimize_departments.py",
    "export_webapp.py",
    "build_browser_data.py",
    "check_join.py",
    "validate_national_plan.py",
    "audit_official_starting_plans.py",
    "audit_official_historical_population.py",
    "audit_residual_search_readiness.py",
    "audit_search_run_results.py",
    "audit_official_seed_integration.py",
    "assemble_mixed_national_draft.py",
    "score_national_heuristic.py",
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in SCRIPTS:
        print("Usage: python scripts/run_blind.py <generation-script.py> [script arguments...]")
        print("Allowed scripts: " + ", ".join(sorted(SCRIPTS)))
        return 2
    if sys.platform != "darwin":
        print("No verified OS quarantine-deny runner is configured for this platform; refusing certification.")
        return 3

    sandbox_exec = Path("/usr/bin/sandbox-exec")
    if not sandbox_exec.exists():
        print("macOS sandbox-exec is unavailable; refusing to run without the quarantine deny rule.")
        return 3

    quarantine = (ROOT / "data/quarantine").resolve()
    probe = quarantine / "electoral/README.md"
    if not probe.is_file():
        print("Blindness probe file is missing; cannot verify quarantine isolation.")
        return 3

    profile = (
        f'(version 1) (allow default) '
        f'(deny file-read* (subpath "{quarantine}")) '
        f'(deny file-write* (subpath "{quarantine}"))'
    )
    # A failing sandbox executable is not evidence that a quarantine read was
    # denied. First prove the sandbox itself can start an innocuous command.
    smoke = subprocess.run(
        [str(sandbox_exec), "-p", profile, sys.executable, "-c", "pass"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    if smoke.returncode != 0:
        print("OS isolation could not start; refusing generation: " + smoke.stderr.strip())
        return 3
    probe_result = subprocess.run(
        [str(sandbox_exec), "-p", profile, sys.executable, "-c", "import sys; from pathlib import Path; Path(sys.argv[1]).read_bytes()", str(probe)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    probe_denied = probe_result.returncode != 0
    if not probe_denied:
        print("The operating system did not deny a read of the quarantine probe; refusing to run.")
        return 3

    script = sys.argv[1]
    script_args = sys.argv[2:]
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run_dir = ROOT / "data/processed/blindness/runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env["REDISTRICTING_BLIND_RUN_ID"] = run_id
    env["REDISTRICTING_BLINDNESS_VERIFIED"] = "seatbelt"

    command = [str(sandbox_exec), "-p", profile, sys.executable, str(ROOT / "scripts" / script), *script_args]
    result = subprocess.run(command, cwd=ROOT, env=env)

    process_manifests = []
    for path in sorted(run_dir.glob("process-*.json")):
        try:
            process_manifests.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    complete_manifests = bool(process_manifests) and all(
        item.get("python_guard_installed")
        and item.get("os_quarantine_deny_claim")
        and not item.get("blocked_attempts")
        and all(digest != "UNAVAILABLE" for digest in item.get("opened_project_inputs_sha256", {}).values())
        for item in process_manifests
    )
    passed = result.returncode == 0 and probe_denied and complete_manifests
    report = {
        "run_id": run_id,
        "script": script,
        "arguments": script_args,
        "completed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "PASS" if passed else "NOT CERTIFIED",
        "exit_code": result.returncode,
        "os_quarantine_deny": "macOS sandbox-exec; file-read* and file-write* denied for data/quarantine",
        "quarantine_probe_denied": probe_denied,
        "process_manifests": process_manifests,
        "coverage_complete": complete_manifests,
        "limitations": [
            "This certifies only the listed generation process and its Python child processes.",
            "The runner refuses to claim a pass when any input hash or process manifest is missing.",
        ],
    }
    (run_dir / "compliance_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Blindness compliance: {report['status']} ({run_dir / 'compliance_report.json'})")
    return result.returncode if result.returncode else (0 if passed else 4)


if __name__ == "__main__":
    raise SystemExit(main())
