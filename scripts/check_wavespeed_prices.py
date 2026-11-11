"""Compare the Wavespeed catalog prices with what Wavespeed billed (COREPRODUC-595).

Run it before a release that changes the Wavespeed catalog or plugin. It reads Wavespeed's
usage report (``POST /api/v3/user/usage_stats``, free) for the account of ``WAVESPEED_API_KEY``.
For each route that was called, it puts Wavespeed's rate (``unit_price``) next to the catalog
rows that call that route. The report shows the basis: a call billed as one unit is billed per
clip or picture, so a row matches when its amount is the rate; a call billed as several units is
billed by the second, so a row matches when its amount is the rate times the seconds in its unit
(``video_5s``: 5). A route that no row matches is marked ``CHECK``: read its API page before
you change a row.

The report counts the whole account (other apps too) by day, and it lags an hour or more, so a
fixed row shows ``CHECK`` until the older calls leave the window.

Usage:
    WAVESPEED_API_KEY=... python3 scripts/check_wavespeed_prices.py [--days 31]

Exit code 1 when a route needs a check, 2 when the report cannot be read.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "packages/core/vinci_core/catalogs/wavespeed.json"
REPORT = "https://api.wavespeed.ai/api/v3/user/usage_stats"


# Routes the plugin adds to a row's endpoint: Seedream edits and InfiniteTalk's video input.
EXTRA = {"bytedance/seedream-v4.5": "/edit", "wavespeed-ai/infinitetalk": "/video-to-video"}


def routes_of(endpoint: str) -> list[str]:
    """The routes a catalog endpoint can bill: the plugin sends a still to the image route."""
    routes = [endpoint]
    if "/text-to-video" in endpoint:
        routes.append(endpoint.replace("/text-to-video", "/image-to-video", 1))
    if endpoint in EXTRA:
        routes.append(endpoint + EXTRA[endpoint])
    return routes


def matches(rate: float, per_call: float, amount: float, unit: str) -> bool:
    """True when the amount is the bill: per clip if a call cost one unit, else per second."""
    seconds = re.match(r"video_(\d+)s", unit)
    by_second = seconds is not None and per_call > 1.5 * rate  # a call billed several units
    price = amount / int(seconds.group(1)) if seconds and by_second else amount
    return abs(rate - price) <= max(0.001, 0.02 * price)


def main() -> int:
    """Print the billed rate and the catalog price of each called route.

    Returns:
        0 when a row matches every called route, 1 when a route needs a check, 2 when the
        report cannot be read.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=31, help="report window in days (default 31)")
    args = parser.parse_args()
    key = os.environ.get("WAVESPEED_API_KEY", "").strip()
    if not key:
        print("set WAVESPEED_API_KEY (the key is never printed)", file=sys.stderr)
        return 2
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    rows: dict[str, list[dict]] = {}
    for row in catalog["models"]:
        for route in routes_of(catalog["endpoints"].get(row["id"], "")):
            rows.setdefault(route, []).append(row)
    end = datetime.now(tz=UTC)
    start = end - timedelta(days=args.days)
    window = {"start_time": start.isoformat(), "end_time": end.isoformat()}
    request = urllib.request.Request(
        REPORT,
        data=json.dumps(window).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            report = json.load(response)
    except (urllib.error.URLError, ValueError) as exc:  # HTTPError is a URLError
        print(f"usage report failed: {exc}", file=sys.stderr)
        return 2
    data = report.get("data") if isinstance(report, dict) else None
    usage = data.get("per_model_usage") if isinstance(data, dict) else None
    if not isinstance(usage, list) or report.get("code", 200) != 200:
        print("usage report has no per_model_usage list: nothing was checked", file=sys.stderr)
        return 2
    checks = 0
    print(f"Wavespeed usage, last {args.days} days, against {CATALOG.name}")
    for item in sorted(usage, key=lambda u: str(u.get("model_uuid"))):
        route, rate = str(item.get("model_uuid") or ""), float(item.get("unit_price") or 0)
        count = int(item.get("total_count") or 0)
        per_call = float(item.get("total_cost") or 0) / max(count, 1)
        billed = f"{count} calls, rate ${rate:.3f}, ${per_call:.3f} a call"
        listed = rows.get(route)
        if not listed:
            print(f"  -      {route}: {billed}; not in the catalog")
            continue
        ok = any(
            matches(rate, per_call, r["pricing"]["amount"], r["pricing"]["unit"]) for r in listed
        )
        checks += not ok
        prices = ", ".join(
            f"{r['id']} ${r['pricing']['amount']:.3f}/{r['pricing']['unit']}" for r in listed
        )
        print(f"  {'ok   ' if ok else 'CHECK'}  {route}: {billed}; catalog {prices}")
    print(f"{checks} route(s) to check" if checks else "a row matches every called route")
    return 1 if checks else 0


if __name__ == "__main__":
    sys.exit(main())
