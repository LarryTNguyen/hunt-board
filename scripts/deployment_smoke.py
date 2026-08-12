"""Provider-neutral post-deploy smoke checks; makes no mutations."""

from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def check(base_url: str, path: str) -> dict:
    request = Request(f"{base_url.rstrip('/')}{path}", headers={"Accept": "application/json"})
    with urlopen(request, timeout=10) as response:  # noqa: S310 - operator-provided host
        if response.status != 200:
            raise RuntimeError(f"{path} returned {response.status}")
        payload = json.loads(response.read())
        if payload.get("status") != "ok":
            raise RuntimeError(f"{path} returned unsafe status: {payload}")
        return payload


def main() -> int:
    base_url = os.environ.get("HUNT_BOARD_SMOKE_BASE_URL")
    if not base_url:
        print("HUNT_BOARD_SMOKE_BASE_URL is required", file=sys.stderr)
        return 2
    try:
        results = {path: check(base_url, path) for path in ("/health/live", "/health/ready")}
    except (HTTPError, URLError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps({"status": "ok", "checks": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
