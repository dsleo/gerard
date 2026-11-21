"""Fetch the Assembly's published seat outlines for the local webapp."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://www.assemblee-nationale.fr/dyn/vos-deputes/hemicycle"
OUTPUT = ROOT / "export/browser/hemicycle-layout.js"
RAW_OUTPUT = ROOT / "data/raw/assembly/hemicycle_layout.json"


class HemicycleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_hemicycle_svg = False
        self.view_box = ""
        self.seats: dict[int, dict[str, str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "svg" and "hemicycle-carte" in values.get("class", "").split():
            self.in_hemicycle_svg = True
            self.view_box = values.get("viewbox", "")
            return
        if tag != "path" or not self.in_hemicycle_svg or "place" not in values.get("class", "").split():
            return
        place_id = values.get("id", "")
        if not place_id.startswith("p") or not place_id[1:].isdigit():
            return
        place = int(place_id[1:])
        if place in self.seats:
            raise ValueError(f"duplicate Assembly seat outline: {place_id}")
        self.seats[place] = {
            "place": place,
            "path": values.get("d", ""),
            "transform": values.get("transform", ""),
        }

    def handle_endtag(self, tag: str) -> None:
        if tag == "svg" and self.in_hemicycle_svg:
            self.in_hemicycle_svg = False


def main() -> None:
    request = Request(SOURCE_URL, headers={"User-Agent": "AtlasCivique/1.0 (local research interface)"})
    with urlopen(request, timeout=40) as response:
        html = response.read().decode("utf-8", "replace")

    parser = HemicycleParser()
    parser.feed(html)
    if not parser.view_box or len(parser.seats) < 570:
        raise RuntimeError(
            f"The Assembly page did not provide a complete seat plan (viewBox={parser.view_box!r}, "
            f"seats={len(parser.seats)})."
        )
    if any(not seat["path"] or not seat["transform"] for seat in parser.seats.values()):
        raise RuntimeError("The Assembly seat plan contains an incomplete seat outline.")

    payload = {
        "source": "Assemblée nationale · official hemicycle seat plan",
        "source_url": SOURCE_URL,
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "viewBox": parser.view_box,
        "seats": list(parser.seats.values()),
    }
    RAW_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    RAW_OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        "window.REDISTRICTING_DATA=window.REDISTRICTING_DATA||{};"
        + "window.REDISTRICTING_DATA['hemicycle-layout']="
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + ";\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "OK", "seat_outlines": len(parser.seats),
                      "raw_snapshot": str(RAW_OUTPUT), "output": str(OUTPUT)}))


if __name__ == "__main__":
    main()
