#!/usr/bin/env python3
"""
Embeddings Transfer Utility

Export embeddings from local PostgreSQL to a JSON file, then import to a cloud database.
Useful for migrating data between development and production environments.

Usage:
    # Export from local DB
    export POSTGRES_DSN="postgresql://user:pass@localhost:5432/capstone"
    python scripts/embeddings_transfer.py export --output embeddings_backup.json

    # Import to cloud DB
    export POSTGRES_DSN="postgresql://user:pass@cloud-host:5432/capstone"
    python scripts/embeddings_transfer.py import --input embeddings_backup.json

    # Transfer directly (export + import in one step)
    export SOURCE_POSTGRES_DSN="postgresql://..."
    export TARGET_POSTGRES_DSN="postgresql://..."
    python scripts/embeddings_transfer.py transfer
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

try:
    import asyncpg
except ImportError:
    logger.error("asyncpg not installed. Run: pip install asyncpg")
    sys.exit(1)


async def get_pool(dsn: str) -> asyncpg.Pool:
    """Create a connection pool to the database."""
    return await asyncpg.create_pool(dsn, min_size=1, max_size=5)


async def export_embeddings(dsn: str, output_path: str, batch_size: int = 1000) -> int:
    """Export all embeddings to a JSON file (optionally gzipped)."""
    pool = await get_pool(dsn)
    
    try:
        # Get total count
        count = await pool.fetchval("SELECT COUNT(*) FROM embeddings")
        logger.info(f"Found {count} embeddings to export")
        
        if count == 0:
            logger.warning("No embeddings to export")
            return 0
        
        # Determine if we should compress
        compress = output_path.endswith('.gz')
        opener = gzip.open if compress else open
        
        exported = 0
        offset = 0
        
        with opener(output_path, 'wt', encoding='utf-8') as f:
            f.write('[\n')  # Start JSON array
            first = True
            
            while offset < count:
                rows = await pool.fetch(
                    """
                    SELECT 
                        id,
                        source_type,
                        source_id,
                        content,
                        embedding::text as embedding_text,
                        metadata,
                        created_at
                    FROM embeddings
                    ORDER BY id
                    LIMIT $1 OFFSET $2
                    """,
                    batch_size,
                    offset
                )
                
                for row in rows:
                    if not first:
                        f.write(',\n')
                    first = False
                    
                    # Convert embedding text "[0.1, 0.2, ...]" to list
                    embedding_str = row['embedding_text']
                    embedding_list = json.loads(embedding_str) if embedding_str else None
                    
                    record = {
                        'id': row['id'],
                        'source_type': row['source_type'],
                        'source_id': row['source_id'],
                        'content': row['content'],
                        'embedding': embedding_list,
                        'metadata': dict(row['metadata']) if row['metadata'] else None,
                        'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                    }
                    json.dump(record, f, separators=(',', ':'))
                    exported += 1
                
                offset += batch_size
                logger.info(f"Exported {exported}/{count} embeddings...")
            
            f.write('\n]')  # End JSON array
        
        logger.info(f"Successfully exported {exported} embeddings to {output_path}")
        return exported
        
    finally:
        await pool.close()


async def import_embeddings(
    dsn: str,
    input_path: str,
    batch_size: int = 100,
    skip_existing: bool = True,
) -> int:
    """Import embeddings from a JSON file into the database."""
    pool = await get_pool(dsn)
    
    try:
        # Determine if compressed
        compress = input_path.endswith('.gz')
        opener = gzip.open if compress else open
        
        with opener(input_path, 'rt', encoding='utf-8') as f:
            records = json.load(f)
        
        logger.info(f"Loaded {len(records)} embeddings from {input_path}")
        
        if not records:
            logger.warning("No embeddings to import")
            return 0
        
        imported = 0
        skipped = 0
        
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            
            for record in batch:
                # Check if already exists by content hash (or id if preserving)
                if skip_existing:
                    exists = await pool.fetchval(
                        "SELECT 1 FROM embeddings WHERE source_type = $1 AND content = $2 LIMIT 1",
                        record['source_type'],
                        record['content'],
                    )
                    if exists:
                        skipped += 1
                        continue
                
                # Convert embedding list to pgvector literal
                embedding = record.get('embedding')
                embedding_literal = json.dumps(embedding) if embedding else None
                
                # Parse created_at
                created_at = None
                if record.get('created_at'):
                    created_at = datetime.fromisoformat(record['created_at'].replace('Z', '+00:00'))
                
                await pool.execute(
                    """
                    INSERT INTO embeddings (source_type, source_id, content, embedding, metadata, created_at)
                    VALUES ($1, $2, $3, $4::vector, $5, COALESCE($6, NOW()))
                    """,
                    record['source_type'],
                    record.get('source_id'),
                    record['content'],
                    embedding_literal,
                    json.dumps(record.get('metadata') or {}),
                    created_at,
                )
                imported += 1
            
            logger.info(f"Imported {imported} embeddings, skipped {skipped} duplicates...")
        
        logger.info(f"Successfully imported {imported} embeddings ({skipped} skipped)")
        return imported
        
    finally:
        await pool.close()


async def transfer_embeddings(
    source_dsn: str,
    target_dsn: str,
    batch_size: int = 500,
) -> int:
    """Transfer embeddings directly from source to target database."""
    source_pool = await get_pool(source_dsn)
    target_pool = await get_pool(target_dsn)
    
    try:
        # Get total count
        count = await source_pool.fetchval("SELECT COUNT(*) FROM embeddings")
        logger.info(f"Found {count} embeddings to transfer")
        
        if count == 0:
            logger.warning("No embeddings to transfer")
            return 0
        
        transferred = 0
        skipped = 0
        offset = 0
        
        while offset < count:
            rows = await source_pool.fetch(
                """
                SELECT 
                    source_type,
                    source_id,
                    content,
                    embedding::text as embedding_text,
                    metadata,
                    created_at
                FROM embeddings
                ORDER BY id
                LIMIT $1 OFFSET $2
                """,
                batch_size,
                offset
            )
            
            for row in rows:
                # Check if already exists
                exists = await target_pool.fetchval(
                    "SELECT 1 FROM embeddings WHERE source_type = $1 AND content = $2 LIMIT 1",
                    row['source_type'],
                    row['content'],
                )
                if exists:
                    skipped += 1
                    continue
                
                await target_pool.execute(
                    """
                    INSERT INTO embeddings (source_type, source_id, content, embedding, metadata, created_at)
                    VALUES ($1, $2, $3, $4::vector, $5, $6)
                    """,
                    row['source_type'],
                    row['source_id'],
                    row['content'],
                    row['embedding_text'],
                    json.dumps(dict(row['metadata']) if row['metadata'] else {}),
                    row['created_at'],
                )
                transferred += 1
            
            offset += batch_size
            logger.info(f"Transferred {transferred}/{count}, skipped {skipped}...")
        
        logger.info(f"Successfully transferred {transferred} embeddings ({skipped} skipped)")
        return transferred
        
    finally:
        await source_pool.close()
        await target_pool.close()


async def main():
    parser = argparse.ArgumentParser(
        description="Export/import embeddings between PostgreSQL databases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest='command', required=True)
    
    # Export command
    export_parser = subparsers.add_parser('export', help='Export embeddings to JSON file')
    export_parser.add_argument('--output', '-o', required=True, help='Output file path (.json or .json.gz)')
    export_parser.add_argument('--batch-size', type=int, default=1000, help='Batch size for export')
    
    # Import command
    import_parser = subparsers.add_parser('import', help='Import embeddings from JSON file')
    import_parser.add_argument('--input', '-i', required=True, help='Input file path (.json or .json.gz)')
    import_parser.add_argument('--batch-size', type=int, default=100, help='Batch size for import')
    import_parser.add_argument('--allow-duplicates', action='store_true', help='Import duplicates')
    
    # Transfer command
    transfer_parser = subparsers.add_parser('transfer', help='Direct transfer between databases')
    transfer_parser.add_argument('--batch-size', type=int, default=500, help='Batch size for transfer')
    
    args = parser.parse_args()
    
    if args.command == 'export':
        dsn = os.getenv('POSTGRES_DSN')
        if not dsn:
            logger.error("POSTGRES_DSN environment variable not set")
            sys.exit(1)
        await export_embeddings(dsn, args.output, args.batch_size)
        
    elif args.command == 'import':
        dsn = os.getenv('POSTGRES_DSN')
        if not dsn:
            logger.error("POSTGRES_DSN environment variable not set")
            sys.exit(1)
        await import_embeddings(dsn, args.input, args.batch_size, not args.allow_duplicates)
        
    elif args.command == 'transfer':
        source_dsn = os.getenv('SOURCE_POSTGRES_DSN')
        target_dsn = os.getenv('TARGET_POSTGRES_DSN')
        if not source_dsn or not target_dsn:
            logger.error("SOURCE_POSTGRES_DSN and TARGET_POSTGRES_DSN environment variables required")
            sys.exit(1)
        await transfer_embeddings(source_dsn, target_dsn, args.batch_size)


if __name__ == '__main__':
    asyncio.run(main())
