#!/usr/bin/env python3
"""
Sync and incrementally ingest HKO archive datasets from authenticated directory listing.

Designed for large historical datasets on a new drive:
- Downloads only missing files (stateful)
- Supports METAR / TAF / SPECI / ADS_B categories
- Optional embedding ingest into pgvector for agent RAG reference/benchmarking

Credentials are read from environment variables:
  HKO_ARCHIVE_USER
  HKO_ARCHIVE_PASS

Example:
  python scripts/hko_archive_sync_ingest.py \
    --base-url https://avrdp.hko.gov.hk/Polyu_Hkyaa/August_2025/ \
    --target-dir /Volumes/Angad-SSD/hko-data/August_2025 \
    --download-categories METAR,TAF,SPECI \
    --ingest-categories METAR,TAF,SPECI \
    --ingest-limit 500
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
import re
from urllib.parse import urlparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set

import httpx
from dotenv import load_dotenv

# Allow running from repo root without installing as a package.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from db import Database  # type: ignore
from ingestion.embedder import embed_and_store  # type: ignore

LINK_RE = re.compile(r'href="([^"]+)"', re.IGNORECASE)
TS_RE = re.compile(r"_(\d{14})\.xml\.gz$", re.IGNORECASE)
ICAO_RE = re.compile(r"_C_([A-Z0-9]{4})_", re.IGNORECASE)

DEFAULT_DOWNLOAD_CATEGORIES = ["METAR", "TAF", "SPECI"]
DEFAULT_INGEST_CATEGORIES = ["METAR", "TAF", "SPECI"]


@dataclass
class SyncConfig:
    base_url: str
    target_dir: Path
    user: str
    password: str
    download_categories: List[str]
    ingest_categories: List[str]
    ingest_limit: int
    skip_download: bool
    skip_ingest: bool


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.data: Dict[str, object] = {
            "downloaded": {},
            "ingested": {},
            "updated_at": None,
        }
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass

    def downloaded(self) -> Dict[str, Dict[str, object]]:
        return self.data.setdefault("downloaded", {})  # type: ignore[return-value]

    def ingested(self) -> Dict[str, Dict[str, object]]:
        return self.data.setdefault("ingested", {})  # type: ignore[return-value]

    def mark_downloaded(self, rel_path: str, size: int):
        self.downloaded()[rel_path] = {
            "size": size,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }

    def mark_ingested(self, rel_path: str, source_type: str):
        self.ingested()[rel_path] = {
            "source_type": source_type,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }

    def is_downloaded(self, rel_path: str, size: int | None = None) -> bool:
        item = self.downloaded().get(rel_path)
        if not item:
            return False
        if size is None:
            return True
        try:
            return int(item.get("size", -1)) == int(size)
        except Exception:
            return False

    def is_ingested(self, rel_path: str) -> bool:
        return rel_path in self.ingested()

    def save(self):
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")


def normalize_categories(raw: str, allowed: Set[str]) -> List[str]:
    vals = [x.strip().upper() for x in raw.split(",") if x.strip()]
    bad = [x for x in vals if x not in allowed]
    if bad:
        raise ValueError(f"Invalid categories: {', '.join(bad)}")
    return vals


def parse_obs_time_from_name(name: str) -> str | None:
    m = TS_RE.search(name)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return None


def parse_icao_from_name(name: str) -> str | None:
    m = ICAO_RE.search(name)
    if not m:
        return None
    return m.group(1).upper()


async def fetch_links(client: httpx.AsyncClient, url: str) -> List[str]:
    resp = await client.get(url, timeout=30)
    resp.raise_for_status()
    links = []
    for href in LINK_RE.findall(resp.text):
        if href in ("../", "./"):
            continue
        if href.startswith("?"):
            continue
        links.append(href)
    return links


async def download_file(client: httpx.AsyncClient, url: str, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    async with client.stream("GET", url, timeout=120) as resp:
        resp.raise_for_status()
        with target.open("wb") as f:
            async for chunk in resp.aiter_bytes():
                f.write(chunk)


async def sync_category(
    client: httpx.AsyncClient,
    cfg: SyncConfig,
    state: StateStore,
    category: str,
) -> int:
    category_url = cfg.base_url.rstrip("/") + f"/{category}/"
    links = await fetch_links(client, category_url)

    downloaded_count = 0
    for link in links:
        if not (link.endswith(".xml.gz") or link.endswith(".zip")):
            continue

        file_url = category_url + link
        rel = f"{category}/{link}"
        target = cfg.target_dir / rel

        if target.exists() and state.is_downloaded(rel, target.stat().st_size):
            continue

        await download_file(client, file_url, target)
        state.mark_downloaded(rel, target.stat().st_size)
        downloaded_count += 1

    return downloaded_count


async def ingest_files(cfg: SyncConfig, state: StateStore) -> int:
    db = Database()
    try:
        await db.connect()
    except Exception as exc:
        msg = str(exc)
        if "role" in msg and "does not exist" in msg:
            dsn = os.getenv("POSTGRES_DSN", "")
            dsn_user = "<unknown>"
            if dsn:
                try:
                    parsed = urlparse(dsn)
                    if parsed.username:
                        dsn_user = parsed.username
                except Exception:
                    pass

            raise RuntimeError(
                "PostgreSQL user from POSTGRES_DSN does not exist. "
                f"Detected DSN user: {dsn_user}.\n\n"
                "Fix options:\n"
                "1) Update POSTGRES_DSN in .env to an existing DB user.\n"
                "2) Or create the missing role/database inside the running postgres container:\n"
                "   docker compose -f docker-compose.yml -f docker-compose.local-infra.yml exec -T postgres psql -U postgres -d postgres -c \"CREATE ROLE capstone WITH LOGIN PASSWORD 'your_password';\"\n"
                "   docker compose -f docker-compose.yml -f docker-compose.local-infra.yml exec -T postgres psql -U postgres -d postgres -c \"CREATE DATABASE capstone OWNER capstone;\"\n"
                "   docker compose -f docker-compose.yml -f docker-compose.local-infra.yml exec -T postgres psql -U postgres -d capstone < infra/init.sql\n"
                "3) If this is disposable local data, reset infra volume and restart with --with-infra."
            ) from exc
        raise

    if not db.available:
        raise RuntimeError("POSTGRES_DSN is not configured or DB is unavailable; cannot ingest embeddings.")

    total = 0
    per_category_limit = max(1, cfg.ingest_limit)

    source_type_map = {
        "METAR": "metar",
        "SPECI": "metar",  # keep searchable with metar source filter
        "TAF": "taf",
    }

    try:
        for category in cfg.ingest_categories:
            source_type = source_type_map.get(category, category.lower())
            files = sorted((cfg.target_dir / category).glob("*.xml.gz"))
            count = 0
            attempts = 0
            failed = 0

            for file_path in files:
                if attempts >= per_category_limit:
                    break

                rel = f"{category}/{file_path.name}"
                if state.is_ingested(rel):
                    continue

                attempts += 1

                try:
                    with gzip.open(file_path, "rt", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                except Exception:
                    continue

                if not content.strip():
                    state.mark_ingested(rel, source_type)
                    continue

                metadata = {
                    "source": "hko_archive",
                    "category": category,
                    "filename": file_path.name,
                    "icao": parse_icao_from_name(file_path.name),
                    "obs_time": parse_obs_time_from_name(file_path.name),
                    "local_path": str(file_path),
                }

                row_id = await embed_and_store(
                    db=db,
                    source_type=source_type,
                    content=content,
                    metadata=metadata,
                )

                # Keep failed items retriable in later runs.
                if row_id == -1:
                    failed += 1
                    # Stop early when provider/config is broken to avoid noisy loops.
                    if failed >= min(10, per_category_limit):
                        print(
                            f"Stopping {category} ingest early after {failed} failed embedding attempts. "
                            "Check embedding provider config (EMBED_BASE_URL/EMBED_MODEL/API key)."
                        )
                        break
                    continue

                state.mark_ingested(rel, source_type)
                total += 1
                count += 1

                if count >= per_category_limit:
                    break
    finally:
        await db.close()

    return total


async def run(cfg: SyncConfig):
    state = StateStore(cfg.target_dir / ".sync_state.json")

    auth = httpx.BasicAuth(cfg.user, cfg.password)
    downloaded = 0

    if not cfg.skip_download:
        async with httpx.AsyncClient(auth=auth, follow_redirects=True) as client:
            for category in cfg.download_categories:
                n = await sync_category(client, cfg, state, category)
                downloaded += n
                state.save()

    ingested = 0
    if not cfg.skip_ingest:
        ingested = await ingest_files(cfg, state)
        state.save()

    print(json.dumps({
        "target_dir": str(cfg.target_dir),
        "downloaded_new_files": downloaded,
        "ingested_new_files": ingested,
        "state_file": str(cfg.target_dir / ".sync_state.json"),
    }, indent=2))


def build_config(args: argparse.Namespace) -> SyncConfig:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

    user = args.user or os.getenv("HKO_ARCHIVE_USER", "")
    password = args.password or os.getenv("HKO_ARCHIVE_PASS", "")
    if (not args.skip_download) and (not user or not password):
        raise SystemExit("Missing credentials. Set HKO_ARCHIVE_USER/HKO_ARCHIVE_PASS or pass --user/--password.")

    allowed = {"METAR", "TAF", "SPECI", "ADS_B"}
    download_categories = normalize_categories(args.download_categories, allowed)
    ingest_categories = normalize_categories(args.ingest_categories, {"METAR", "TAF", "SPECI"})

    return SyncConfig(
        base_url=args.base_url,
        target_dir=Path(args.target_dir).resolve(),
        user=user,
        password=password,
        download_categories=download_categories,
        ingest_categories=ingest_categories,
        ingest_limit=args.ingest_limit,
        skip_download=args.skip_download,
        skip_ingest=args.skip_ingest,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync and ingest authenticated HKO archive data")
    parser.add_argument(
        "--base-url",
        default="https://avrdp.hko.gov.hk/Polyu_Hkyaa/August_2025/",
        help="Base month URL ending with '/'",
    )
    parser.add_argument(
        "--target-dir",
        default=str(Path("/Volumes/Angad-SSD/hko-data/August_2025")),
        help="Local target directory on new drive",
    )
    parser.add_argument("--user", default="", help="Basic auth username (or HKO_ARCHIVE_USER)")
    parser.add_argument("--password", default="", help="Basic auth password (or HKO_ARCHIVE_PASS)")
    parser.add_argument(
        "--download-categories",
        default=",".join(DEFAULT_DOWNLOAD_CATEGORIES),
        help="Comma list: METAR,TAF,SPECI,ADS_B",
    )
    parser.add_argument(
        "--ingest-categories",
        default=",".join(DEFAULT_INGEST_CATEGORIES),
        help="Comma list for embedding ingest: METAR,TAF,SPECI",
    )
    parser.add_argument(
        "--ingest-limit",
        type=int,
        default=500,
        help="Max files to ingest per category per run (controls embedding cost/time)",
    )
    parser.add_argument("--skip-download", action="store_true", help="Skip download and only ingest local files")
    parser.add_argument("--skip-ingest", action="store_true", help="Skip ingest and only download/sync")
    return parser.parse_args()


def main():
    args = parse_args()
    cfg = build_config(args)
    asyncio.run(run(cfg))


if __name__ == "__main__":
    main()
