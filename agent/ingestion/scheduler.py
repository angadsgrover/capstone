"""
APScheduler-based ingestion scheduler.

Runs inside the agent container as an asyncio background task:
  - METAR every 30 minutes
  - TAF   every 60 minutes

Usage (called once during FastAPI lifespan startup):
    from ingestion.scheduler import setup_scheduler
    scheduler = setup_scheduler(db)

    # In shutdown:
    scheduler.shutdown(wait=False)
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


def setup_scheduler(db) -> AsyncIOScheduler:
    """
    Create, configure, and start the AsyncIOScheduler.

    Each job is wrapped in try/except so a single failure doesn't stop
    the scheduler.
    """
    from ingestion.metar_ingestor import ingest_metar
    from ingestion.taf_ingestor   import ingest_taf

    scheduler = AsyncIOScheduler()

    async def _run_metar():
        try:
            n = await ingest_metar(db)
            logger.debug("Scheduled METAR run: %d new rows.", n)
        except Exception as e:
            logger.warning("Scheduled METAR job failed: %s", e)

    async def _run_taf():
        try:
            n = await ingest_taf(db)
            logger.debug("Scheduled TAF run: %d new rows.", n)
        except Exception as e:
            logger.warning("Scheduled TAF job failed: %s", e)

    scheduler.add_job(
        _run_metar,
        trigger=IntervalTrigger(minutes=30),
        id="metar_ingestion",
        replace_existing=True,
        # Run immediately on first start so the DB has data right away
        next_run_time=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ),
    )
    scheduler.add_job(
        _run_taf,
        trigger=IntervalTrigger(minutes=60),
        id="taf_ingestion",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Ingestion scheduler started (METAR: 30min, TAF: 60min).")
    return scheduler
