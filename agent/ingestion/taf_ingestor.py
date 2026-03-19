"""
TAF ingestor — fetches and stores Terminal Aerodrome Forecasts from
aviationweather.gov.

Endpoint: https://aviationweather.gov/api/data/taf
          ?ids=VHHH,EGLL&format=json
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from ingestion.embedder import embed_and_store

logger = logging.getLogger(__name__)

AVWX_TAF_URL = "https://aviationweather.gov/api/data/taf"

# Reuse the same airport list as the METAR ingestor.
from ingestion.metar_ingestor import DEFAULT_ICAO_LIST


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


async def ingest_taf(db, icao_list: list[str] | None = None) -> int:
    """
    Fetch TAFs for *icao_list* and upsert into taf_history + embeddings.
    Returns the number of new rows inserted.
    """
    if not db.available:
        return 0

    ids = ",".join(icao_list or DEFAULT_ICAO_LIST)
    inserted = 0

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                AVWX_TAF_URL,
                params={"ids": ids, "format": "json"},
            )
            resp.raise_for_status()
            records: list[dict] = resp.json()
    except Exception as e:
        logger.warning("TAF fetch failed: %s", e)
        return 0

    for r in records:
        raw_text = r.get("rawTAF") or r.get("raw", "")
        icao     = (r.get("stationId") or r.get("icaoId") or "")[:4].upper()
        if not raw_text or not icao:
            continue

        issue_time = _parse_dt(r.get("issueTime")) or datetime.now(timezone.utc)
        valid_from = _parse_dt(r.get("validTimeFrom"))
        valid_to   = _parse_dt(r.get("validTimeTo"))

        try:
            row_id = await db._pool.fetchval(  # type: ignore[union-attr]
                """
                INSERT INTO taf_history (icao, raw_text, issue_time, valid_from, valid_to)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                icao, raw_text, issue_time, valid_from, valid_to,
            )
            if row_id:
                await embed_and_store(
                    db,
                    source_type="taf",
                    content=raw_text,
                    source_id=row_id,
                    metadata={
                        "icao":       icao,
                        "issue_time": issue_time.isoformat(),
                        "valid_from": valid_from.isoformat() if valid_from else None,
                        "valid_to":   valid_to.isoformat()   if valid_to   else None,
                    },
                )
                inserted += 1
        except Exception as e:
            logger.debug("TAF insert error for %s: %s", icao, e)

    if inserted:
        logger.info("TAF ingestor: inserted %d new forecasts.", inserted)
    return inserted
