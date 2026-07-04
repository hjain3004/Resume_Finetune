"""One-off helper: fetch a URL and save its raw response body + headers as a
test fixture. Usage: python scripts/record_fixture.py <url> <name>

Saves tests/fixtures/<name>.body and tests/fixtures/<name>.headers.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

USER_AGENT = "job-pipeline (personal use)"
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def record_fixture(url: str, name: str) -> None:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    body_path = FIXTURES_DIR / f"{name}.body"
    headers_path = FIXTURES_DIR / f"{name}.headers.json"
    body_path.write_bytes(response.content)
    headers_path.write_text(json.dumps(dict(response.headers), indent=2))
    print(f"Saved {body_path} ({len(response.content)} bytes) and {headers_path}")


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python scripts/record_fixture.py <url> <name>", file=sys.stderr)
        return 1
    record_fixture(sys.argv[1], sys.argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
