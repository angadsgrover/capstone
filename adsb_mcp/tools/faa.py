"""FAA aircraft registration tools.

Provides 4 tools wrapping the FAA Aircraft Registry web scraper:
  - batch_lookup_faa    : look up and cache a list of N-numbers
  - create_or_update_faa: upsert a registration record
  - get_faa_entry       : retrieve a record from cache
  - delete_faa_entry    : remove a record from cache

Data is scraped from https://registry.faa.gov and stored in the local
SQLite *faa_reg* table to avoid repeatedly hitting the FAA website.
"""

from __future__ import annotations

import os
import re
import ssl
import sys
import time
import random
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import setup_aircraft_db

# Disable certificate verification for the FAA registry (matches original behaviour)
ssl._create_default_https_context = ssl._create_unverified_context

_FAA_BASE_URL = "https://registry.faa.gov/AircraftInquiry/Search/NNumberResult"
_FAA_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
}


# ---------------------------------------------------------------------------
# Scraping helpers (synchronous – FAA site requires cookies / session)
# ---------------------------------------------------------------------------

def _scrape_faa(n_number: str, max_retries: int = 3) -> dict[str, Any] | None:
    """Fetch and parse FAA registration data for *n_number*.

    Returns a dict of field→value pairs extracted from the HTML tables,
    or None if the aircraft could not be found or an error occurred.
    """
    url = f"{_FAA_BASE_URL}?nNumberTxt={quote(n_number)}"

    for attempt in range(max_retries):
        if attempt > 0:
            time.sleep(2 + random.random())
        try:
            req = Request(url, headers=_FAA_HEADERS)
            response = urlopen(req)
            if response.getcode() != 200:
                continue
            html = response.read().decode("utf-8")
            return _parse_faa_html(html, n_number)
        except (HTTPError, URLError):
            if attempt == max_retries - 1:
                return None
        except Exception:
            if attempt == max_retries - 1:
                return None
    return None


def _parse_faa_html(html: str, n_number: str) -> dict[str, Any] | None:
    """Extract key→value pairs from FAA registry HTML."""
    soup = BeautifulSoup(html, "html.parser")
    if soup.find(string=re.compile("No aircraft found")):
        return None

    tables = soup.find_all("table", class_="devkit-table")
    if not tables:
        return None

    data: dict[str, Any] = {"n_number": n_number}
    for table in tables:
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) == 2:
                key = cells[0].text.strip().rstrip(":").lower().replace(" ", "_")
                data[key] = cells[1].text.strip()
            elif len(cells) == 4:
                for ki, vi in ((0, 1), (2, 3)):
                    key = cells[ki].text.strip().rstrip(":").lower().replace(" ", "_")
                    data[key] = cells[vi].text.strip()

    data = {k: v for k, v in data.items() if v and v != "None" and v.strip()}
    return data if len(data) > 1 else None


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _save_faa(conn, aircraft_data: dict[str, Any]) -> bool:
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(faa_reg)")
    valid_cols = {row[1] for row in cursor.fetchall()}
    filtered = {k: v for k, v in aircraft_data.items() if k in valid_cols}
    cols = ", ".join(filtered.keys())
    placeholders = ", ".join(["?"] * len(filtered))
    try:
        cursor.execute(
            f"INSERT OR REPLACE INTO faa_reg ({cols}) VALUES ({placeholders})",
            list(filtered.values()),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False


def _get_faa(conn, n_number: str) -> dict[str, Any] | None:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM faa_reg WHERE n_number = ?", (n_number,))
    row = cursor.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, row))


def _delete_faa(conn, n_number: str) -> bool:
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM faa_reg WHERE n_number = ?", (n_number,))
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        conn.rollback()
        return False


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register(mcp: FastMCP) -> None:
    """Attach all FAA registry tools to *mcp*."""

    @mcp.tool(
        description=(
            "Fetches FAA registration data for one or more aircraft N-Numbers "
            "by scraping the FAA Aircraft Registry and saves results to the local "
            "database. Returns a summary of successes and failures."
        )
    )
    def batch_lookup_faa(
        n_numbers: list[str],
        db_path: str = "aircraft.db",
    ) -> str:
        """
        Args:
            n_numbers: List of US aircraft N-Numbers to look up (e.g. ['N12345', 'N98765']).
            db_path:   Path to the SQLite database file.
        """
        conn = setup_aircraft_db(db_path)
        success, fail = 0, 0
        for n in n_numbers:
            aircraft_data = _scrape_faa(n)
            if aircraft_data and _save_faa(conn, aircraft_data):
                success += 1
            else:
                fail += 1
        conn.close()
        return f"FAA lookup complete. Saved: {success}, Failed: {fail}."

    @mcp.tool(
        description=(
            "Creates or updates an FAA registration entry in the local database. "
            "Useful for manually adding or correcting registration data. "
            "The aircraft_data dict must include 'n_number' as the primary key."
        )
    )
    def create_or_update_faa(
        aircraft_data: dict[str, Any],
        db_path: str = "aircraft.db",
    ) -> str:
        """
        Args:
            aircraft_data: Dict of FAA registration fields. Must include 'n_number'.
            db_path:       Path to the SQLite database file.
        """
        if not aircraft_data or "n_number" not in aircraft_data:
            return "Error: aircraft_data must include 'n_number'."
        conn = setup_aircraft_db(db_path)
        ok = _save_faa(conn, aircraft_data)
        conn.close()
        n = aircraft_data["n_number"]
        return (
            f"Successfully saved FAA entry for {n}."
            if ok
            else f"Failed to save FAA entry for {n}."
        )

    @mcp.tool(
        description=(
            "Retrieves a cached FAA registration entry for the given N-Number "
            "from the local database. Returns all registration fields or a "
            "not-found message if the aircraft has not been looked up yet."
        )
    )
    def get_faa_entry(
        n_number: str,
        db_path: str = "aircraft.db",
    ) -> dict[str, Any] | str:
        """
        Args:
            n_number: US aircraft N-Number (e.g. 'N12345').
            db_path:  Path to the SQLite database file.
        """
        conn = setup_aircraft_db(db_path)
        data = _get_faa(conn, n_number)
        conn.close()
        return data if data else f"No FAA entry found for N-Number: {n_number}"

    @mcp.tool(
        description=(
            "Deletes a cached FAA registration entry for the given N-Number "
            "from the local database."
        )
    )
    def delete_faa_entry(
        n_number: str,
        db_path: str = "aircraft.db",
    ) -> str:
        """
        Args:
            n_number: US aircraft N-Number to remove (e.g. 'N12345').
            db_path:  Path to the SQLite database file.
        """
        conn = setup_aircraft_db(db_path)
        ok = _delete_faa(conn, n_number)
        conn.close()
        return (
            f"Deleted FAA entry for {n_number}."
            if ok
            else f"No FAA entry found for {n_number}."
        )
