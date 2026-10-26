"""Synchronize scraper CSV data with the OrangeTechShippingWeb endpoint."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

CSV_FIELDS = [
    "captured_at_utc",
    "vessel_name",
    "mmsi",
    "imo",
    "call_sign",
    "ship_type",
    "status",
    "latitude",
    "longitude",
    "latitude_decimal",
    "longitude_decimal",
    "speed_kn",
    "course_deg",
    "heading_deg",
    "destination",
    "eta",
    "last_update",
]
MAX_POSITIONS_PER_REQUEST = 500


def _configuration() -> tuple[str, str]:
    base_url = os.environ.get("VESSEL_SYNC_API_URL", "").strip()
    api_key = os.environ.get("VESSEL_SYNC_API_KEY", "").strip()
    if not base_url or not api_key:
        raise RuntimeError("Set VESSEL_SYNC_API_URL and VESSEL_SYNC_API_KEY.")

    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("VESSEL_SYNC_API_URL must be an HTTPS URL.")
    return base_url, api_key


def _url_with_action(base_url: str, action: str) -> str:
    parsed = urlsplit(base_url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("action", action))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _request(url: str, api_key: str, data: bytes | None = None) -> bytes:
    headers = {"X-Vessel-Sync-Key": api_key}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urlopen(request, timeout=45) as response:
            return response.read()
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Sync endpoint returned HTTP {error.code}: {body}") from error
    except URLError as error:
        raise RuntimeError(f"Could not reach the vessel sync endpoint: {error.reason}") from error


def _read_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or not set(CSV_FIELDS).issubset(reader.fieldnames):
            raise RuntimeError(f"{csv_path} does not contain the expected vessel CSV columns.")
        return [
            {field: (row.get(field) or "").strip() for field in CSV_FIELDS}
            for row in reader
        ]


def _row_key(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(row[field] for field in CSV_FIELDS)


def fetch_vessels() -> int:
    base_url, api_key = _configuration()
    payload = json.loads(_request(_url_with_action(base_url, "vessels"), api_key))
    vessels = payload.get("vessels") if isinstance(payload, dict) else None
    if not isinstance(vessels, list) or any(
        not isinstance(vessel, str) or not vessel.strip() for vessel in vessels
    ):
        raise RuntimeError("The sync endpoint returned an invalid vessel list.")
    for vessel in vessels:
        print(vessel.strip())
    return len(vessels)


def post_new_positions(before_path: Path, current_path: Path) -> int:
    base_url, api_key = _configuration()
    previous = Counter(_row_key(row) for row in _read_rows(before_path))
    added: list[dict[str, str]] = []
    for row in _read_rows(current_path):
        key = _row_key(row)
        if previous[key]:
            previous[key] -= 1
        else:
            added.append(row)

    for offset in range(0, len(added), MAX_POSITIONS_PER_REQUEST):
        batch = added[offset : offset + MAX_POSITIONS_PER_REQUEST]
        data = json.dumps({"positions": batch}, separators=(",", ":")).encode("utf-8")
        result = json.loads(_request(base_url, api_key, data))
        if not isinstance(result, dict) or result.get("received") != len(batch):
            raise RuntimeError("The sync endpoint did not confirm the complete position batch.")
        print(
            f"Position batch accepted: {result.get('inserted', 0)} inserted, "
            f"{result.get('duplicates', 0)} duplicates."
        )

    print(f"Posted {len(added)} newly generated position row(s).")
    return len(added)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("vessels", help="Print currently required vessels, one per line.")
    post_parser = subparsers.add_parser("post-new", help="POST rows appended since a CSV snapshot.")
    post_parser.add_argument("--before", type=Path, required=True)
    post_parser.add_argument("--current", type=Path, default=Path("vessel_positions.csv"))
    args = parser.parse_args()

    try:
        if args.command == "vessels":
            fetch_vessels()
        else:
            post_new_positions(args.before, args.current)
    except (RuntimeError, json.JSONDecodeError, OSError) as error:
        print(f"Vessel synchronization failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
