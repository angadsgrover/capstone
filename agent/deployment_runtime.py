"""Durable local runtime state for deployment-style assistant/thread/run/cron APIs.

This module provides a VM-friendly persistence layer (JSON file) so deployment
features continue working without LangSmith Cloud or a dedicated control plane.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _metadata_matches(target: Dict[str, Any], required: Dict[str, Any]) -> bool:
    for key, value in required.items():
        if target.get(key) != value:
            return False
    return True


class DeploymentRuntimeStore:
    """File-backed store for assistants, threads, runs, and crons."""

    def __init__(self, state_file: str) -> None:
        self.state_file = state_file
        self.lock = asyncio.Lock()
        self.assistants: Dict[str, Dict[str, Any]] = {}
        self.threads: Dict[str, Dict[str, Any]] = {}
        self.runs: Dict[str, Dict[str, Any]] = {}
        self.crons: Dict[str, Dict[str, Any]] = {}

    async def load(self) -> None:
        async with self.lock:
            if os.path.exists(self.state_file):
                try:
                    data = await asyncio.to_thread(self._read_file)
                except Exception:
                    data = {}
                self.assistants = data.get("assistants", {})
                self.threads = data.get("threads", {})
                self.runs = data.get("runs", {})
                self.crons = data.get("crons", {})
            await self._ensure_default_assistant_unlocked()
            await self._persist_unlocked()

    async def persist(self) -> None:
        async with self.lock:
            await self._persist_unlocked()

    def _read_file(self) -> Dict[str, Any]:
        with open(self.state_file, "r", encoding="utf-8") as handle:
            return json.load(handle)

    async def _persist_unlocked(self) -> None:
        payload = {
            "assistants": self.assistants,
            "threads": self.threads,
            "runs": self.runs,
            "crons": self.crons,
        }
        directory = os.path.dirname(self.state_file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp_file = f"{self.state_file}.tmp"

        def _write() -> None:
            with open(tmp_file, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
            os.replace(tmp_file, self.state_file)

        await asyncio.to_thread(_write)

    async def _ensure_default_assistant_unlocked(self) -> None:
        for assistant in self.assistants.values():
            if assistant.get("graph_id") == "agent" and assistant.get("is_default"):
                return

        assistant_id = "assistant-agent-default"
        now = utc_now_iso()
        config = {
            "model": os.getenv("MODEL_CHOICE", "openai/gpt-4o-mini"),
            "base_url": os.getenv("BASE_URL", "https://openrouter.ai/api/v1"),
            "assistant_system_prompt": "",
            "forced_route": "",
        }
        self.assistants[assistant_id] = {
            "assistant_id": assistant_id,
            "name": "Default Agent Assistant",
            "graph_id": "agent",
            "description": "Default assistant bound to the primary graph",
            "metadata": {"default": True},
            "config": config,
            "is_default": True,
            "version": 1,
            "versions": [
                {
                    "version": 1,
                    "created_at": now,
                    "config": config,
                    "metadata": {"default": True},
                }
            ],
            "created_at": now,
            "updated_at": now,
        }

    async def create_assistant(
        self,
        name: str,
        graph_id: str,
        config: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        description: str = "",
        assistant_id: str = "",
    ) -> Dict[str, Any]:
        async with self.lock:
            now = utc_now_iso()
            resolved_id = assistant_id.strip() or str(uuid.uuid4())
            if resolved_id in self.assistants:
                raise ValueError(f"assistant_id already exists: {resolved_id}")

            assistant = {
                "assistant_id": resolved_id,
                "name": name or f"Assistant {resolved_id[:8]}",
                "graph_id": graph_id or "agent",
                "description": description or "",
                "metadata": metadata or {},
                "config": config or {},
                "is_default": False,
                "version": 1,
                "versions": [
                    {
                        "version": 1,
                        "created_at": now,
                        "config": config or {},
                        "metadata": metadata or {},
                    }
                ],
                "created_at": now,
                "updated_at": now,
            }
            self.assistants[resolved_id] = assistant
            await self._persist_unlocked()
            return _clone(assistant)

    async def get_assistant(self, assistant_id: str) -> Optional[Dict[str, Any]]:
        async with self.lock:
            assistant = self.assistants.get(assistant_id)
            return _clone(assistant) if assistant else None

    async def resolve_assistant(self, assistant_ref: str = "") -> Optional[Dict[str, Any]]:
        async with self.lock:
            ref = (assistant_ref or "").strip()
            if ref and ref in self.assistants:
                return _clone(self.assistants[ref])

            if ref:
                for assistant in self.assistants.values():
                    if assistant.get("graph_id") == ref and assistant.get("is_default"):
                        return _clone(assistant)
                for assistant in self.assistants.values():
                    if assistant.get("graph_id") == ref:
                        return _clone(assistant)

            for assistant in self.assistants.values():
                if assistant.get("graph_id") == "agent" and assistant.get("is_default"):
                    return _clone(assistant)
            return None

    async def patch_assistant(
        self,
        assistant_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        async with self.lock:
            assistant = self.assistants.get(assistant_id)
            if not assistant:
                return None

            if name is not None:
                assistant["name"] = name
            if description is not None:
                assistant["description"] = description
            if config is not None:
                assistant["config"] = config
            if metadata is not None:
                assistant["metadata"] = metadata

            assistant["version"] = int(assistant.get("version", 1)) + 1
            assistant["updated_at"] = utc_now_iso()
            assistant.setdefault("versions", []).append(
                {
                    "version": assistant["version"],
                    "created_at": assistant["updated_at"],
                    "config": assistant.get("config", {}),
                    "metadata": assistant.get("metadata", {}),
                }
            )
            await self._persist_unlocked()
            return _clone(assistant)

    async def delete_assistant(self, assistant_id: str) -> bool:
        async with self.lock:
            assistant = self.assistants.get(assistant_id)
            if not assistant or assistant.get("is_default"):
                return False
            self.assistants.pop(assistant_id, None)
            await self._persist_unlocked()
            return True

    async def search_assistants(
        self,
        metadata: Optional[Dict[str, Any]] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        async with self.lock:
            rows = sorted(
                self.assistants.values(),
                key=lambda row: row.get("updated_at", ""),
                reverse=True,
            )
            if metadata:
                rows = [row for row in rows if _metadata_matches(row.get("metadata", {}), metadata)]
            sliced = rows[max(offset, 0): max(offset, 0) + max(limit, 0)]
            return _clone(sliced)

    async def count_assistants(self, metadata: Optional[Dict[str, Any]] = None) -> int:
        async with self.lock:
            if not metadata:
                return len(self.assistants)
            return sum(1 for row in self.assistants.values() if _metadata_matches(row.get("metadata", {}), metadata))

    async def create_thread(
        self,
        metadata: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        values: Optional[Dict[str, Any]] = None,
        thread_id: str = "",
    ) -> Dict[str, Any]:
        async with self.lock:
            now = utc_now_iso()
            resolved_id = thread_id.strip() or str(uuid.uuid4())
            if resolved_id in self.threads:
                raise ValueError(f"thread_id already exists: {resolved_id}")
            thread = {
                "thread_id": resolved_id,
                "created_at": now,
                "updated_at": now,
                "metadata": metadata or {},
                "status": "idle",
                "config": config or {},
                "values": values,
                "messages": [],
            }
            self.threads[resolved_id] = thread
            await self._persist_unlocked()
            return _clone(thread)

    async def get_thread(self, thread_id: str) -> Optional[Dict[str, Any]]:
        async with self.lock:
            thread = self.threads.get(thread_id)
            return _clone(thread) if thread else None

    async def patch_thread(
        self,
        thread_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        values: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        async with self.lock:
            thread = self.threads.get(thread_id)
            if not thread:
                return None
            if metadata is not None:
                thread["metadata"] = metadata
            if config is not None:
                thread["config"] = config
            if values is not None:
                thread["values"] = values
            thread["updated_at"] = utc_now_iso()
            await self._persist_unlocked()
            return _clone(thread)

    async def set_thread_status(self, thread_id: str, status: str) -> None:
        async with self.lock:
            thread = self.threads.get(thread_id)
            if not thread:
                return
            thread["status"] = status
            thread["updated_at"] = utc_now_iso()
            await self._persist_unlocked()

    async def append_thread_message(self, thread_id: str, role: str, content: str, run_id: str = "") -> None:
        async with self.lock:
            thread = self.threads.get(thread_id)
            if not thread:
                return
            thread.setdefault("messages", []).append(
                {
                    "role": role,
                    "content": content,
                    "run_id": run_id,
                    "timestamp": utc_now_iso(),
                }
            )
            max_messages = max(20, int(os.getenv("DEPLOYMENT_THREAD_HISTORY_LIMIT", "200")))
            if len(thread["messages"]) > max_messages:
                thread["messages"] = thread["messages"][-max_messages:]
            thread["updated_at"] = utc_now_iso()
            await self._persist_unlocked()

    async def delete_thread(self, thread_id: str) -> bool:
        async with self.lock:
            if thread_id not in self.threads:
                return False
            self.threads.pop(thread_id, None)
            # Keep run history for auditability; do not remove from runs.
            await self._persist_unlocked()
            return True

    async def search_threads(
        self,
        metadata: Optional[Dict[str, Any]] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        async with self.lock:
            rows = sorted(
                self.threads.values(),
                key=lambda row: row.get("updated_at", ""),
                reverse=True,
            )
            if metadata:
                rows = [row for row in rows if _metadata_matches(row.get("metadata", {}), metadata)]
            sliced = rows[max(offset, 0): max(offset, 0) + max(limit, 0)]
            return _clone(sliced)

    async def count_threads(self, metadata: Optional[Dict[str, Any]] = None) -> int:
        async with self.lock:
            if not metadata:
                return len(self.threads)
            return sum(1 for row in self.threads.values() if _metadata_matches(row.get("metadata", {}), metadata))

    async def create_run(
        self,
        thread_id: str,
        assistant_id: str,
        input_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        mode: str = "background",
        run_id: str = "",
        status: str = "queued",
    ) -> Dict[str, Any]:
        async with self.lock:
            now = utc_now_iso()
            resolved_id = run_id.strip() or str(uuid.uuid4())
            if resolved_id in self.runs:
                raise ValueError(f"run_id already exists: {resolved_id}")
            run = {
                "run_id": resolved_id,
                "thread_id": thread_id,
                "assistant_id": assistant_id,
                "status": status,
                "mode": mode,
                "input": input_payload,
                "metadata": metadata or {},
                "created_at": now,
                "updated_at": now,
                "started_at": None,
                "completed_at": None,
                "error": None,
                "output": None,
                "events_run_id": resolved_id,
            }
            self.runs[resolved_id] = run
            if thread_id in self.threads:
                self.threads[thread_id]["status"] = "running" if status in ("queued", "running") else "idle"
                self.threads[thread_id]["updated_at"] = now
            await self._persist_unlocked()
            return _clone(run)

    async def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        async with self.lock:
            run = self.runs.get(run_id)
            return _clone(run) if run else None

    async def list_runs(
        self,
        thread_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        async with self.lock:
            rows = [row for row in self.runs.values() if row.get("thread_id") == thread_id]
            rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
            sliced = rows[max(offset, 0): max(offset, 0) + max(limit, 0)]
            return _clone(sliced)

    async def update_run(
        self,
        run_id: str,
        status: Optional[str] = None,
        output: Any = None,
        error: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        async with self.lock:
            run = self.runs.get(run_id)
            if not run:
                return None

            now = utc_now_iso()
            if status:
                run["status"] = status
                if status == "running" and not run.get("started_at"):
                    run["started_at"] = now
                if status in ("completed", "failed", "cancelled"):
                    run["completed_at"] = now
            if output is not None:
                run["output"] = output
            if error is not None:
                run["error"] = error
            run["updated_at"] = now

            thread_id = run.get("thread_id")
            if thread_id and thread_id in self.threads:
                if run.get("status") in ("running", "queued"):
                    self.threads[thread_id]["status"] = "running"
                else:
                    self.threads[thread_id]["status"] = "idle"
                self.threads[thread_id]["updated_at"] = now

            await self._persist_unlocked()
            return _clone(run)

    async def create_cron(
        self,
        assistant_id: str,
        schedule: str,
        input_payload: Dict[str, Any],
        thread_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        on_run_completed: str = "delete",
        cron_id: str = "",
    ) -> Dict[str, Any]:
        async with self.lock:
            now = utc_now_iso()
            resolved_id = cron_id.strip() or str(uuid.uuid4())
            if resolved_id in self.crons:
                raise ValueError(f"cron_id already exists: {resolved_id}")

            cron = {
                "cron_id": resolved_id,
                "assistant_id": assistant_id,
                "thread_id": thread_id or None,
                "schedule": schedule,
                "input": input_payload,
                "metadata": metadata or {},
                "on_run_completed": on_run_completed if on_run_completed in ("delete", "keep") else "delete",
                "active": True,
                "created_at": now,
                "updated_at": now,
                "last_run_at": None,
                "last_run_id": None,
                "run_count": 0,
                "next_run_at": None,
            }
            self.crons[resolved_id] = cron
            await self._persist_unlocked()
            return _clone(cron)

    async def update_cron(
        self,
        cron_id: str,
        schedule: Optional[str] = None,
        input_payload: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        active: Optional[bool] = None,
        on_run_completed: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        async with self.lock:
            cron = self.crons.get(cron_id)
            if not cron:
                return None

            if schedule is not None:
                cron["schedule"] = schedule
            if input_payload is not None:
                cron["input"] = input_payload
            if metadata is not None:
                cron["metadata"] = metadata
            if active is not None:
                cron["active"] = bool(active)
            if on_run_completed is not None and on_run_completed in ("delete", "keep"):
                cron["on_run_completed"] = on_run_completed

            cron["updated_at"] = utc_now_iso()
            await self._persist_unlocked()
            return _clone(cron)

    async def mark_cron_run(self, cron_id: str, run_id: str, next_run_at: Optional[str] = None) -> Optional[Dict[str, Any]]:
        async with self.lock:
            cron = self.crons.get(cron_id)
            if not cron:
                return None
            cron["last_run_at"] = utc_now_iso()
            cron["last_run_id"] = run_id
            cron["run_count"] = int(cron.get("run_count", 0)) + 1
            cron["updated_at"] = utc_now_iso()
            cron["next_run_at"] = next_run_at
            await self._persist_unlocked()
            return _clone(cron)

    async def set_cron_next_run(self, cron_id: str, next_run_at: Optional[str]) -> None:
        async with self.lock:
            cron = self.crons.get(cron_id)
            if not cron:
                return
            cron["next_run_at"] = next_run_at
            cron["updated_at"] = utc_now_iso()
            await self._persist_unlocked()

    async def get_cron(self, cron_id: str) -> Optional[Dict[str, Any]]:
        async with self.lock:
            cron = self.crons.get(cron_id)
            return _clone(cron) if cron else None

    async def search_crons(
        self,
        metadata: Optional[Dict[str, Any]] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        async with self.lock:
            rows = sorted(
                self.crons.values(),
                key=lambda row: row.get("updated_at", ""),
                reverse=True,
            )
            if metadata:
                rows = [row for row in rows if _metadata_matches(row.get("metadata", {}), metadata)]
            sliced = rows[max(offset, 0): max(offset, 0) + max(limit, 0)]
            return _clone(sliced)

    async def count_crons(self, metadata: Optional[Dict[str, Any]] = None) -> int:
        async with self.lock:
            if not metadata:
                return len(self.crons)
            return sum(1 for row in self.crons.values() if _metadata_matches(row.get("metadata", {}), metadata))

    async def delete_cron(self, cron_id: str) -> bool:
        async with self.lock:
            if cron_id not in self.crons:
                return False
            self.crons.pop(cron_id, None)
            await self._persist_unlocked()
            return True
