"""Check deployed site bytes against the locally built release manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import Request, urlopen


# Also support manifests built before control files were excluded at build time.
CONTROL_FILES = frozenset({".nojekyll", ".gerard-pages-build"})


def verify(url: str, manifest: Path) -> int:
    if urlsplit(url).scheme not in {"https", "http"}:
        raise ValueError("The deployment URL must use HTTP or HTTPS")
    base = url.rstrip("/") + "/"
    expected = {
        name: digest
        for name, digest in json.loads(manifest.read_text(encoding="utf-8"))["sha256"].items()
        if name not in CONTROL_FILES
    }
    if not expected:
        raise ValueError("The release manifest contains no public files to verify")
    for name, digest in expected.items():
        request = Request(urljoin(base, quote(name)), headers={"Cache-Control": "no-cache"})
        try:
            with urlopen(request, timeout=30) as response:
                actual = hashlib.sha256(response.read()).hexdigest()
        except HTTPError as error:
            raise ValueError(
                f"HTTP {error.code} while verifying {name}: {request.full_url}"
            ) from error
        except (URLError, TimeoutError) as error:
            raise URLError(f"Cannot verify {name} at {request.full_url}: {error}") from error
        if actual != digest:
            raise ValueError(
                f"The published file differs from this release: {name} ({request.full_url})"
            )
    print(f"Verified {len(expected)} published files at {base}")
    return len(expected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--manifest", type=Path, default=Path("_site/build-manifest.json"))
    parser.add_argument("--attempts", type=int, default=1)
    args = parser.parse_args()
    attempts = max(1, args.attempts)
    for attempt in range(attempts):
        try:
            verify(args.url, args.manifest)
            return
        except (URLError, ValueError, TimeoutError) as error:
            print(f"Verification attempt {attempt + 1}/{attempts}: {error}", file=sys.stderr)
            if attempt + 1 >= attempts:
                parser.exit(1, "Published-site verification failed.\n")
            time.sleep(5)


if __name__ == "__main__":
    main()
