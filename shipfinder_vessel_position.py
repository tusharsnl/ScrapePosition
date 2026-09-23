"""ShipFinder vessel position tracker.

Given a vessel name (e.g. "WAN HAI 517"), this script:
  1. Loads https://www.shipfinder.com/
  2. Types the vessel name into the search box and picks the first
     autocomplete result.
  3. Reads the "Coastal AIS" info panel that appears (MMSI, Lat, Lon,
     Speed, Course, Status, Destination, ETA, Last Update, etc.).
  4. Appends a row with a timestamp + lat/lon (+ the other fields) to a
     CSV file, creating it with a header the first time it's run.

Designed to be run on a schedule (e.g. hourly via cron) so the CSV builds
up a position history for the vessel over time.

Usage:
    python shipfinder_vessel_position.py "WAN HAI 517"
    python shipfinder_vessel_position.py "WAN HAI 517" --output wan_hai_517_positions.csv
    python shipfinder_vessel_position.py "WAN HAI 517" --headless
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_URL = "https://www.shipfinder.com/"

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


class ShipFinderError(Exception):
    """Raised when a vessel's position cannot be retrieved from ShipFinder."""


def dms_to_decimal(coord: Optional[str]) -> Optional[float]:
    """Convert ShipFinder's "degrees-decimal minutes" coordinate strings
    (e.g. "1-16.954N", "103-45.732E") to signed decimal degrees
    (e.g. 1.28257, 103.7622). South and West are negative.

    Returns None if `coord` doesn't match the expected pattern.
    """
    if not coord:
        return None
    match = re.match(r"^(\d+)-(\d+(?:\.\d+)?)([NSEW])$", coord.strip())
    if not match:
        return None
    degrees, minutes, hemisphere = match.groups()
    decimal = int(degrees) + float(minutes) / 60
    if hemisphere in ("S", "W"):
        decimal = -decimal
    return round(decimal, 6)


@dataclass
class VesselPosition:
    vessel_name: str
    mmsi: Optional[str] = None
    imo: Optional[str] = None
    call_sign: Optional[str] = None
    ship_type: Optional[str] = None
    status: Optional[str] = None
    latitude: Optional[str] = None
    longitude: Optional[str] = None
    speed_kn: Optional[str] = None
    course_deg: Optional[str] = None
    heading_deg: Optional[str] = None
    destination: Optional[str] = None
    eta: Optional[str] = None
    last_update: Optional[str] = None

    def as_csv_row(self) -> dict[str, str]:
        lat_decimal = dms_to_decimal(self.latitude)
        lon_decimal = dms_to_decimal(self.longitude)
        return {
            "captured_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "vessel_name": self.vessel_name,
            "mmsi": self.mmsi or "",
            "imo": self.imo or "",
            "call_sign": self.call_sign or "",
            "ship_type": self.ship_type or "",
            "status": self.status or "",
            "latitude": self.latitude or "",
            "longitude": self.longitude or "",
            "latitude_decimal": lat_decimal if lat_decimal is not None else "",
            "longitude_decimal": lon_decimal if lon_decimal is not None else "",
            "speed_kn": self.speed_kn or "",
            "course_deg": self.course_deg or "",
            "heading_deg": self.heading_deg or "",
            "destination": self.destination or "",
            "eta": self.eta or "",
            "last_update": self.last_update or "",
        }


_LABEL_MAP = {
    "MMSI": "mmsi",
    "IMO": "imo",
    "Call Sign": "call_sign",
    "Type": "ship_type",
    "Status": "status",
    "Lat": "latitude",
    "Lon": "longitude",
    "Speed": "speed_kn",
    "Course": "course_deg",
    "Heading": "heading_deg",
    "Dest": "destination",
    "ETA": "eta",
    "Last Update": "last_update",
}


def _parse_ais_table(raw_rows: list[str]) -> dict[str, str]:
    """Parse the Coastal AIS info panel's table rows into a flat dict.

    Each row looks like: "MMSI：\t566942000\tHeading：\t121.0Deg"
    (two label/value pairs per row, tab-separated, full-width colon).
    """
    parsed: dict[str, str] = {}
    for row in raw_rows:
        cells = [c.strip() for c in row.split("\t") if c.strip()]
        # cells look like ["MMSI：", "566942000", "Heading：", "121.0Deg"]
        for i in range(0, len(cells) - 1, 2):
            label = cells[i].rstrip("：:").strip()
            value = cells[i + 1].strip()
            key = _LABEL_MAP.get(label)
            if key:
                parsed[key] = value
    return parsed


def get_vessel_position(
    vessel_name: str,
    headless: bool = True,
    timeout_ms: int = 30000,
    result_type: str = "Cargo ship",
) -> VesselPosition:
    """Search ShipFinder for `vessel_name`, close the welcome popup, open the
    search result matching `result_type` (default: "Cargo ship"), and read
    its current position from the Coastal AIS info panel."""
    vessel_name = vessel_name.strip()
    if not vessel_name:
        raise ShipFinderError("Vessel name must not be empty.")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        )
        page = context.new_page()
        try:
            page.goto(BASE_URL, timeout=timeout_ms, wait_until="domcontentloaded")

            # Dismiss the "Welcome" / promo modal that appears on every page
            # load before interacting with the search box.
            try:
                page.locator("button.modal-close").or_(page.locator("text=✕")).first.click(
                    timeout=3000
                )
            except Exception:
                pass
            page.wait_for_timeout(500)

            search_box = page.locator("#txtKey")
            search_box.wait_for(state="visible", timeout=timeout_ms)
            search_box.fill(vessel_name)

            results = page.locator("ul li a")
            try:
                results.first.wait_for(state="visible", timeout=timeout_ms)
            except PlaywrightTimeoutError as exc:
                raise ShipFinderError(
                    f"No search results found for vessel '{vessel_name}'."
                ) from exc

            # ShipFinder returns multiple AIS records for the same vessel
            # (e.g. one tagged "Container", one tagged "Cargo ship"). Select
            # the result whose label matches `result_type` (default:
            # "Cargo ship", per the requested search flow).
            target_result = page.locator("ul li a", has_text=result_type).first
            if target_result.count() == 0:
                target_result = results.first
            target_result.click(force=True)

            # Wait for the Coastal AIS info panel's table to render. This
            # table lives inside a link to /ship/detail/mmsi/<mmsi> — using
            # that scopes us away from the page's other (hidden) tables,
            # such as the unrelated "Port Call" history table. The panel
            # can take a moment to populate and its visibility can be
            # briefly inconsistent, so poll for the "Lat" cell's text
            # rather than relying purely on a single visibility check.
            deadline = time.monotonic() + (timeout_ms / 1000)
            raw_rows: list[str] = []
            while time.monotonic() < deadline:
                raw_rows = page.evaluate(
                    """
                    () => {
                        const table = document.querySelector('#shipAIS');
                        if (!table) return [];
                        return Array.from(table.querySelectorAll('tr')).map(tr => tr.innerText);
                    }
                    """
                )
                if any("Lat" in row for row in raw_rows):
                    break
                page.wait_for_timeout(500)

            fields = _parse_ais_table(raw_rows)
            if not fields.get("latitude") or not fields.get("longitude"):
                raise ShipFinderError(
                    f"Could not read latitude/longitude for vessel '{vessel_name}'."
                )

            return VesselPosition(vessel_name=vessel_name, **fields)

        finally:
            context.close()
            browser.close()


def append_to_csv(position: VesselPosition, csv_path: str) -> None:
    """Append a position row to `csv_path`, creating it with a header if it
    doesn't already exist."""
    file_exists = os.path.isfile(csv_path)
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(position.as_csv_row())


def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Capture a vessel's current position from ShipFinder and append it to a CSV file."
    )
    parser.add_argument("vessel_name", help='Vessel name or IMO number, e.g. "WAN HAI 517" or "9400186"')
    parser.add_argument(
        "--output",
        default="vessel_positions.csv",
        help="CSV file to append to (created if it doesn't exist). Default: vessel_positions.csv",
    )
    parser.add_argument("--headless", action="store_true", default=True, help="Run headless (default).")
    parser.add_argument("--no-headless", dest="headless", action="store_false", help="Run with a visible browser.")
    parser.add_argument(
        "--result-type",
        default="Cargo ship",
        help='Which labeled search result to open, e.g. "Cargo ship" (default) or "Container".',
    )
    args = parser.parse_args()

    try:
        position = get_vessel_position(
            args.vessel_name, headless=args.headless, result_type=args.result_type
        )
    except ShipFinderError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    append_to_csv(position, args.output)
    row = position.as_csv_row()
    print(
        f"[{row['captured_at_utc']}] {position.vessel_name}: "
        f"lat={position.latitude} ({row['latitude_decimal']}), "
        f"lon={position.longitude} ({row['longitude_decimal']}) -> appended to {args.output}"
    )


if __name__ == "__main__":
    _cli()
