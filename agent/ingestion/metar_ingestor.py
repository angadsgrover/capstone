"""
METAR ingestor — fetches and stores historical METAR observations from
aviationweather.gov (free, no API key required).

Endpoint: https://aviationweather.gov/api/data/metar
          ?ids=VHHH,EGLL,KJFK&format=json&hours=2
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from ingestion.embedder import embed_and_store

logger = logging.getLogger(__name__)

AVWX_METAR_URL = "https://aviationweather.gov/api/data/metar"

# Airports polled by the scheduler.  Can be overridden via METAR_ICAO_LIST env var.
DEFAULT_ICAO_LIST = [
    "VHHH",  # Hong Kong
    "EGLL",  # London Heathrow
    "KJFK",  # New York JFK
    "WSSS",  # Singapore Changi
    "OMDB",  # Dubai
    "RJTT",  # Tokyo Haneda
    "YSSY",  # Sydney
    "LFPG",  # Paris CDG
]


def _parse_obs_time(raw: dict) -> datetime | None:
    ts = raw.get("obsTime") or raw.get("receiptTime")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


async def ingest_metar(db, icao_list: list[str] | None = None, hours: int = 2) -> int:
    """
    Fetch METARs for *icao_list* (or DEFAULT_ICAO_LIST) and upsert them into
    metar_history + embeddings.  Returns the number of new rows inserted.
    """
    if not db.available:
        return 0

    ids = ",".join(icao_list or DEFAULT_ICAO_LIST)
    inserted = 0

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                AVWX_METAR_URL,
                params={"ids": ids, "format": "json", "hours": hours},
            )
            resp.raise_for_status()
            records: list[dict] = resp.json()
    except Exception as e:
        logger.warning("METAR fetch failed: %s", e)
        return 0

    for r in records:
        raw_text = r.get("rawOb") or r.get("raw", "")
        icao     = (r.get("stationId") or r.get("icaoId") or "")[:4].upper()
        if not raw_text or not icao:
            continue

        obs_time = _parse_obs_time(r)
        if obs_time is None:
            obs_time = datetime.now(timezone.utc)

        try:
            row_id = await db._pool.fetchval(  # type: ignore[union-attr]
                """
                INSERT INTO metar_history
                    (icao, raw_text, obs_time, flight_cat,
                     temp_c, dewpoint_c, wind_dir, wind_speed_kt, wind_gust_kt,
                     visibility_sm, ceiling_ft, altimeter, wx_string)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                ON CONFLICT (icao, obs_time) DO NOTHING
                RETURNING id
                """,
                icao,
                raw_text,
                obs_time,
                r.get("flightCategory") or r.get("fltcat"),
                r.get("temp"),
                r.get("dewp"),
                r.get("wdir"),
                r.get("wspd"),
                r.get("wgst"),
                r.get("visib"),
                r.get("ceil"),
                r.get("altim"),
                r.get("wxString"),
            )
            if row_id:
                await embed_and_store(
                    db,
                    source_type="metar",
                    content=raw_text,
                    source_id=row_id,
                    metadata={"icao": icao, "obs_time": obs_time.isoformat()},
                )
                inserted += 1
        except Exception as e:
            logger.debug("METAR insert error for %s: %s", icao, e)

    if inserted:
        logger.info("METAR ingestor: inserted %d new observations.", inserted)
    return inserted
