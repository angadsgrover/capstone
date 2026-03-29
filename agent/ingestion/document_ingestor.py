"""
Document ingestion for long-term memory (Mem0 Cloud).

Supports ingestion of:
- Safety documents (incident reports, NTSB reports, ATSB bulletins)
- Regulatory documents (FAA circulars, EASA regulations)
- Technical manuals (aircraft systems, procedures)
- Training materials (SOPs, checklists)

Features:
- Batch ingestion from directory
- Metadata extraction (date, source, type)
- Automatic indexing and retrieval via Mem0 Cloud
- Progress tracking and error handling

Usage:
    from ingestion.document_ingestor import DocumentIngestor

    ingestor = DocumentIngestor(memory_manager)
    await ingestor.ingest_file("safety_reports/ntsb_2024_001.txt")
    await ingestor.ingest_directory("safety_reports/")
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import pathlib
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from memory import DualMemoryManager

logger = logging.getLogger(__name__)


# ── Supported document types ──────────────────────────────────────────────────

SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".pdf", ".html", ".json",
    ".csv", ".xml", ".rtf"
}

# Map file extensions to source types
SOURCE_TYPE_MAPPING = {
    "ntsb": "NTSB Report",
    "atsb": "ATSB Bulletin",
    "faa": "FAA Circular",
    "easa": "EASA Regulation",
    "icao": "ICAO Standard",
    "sop": "Standard Operating Procedure",
    "manual": "Technical Manual",
    "bulletin": "Safety Bulletin",
    "incident": "Incident Report",
    "regulation": "Regulation",
}


# ── Document Ingestor ─────────────────────────────────────────────────────────


class DocumentIngestor:
    """
    Ingest documents into long-term memory (Mem0 Cloud).

    Best Practices:
    1. **Metadata**: Always include source, date, type for better retrieval
    2. **Batch size**: Process 10-50 docs at a time to avoid overwhelming the LLM
    3. **Error handling**: Log failures but continue; don't fail entire batch
    4. **Deduplication**: Use file hash or unique ID to avoid duplicate ingestion
    5. **Chunking**: For large docs (>10k chars), split into sections

    Example:
        ingestor = DocumentIngestor(memory_manager)

        # Single file
        await ingestor.ingest_file(
            "reports/ntsb_2024_001.txt",
            metadata={"date": "2024-01-15", "severity": "high"}
        )

        # Directory (recursive)
        stats = await ingestor.ingest_directory(
            "safety_reports/",
            recursive=True,
            dataset="aviation_safety"
        )
        print(f"Ingested {stats['success']}/{stats['total']} documents")
    """

    def __init__(self, memory_manager: "DualMemoryManager") -> None:
        self.memory_manager = memory_manager

    async def ingest_file(
        self,
        file_path: str | pathlib.Path,
        metadata: Optional[Dict[str, Any]] = None,
        dataset: str = "aviation_knowledge",
    ) -> bool:
        """
        Ingest a single document file.

        Args:
            file_path: Path to document file
            metadata: Optional metadata (source, date, type, etc.)
            dataset: Target dataset name

        Returns:
            True if successful, False otherwise
        """
        if not self.memory_manager.long_term_available:
            logger.warning("Long-term memory unavailable; skipping ingestion.")
            return False

        path = pathlib.Path(file_path)

        if not path.exists():
            logger.warning("File not found: %s", path)
            return False

        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            logger.warning("Unsupported file type: %s", path.suffix)
            return False

        try:
            # Read document content
            content = self._read_document(path)
            if not content:
                logger.warning("Empty document: %s", path)
                return False

            # Extract/enhance metadata
            doc_metadata = self._extract_metadata(path, metadata)

            # Ingest into long-term memory
            success = await self.memory_manager.add_knowledge(
                text=content,
                metadata=doc_metadata,
                dataset_name=dataset,
            )

            if success:
                logger.info("Ingested: %s → %s", path.name, dataset)
            else:
                logger.warning("Failed to ingest: %s", path.name)

            return success

        except Exception as e:
            logger.error("Error ingesting %s: %s", path, e)
            return False

    async def ingest_directory(
        self,
        directory: str | pathlib.Path,
        recursive: bool = True,
        dataset: str = "aviation_knowledge",
        batch_size: int = 10,
        delay_seconds: float = 1.0,
    ) -> Dict[str, int]:
        """
        Ingest all supported documents from a directory.

        Args:
            directory: Path to directory
            recursive: Search subdirectories
            dataset: Target dataset name
            batch_size: Number of files to process concurrently
            delay_seconds: Delay between batches (rate limiting)

        Returns:
            Statistics: {"total": N, "success": M, "failed": K}
        """
        path = pathlib.Path(directory)

        if not path.exists() or not path.is_dir():
            logger.warning("Invalid directory: %s", path)
            return {"total": 0, "success": 0, "failed": 0}

        # Find all supported files
        pattern = "**/*" if recursive else "*"
        files = [
            f for f in path.glob(pattern)
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
        ]

        if not files:
            logger.info("No supported documents found in %s", path)
            return {"total": 0, "success": 0, "failed": 0}

        logger.info("Found %d documents to ingest from %s", len(files), path)

        # Process in batches
        stats = {"total": len(files), "success": 0, "failed": 0}

        for i in range(0, len(files), batch_size):
            batch = files[i:i + batch_size]

            # Process batch concurrently
            tasks = [
                self.ingest_file(str(f), dataset=dataset)
                for f in batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Update stats
            for result in results:
                if isinstance(result, bool) and result:
                    stats["success"] += 1
                else:
                    stats["failed"] += 1

            # Rate limiting delay
            if i + batch_size < len(files):
                await asyncio.sleep(delay_seconds)

        logger.info(
            "Ingestion complete: %d/%d successful, %d failed",
            stats["success"], stats["total"], stats["failed"]
        )

        return stats

    async def ingest_batch(
        self,
        documents: List[Dict[str, Any]],
        dataset: str = "aviation_knowledge",
    ) -> Dict[str, int]:
        """
        Ingest a batch of documents from structured data.

        Args:
            documents: List of {"text": str, "metadata": dict}
            dataset: Target dataset name

        Returns:
            Statistics: {"total": N, "success": M, "failed": K}

        Example:
            docs = [
                {
                    "text": "NTSB report content...",
                    "metadata": {"source": "NTSB", "date": "2024-01-15"}
                },
                ...
            ]
            stats = await ingestor.ingest_batch(docs)
        """
        if not self.memory_manager.long_term_available:
            return {"total": len(documents), "success": 0, "failed": len(documents)}

        success_count = await self.memory_manager.add_knowledge_batch(
            documents=documents,
            dataset_name=dataset,
        )

        return {
            "total": len(documents),
            "success": success_count,
            "failed": len(documents) - success_count,
        }

    # ── Helper methods ────────────────────────────────────────────────────────

    def _read_document(self, path: pathlib.Path) -> str:
        """Read document content (handles text, PDF, etc.)."""
        try:
            if path.suffix.lower() == ".pdf":
                return self._read_pdf(path)
            else:
                # Text-based formats
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()
        except Exception as e:
            logger.error("Error reading %s: %s", path, e)
            return ""

    def _read_pdf(self, path: pathlib.Path) -> str:
        """Extract text from PDF (requires PyPDF2 or pdfplumber)."""
        try:
            import PyPDF2  # type: ignore
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                pages = [page.extract_text() for page in reader.pages]
                return "\n\n".join(pages)
        except ImportError:
            logger.warning("PyPDF2 not installed; cannot read PDF: %s", path)
            return ""
        except Exception as e:
            logger.error("Error reading PDF %s: %s", path, e)
            return ""

    def _extract_metadata(
        self,
        path: pathlib.Path,
        user_metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Extract/enhance metadata from file path and user input."""
        metadata = user_metadata.copy() if user_metadata else {}

        # Add file info
        metadata["filename"] = path.name
        metadata["file_type"] = path.suffix.lower()[1:]  # remove dot

        # Infer source type from filename
        name_lower = path.stem.lower()
        for keyword, source_type in SOURCE_TYPE_MAPPING.items():
            if keyword in name_lower:
                if "source_type" not in metadata:
                    metadata["source_type"] = source_type
                break

        # Add ingestion timestamp
        metadata["ingested_at"] = datetime.now().isoformat()

        # File modification time as doc date (if not provided)
        if "date" not in metadata:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            metadata["date"] = mtime.strftime("%Y-%m-%d")

        return metadata
