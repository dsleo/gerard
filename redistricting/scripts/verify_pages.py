"""Check deployed site bytes against the locally built release manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import Request, urlopen


def verify(url: str, manifest: Path) -> int:
    if urlsplit(url).scheme not in {"https", "http"}:
        raise ValueError("The deployment URL must use HTTP or HTTPS")
    base = url.rstrip("/") + "/"
    expected = json.loads(manifest.read_text(encoding="utf-8"))["sha256"]
    for name, digest in expected.items():
        request = Request(urljoin(base, quote(name)), headers={"Cache-Control": "no-cache"})
        with urlopen(request, timeout=30) as response:
            actual = hashlib.sha256(response.read()).hexdigest()
        if actual != digest:
            raise ValueError(f"The published file differs from this release: {name}")
    print(f"Verified {len(expected)} published files at {base}")
    return len(expected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--manifest", type=Path, default=Path("_site/build-manifest.json"))
    parser.add_argument("--attempts", type=int, default=1)
    args = parser.parse_args()
    for attempt in range(max(1, args.attempts)):
        try:
            verify(args.url, args.manifest)
            return
        except (URLError, ValueError, TimeoutError):
            if attempt + 1 >= args.attempts:
                raise
            time.sleep(5)


if __name__ == "__main__":
    main()
