"""Serve the project folder over HTTP so the webapp can load export/ (fetch does not work from file://).

Run from redistricting/:   .venv/bin/python scripts/serve.py
Then open http://localhost:8000/webapp/
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import subprocess
import sys
import threading
import uuid
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from redistrict.allocate.policy import D53_FIXED_SEATS  # noqa: E402

PORT = 8000
MONITOR_ROOT = ROOT / "data/processed/optimizer_monitor/runs"
ACTIVE_FILE = ROOT / "data/processed/optimizer_monitor/active.json"
RUN_LOCK = threading.Lock()
ACTIVE_PROCESS: subprocess.Popen | None = None


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def run_path(run_id: str) -> Path | None:
    if not run_id or any(ch not in "0123456789T-Zabcdefghijklmnopqrstuvwxyz-" for ch in run_id):
        return None
    path = MONITOR_ROOT / run_id
    return path if path.parent == MONITOR_ROOT else None


def alive(run: dict) -> bool:
    if run.get("status") not in {"RUNNING", "PENDING"}:
        return False
    pid = run.get("pid")
    if not pid:
        try:
            started = dt.datetime.fromisoformat(run["started_utc"])
            return (dt.datetime.now(dt.timezone.utc) - started).total_seconds() < 60
        except (KeyError, ValueError):
            return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def read_run(run_id: str) -> dict | None:
    path = run_path(run_id)
    if path is None:
        return None
    try:
        return json.loads((path / "run.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def tail(path: Path, count: int = 24) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-count:]
    except OSError:
        return []


def summarize_optimizer(path: Path) -> dict | None:
    rows = []
    directory = path / "departments"
    if not directory.exists():
        return None
    for item in directory.glob("*.json"):
        try:
            rows.append(json.loads(item.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    completed = [row for row in rows if row.get("status") == "COMPLETED"]
    if not completed:
        return None
    values = [row.get("best", {}) for row in completed]
    def avg(key: str) -> float | None:
        items = [float(value[key]) for value in values if isinstance(value.get(key), (int, float))]
        return sum(items) / len(items) if items else None
    return {
        "departments_completed": len(completed),
        "proposals_completed": sum(int(row.get("proposals_completed", 0)) for row in completed),
        "accepted_moves": sum(int(row.get("accepted_moves", 0)) for row in completed),
        "mean_best_score": avg("L"), "mean_population_deviation": avg("l_pop"),
        "mean_compactness_loss": avg("l_comp"), "mean_epci_loss": avg("l_epci"),
    }


def legacy_optimizer_history() -> dict | None:
    output = ROOT / "data/processed/optimized"
    rows = []
    for item in output.glob("*.json"):
        try:
            result = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if result.get("dept") and result.get("optimized"):
            rows.append(result)
    if not rows:
        return None
    best = [float(row["optimized"]["L"]) for row in rows if isinstance(row["optimized"].get("L"), (int, float))]
    starts = [float(row["start"]["L"]) for row in rows if isinstance(row.get("start", {}).get("L"), (int, float))]
    steps = [int(row["steps"]) for row in rows if isinstance(row.get("steps"), int)]
    accepted = [int(row.get("accepted", 0)) for row in rows]
    better_than_sampled = 0
    for row in rows:
        sampled_scores = [float(plan["L"]) for plan in row.get("sampled", [])
                          if isinstance(plan.get("L"), (int, float))]
        if sampled_scores and float(row["optimized"]["L"]) <= min(sampled_scores):
            better_than_sampled += 1
    latest_file = max((item.stat().st_mtime for item in output.glob("*.json")), default=0)
    return {
        "run_id": "legacy-saved-candidates",
        "status": "LEGACY_EXPLORATORY_REJECTED",
        "started_utc": None,
        "completed_utc": None,
        "current_stage": "Sorties archivées, métadonnées de run manquantes",
        "configuration": {"optimizer_steps": max(steps) if steps else None, "seed": None, "workers": None},
        "optimization_summary": {
            "departments_completed": len(rows), "proposals_completed": sum(steps),
            "accepted_moves": sum(accepted),
            "mean_start_score": sum(starts) / len(starts) if starts else None,
            "mean_best_score": sum(best) / len(best) if best else None,
            "at_least_as_good_as_sampled": better_than_sampled,
        },
        "history_note": "Anciennes sorties candidates, rejetées par les contrôles stricts. Aucun ID de run, seed, durée exacte ou historique proposition-par-proposition n'a été conservé.",
        "artifact_mtime_utc": dt.datetime.fromtimestamp(latest_file, dt.timezone.utc).isoformat() if latest_file else None,
    }


def gate_readiness() -> dict:
    report_path = ROOT / "data/processed/gate1/step1_graph_audit.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        infeasible_search = {d: reason for d, reason in report.get("infeasible_departments", {}).items()
                             if d not in D53_FIXED_SEATS}
        disconnected_search = {d: comps for d, comps in report.get("disconnected_departments", {}).items()
                               if d not in D53_FIXED_SEATS}
        blocked = bool(infeasible_search or disconnected_search or report.get("flag_counts")
                       or report.get("departments") != 101 or report.get("seats_sum") != 558)
        return {
            "available": True,
            "status": "BLOCKED" if blocked else "SEARCH_READY",
            "search_departments": report.get("departments", 0) - len(D53_FIXED_SEATS),
            "infeasible_departments": len(infeasible_search),
            "disconnected_departments": len(disconnected_search),
            "carry_forward_component_diagnostics": len(set(report.get("infeasible_departments", {})) & set(D53_FIXED_SEATS)),
            "flags": report.get("flag_counts", {}),
            "last_updated": dt.datetime.fromtimestamp(report_path.stat().st_mtime, dt.timezone.utc).isoformat(),
            "note": "Search is ready for the 89 non-frozen departments. The 12 fixed departments are left unchanged and are outside this search.",
        }
    except (OSError, json.JSONDecodeError):
        return {"available": False, "status": "UNKNOWN", "note": "No saved Gate 1 report is available."}


def validated_config(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Run settings must be a JSON object")
    config = {
        "replicates": int(value.get("replicates", 3)),
        "sample_steps": int(value.get("sample_steps", 300)),
        "optimizer_steps": int(value.get("optimizer_steps", 800)),
        "workers": int(value.get("workers", 3)),
        "seed": int(value.get("seed", 42)),
        "patience_rounds": int(value.get("patience_rounds", 3)),
        "min_improvement": float(value.get("min_improvement", 0.0001)),
    }
    bounds = {
        "replicates": (1, 5), "sample_steps": (100, 1000),
        "optimizer_steps": (100, 2000), "workers": (1, 8),
        "seed": (0, 2**32 - 1), "patience_rounds": (0, 10),
        "min_improvement": (0.0, 0.01),
    }
    for key, (low, high) in bounds.items():
        if not low <= config[key] <= high:
            raise ValueError(f"{key} must be between {low} and {high}")
    config["optimizer_steps_per_round"] = 100
    config["optimizer_min_rounds"] = 4
    config["objective_weights"] = {"population": 0.5, "compactness": 0.3, "epci_splits": 0.2}
    config["population_tolerance"] = 0.2
    config["temperature"] = {"start": 0.02, "end": 0.0005, "schedule": "geometric"}
    return config


class Handler(http.server.SimpleHTTPRequestHandler):
    def _json(self, value: dict, status: int = 200) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _active_run(self) -> dict | None:
        try:
            active = json.loads(ACTIVE_FILE.read_text(encoding="utf-8"))
            run = read_run(str(active.get("run_id", "")))
            if run and run.get("status") in {"RUNNING", "PENDING"} and run.get("pid") and not alive(run):
                path = run_path(str(run["run_id"]))
                if path:
                    run["optimization_summary"] = summarize_optimizer(path)
                    run["status"] = "FAILED"
                    run["completed_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
                    run["error"] = "The local server no longer sees the pipeline process running."
                    atomic_json(path / "run.json", run)
            return run
        except (OSError, json.JSONDecodeError):
            return None

    def do_GET(self) -> None:
        if self.path == "/api/optimizer/status":
            run = self._active_run()
            departments = []
            recent_log = []
            if run:
                path = run_path(str(run.get("run_id", "")))
                if path:
                    progress_dir = path / "departments"
                    if progress_dir.exists():
                        for item in progress_dir.glob("*.json"):
                            try:
                                departments.append(json.loads(item.read_text(encoding="utf-8")))
                            except (OSError, json.JSONDecodeError):
                                continue
                    recent_log = tail(path / "pipeline-console.log")
            departments.sort(key=lambda row: str(row.get("dept", "")))
            self._json({"run": run, "departments": departments, "recent_log": recent_log,
                        "readiness": gate_readiness()})
            return
        if self.path == "/api/optimizer/history":
            records = []
            if MONITOR_ROOT.exists():
                for path in MONITOR_ROOT.glob("*/run.json"):
                    try:
                        record = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    records.append({key: record.get(key) for key in (
                        "run_id", "status", "started_utc", "completed_utc", "current_stage",
                        "configuration", "failures", "pipeline_run_id", "optimization_summary", "analysis_summary",
                        "history_note", "artifact_mtime_utc",
                    )})
            legacy = legacy_optimizer_history()
            if legacy:
                records.append(legacy)
            records.sort(key=lambda row: str(row.get("started_utc", "")), reverse=True)
            self._json({"runs": records[:30]})
            return
        super().do_GET()

    def do_POST(self) -> None:
        global ACTIVE_PROCESS
        if self.path != "/api/optimizer/start":
            self._json({"error": "Unknown API route"}, 404)
            return
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"}:
            self._json({"error": "The optimizer can only be launched from this local app"}, 403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 4096:
                raise ValueError("Run settings are too large")
            body = json.loads(self.rfile.read(length) or b"{}")
            config = validated_config(body)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)
            return
        readiness = gate_readiness()
        if readiness.get("status") == "BLOCKED":
            self._json({"error": "Gate 1 found a blocking issue in the 89 search departments, or the national population scope is incomplete. The 12 frozen departments do not block search; their carry-forward validator remains a separate requirement for accepting the complete national map.",
                        "readiness": readiness}, 409)
            return
        with RUN_LOCK:
            previous = self._active_run()
            if previous and alive(previous):
                self._json({"error": "A national run is already active", "run_id": previous.get("run_id")}, 409)
                return
            run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
            path = MONITOR_ROOT / run_id
            path.mkdir(parents=True, exist_ok=False)
            run = {
                "run_id": run_id, "status": "RUNNING", "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "configuration": config, "current_stage": "starting", "pid": None,
            "history_scope": "Exploratory search over the 89 non-frozen departments; not a national-map acceptance run.",
            }
            atomic_json(path / "run.json", run)
            atomic_json(ACTIVE_FILE, {"run_id": run_id})
            env = os.environ.copy()
            env["REDISTRICT_MONITOR_DIR"] = str(path)
            command = [sys.executable, str(ROOT / "scripts/run_national_pipeline.py"),
                       "--replicates", str(config["replicates"]),
                       "--sample-steps", str(config["sample_steps"]),
                       "--optimizer-steps", str(config["optimizer_steps"]),
                       "--workers", str(config["workers"]), "--seed", str(config["seed"]),
                       "--optimizer-steps-per-round", str(config["optimizer_steps_per_round"]),
                       "--optimizer-patience-rounds", str(config["patience_rounds"]),
                       "--optimizer-min-rounds", str(config["optimizer_min_rounds"]),
                       "--optimizer-min-improvement", str(config["min_improvement"])]
            log = (path / "pipeline-console.log").open("w", encoding="utf-8")
            try:
                ACTIVE_PROCESS = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            except OSError as exc:
                log.close()
                run.update(status="FAILED_TO_START", error=str(exc), completed_utc=dt.datetime.now(dt.timezone.utc).isoformat())
                atomic_json(path / "run.json", run)
                self._json({"error": "Could not start the national pipeline", "detail": str(exc)}, 500)
                return
            run = json.loads((path / "run.json").read_text(encoding="utf-8"))
            run["pid"] = ACTIVE_PROCESS.pid
            atomic_json(path / "run.json", run)
            threading.Thread(target=self._wait_for_run, args=(ACTIVE_PROCESS, run_id, log), daemon=True).start()
            self._json({"run": run}, 202)

    @staticmethod
    def _wait_for_run(process: subprocess.Popen, run_id: str, log) -> None:
        global ACTIVE_PROCESS
        exit_code = process.wait()
        log.close()
        path = run_path(run_id)
        if path:
            try:
                run = json.loads((path / "run.json").read_text(encoding="utf-8"))
                run["optimization_summary"] = summarize_optimizer(path)
                if run.get("status") in {"RUNNING", "PENDING"}:
                    run["status"] = "COMPLETED" if exit_code == 0 else "FAILED"
                    run["completed_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
                    run["exit_code"] = exit_code
                    atomic_json(path / "run.json", run)
            except (OSError, json.JSONDecodeError):
                pass
        ACTIVE_PROCESS = None

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def main() -> None:
    handler = functools.partial(Handler, directory=str(ROOT))
    with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler) as httpd:
        print(f"serving {ROOT} at http://localhost:{PORT}/webapp/  (Ctrl-C to stop)")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
