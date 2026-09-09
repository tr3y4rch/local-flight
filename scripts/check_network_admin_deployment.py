#!/usr/bin/env python3
"""Verify the operator shell and its read routes without mutating relay data."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen


def admin_revision(assets: Path) -> str:
    shell = (assets / "admin.html").read_text(encoding="utf-8")
    for token, name in (("__ADMIN_CSS__", "admin.css"), ("__ADMIN_JS__", "admin.js")):
        shell = shell.replace(token, (assets / name).read_text(encoding="utf-8"))
    return hashlib.sha256(shell.encode()).hexdigest()[:12]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("--host-header", default="")
    parser.add_argument("--expected-admin-revision", default="")
    parser.add_argument("--assets", type=Path, default=Path(__file__).resolve().parents[1] / "relay" / "admin")
    args = parser.parse_args()
    password = os.environ.get("RELAY_ADMIN_PASSWORD", "")
    if not password:
        parser.error("RELAY_ADMIN_PASSWORD must be supplied through the environment")
    expected = args.expected_admin_revision or admin_revision(args.assets)
    credentials = base64.b64encode(f"operator:{password}".encode()).decode()
    headers = {"Authorization": f"Basic {credentials}", "Accept": "application/json"}
    if args.host_header:
        headers["Host"] = args.host_header
    paths = ["/admin"] + [
        f"/admin/api/{name}" for name in
        ("overview", "fleet", "usage", "schedules", "surfaces", "reports", "activations", "retention", "access")
    ]
    for path in paths:
        request = Request(args.base_url.rstrip("/") + path, headers=headers)
        with urlopen(request, timeout=20) as response:
            body = response.read()
            if response.status != 200:
                raise SystemExit(f"Operator route failed: {path}")
            if response.headers.get("Cache-Control") != "no-store":
                raise SystemExit(f"Operator route can be cached: {path}")
            if response.headers.get("X-LocalFlight-Admin-Revision") != expected:
                raise SystemExit(f"Operator source revision mismatch: {path}")
            if path == "/admin":
                if b'content="network-ops-v2"' not in body or b"Command center" not in body:
                    raise SystemExit("The redesigned operator shell is missing")
            elif not isinstance(json.loads(body), dict):
                raise SystemExit(f"Operator route returned an invalid response: {path}")
        print(f"PASS {path}")
    print("Operator shell revision and all read routes verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
