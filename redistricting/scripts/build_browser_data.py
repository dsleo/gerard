"""Write lazy-loading, gzip-packed JavaScript companions for the webapp.

Run from redistricting/: .venv/bin/python scripts/run_blind.py build_browser_data.py
"""

from __future__ import annotations

import json
import base64
import gzip
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from redistrict.ingest.generation import install_generation_guard

ROOT = Path(__file__).resolve().parents[1]
install_generation_guard(ROOT, "build_browser_data.py")
EXPORT = ROOT / "export"
BROWSER = EXPORT / "browser"


def write_payload(path: Path, key: str, source: Path) -> None:
    if source.suffix == ".gz":
        compressed = source.read_bytes()
        raw = gzip.decompress(compressed)
    else:
        raw = source.read_bytes()
        compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    payload = json.loads(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "window.REDISTRICTING_DATA=window.REDISTRICTING_DATA||{};"
        f"window.REDISTRICTING_DATA[{json.dumps(key)}]=(async()=>{{"
        f"const b=Uint8Array.from(atob({json.dumps(base64.b64encode(compressed).decode('ascii'))}),c=>c.charCodeAt(0));"
        "if(typeof DecompressionStream==='undefined')throw new Error('Gzip decompression is unavailable');"
        "const stream=new Blob([b]).stream().pipeThrough(new DecompressionStream('gzip'));"
        "return JSON.parse(await new Response(stream).text())})();",
        encoding="utf-8",
    )


def main() -> None:
    acceptance_path = EXPORT / "acceptance.json"
    if not acceptance_path.is_file() or json.loads(acceptance_path.read_text(encoding="utf-8")).get("status") != "ACCEPTED_MACHINE_CHECKS":
        raise RuntimeError("refusing to build browser map data without an accepted national map certificate")
    write_payload(BROWSER / "summary.js", "summary", EXPORT / "summary.json")
    write_payload(BROWSER / "gate1.js", "gate1", EXPORT / "gate1.json")
    write_payload(BROWSER / "departments.js", "departments", EXPORT / "departments.geojson.gz")
    maps_dir = BROWSER / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)
    for old in maps_dir.glob("*.js"):
        old.unlink()
    for source in sorted((EXPORT / "maps").glob("*.geojson.gz")):
        dept = source.name.removesuffix(".geojson.gz")
        write_payload(maps_dir / f"{dept}.js", f"map:{dept}", source)
    print(f"Prepared direct-open map data in {BROWSER}")


if __name__ == "__main__":
    main()
