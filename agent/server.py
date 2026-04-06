"""
FastAPI server for the LangGraph aviation weather agent.
"""
import asyncio
import json
import logging
import os
import pathlib
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

try:
    from langsmith import traceable
    from langsmith.run_helpers import get_current_run_tree
except Exception:  # pragma: no cover - safe no-op fallback when langsmith unavailable
    def traceable(*args, **kwargs):
        if args and callable(args[0]) and len(args) == 1 and not kwargs:
            return args[0]

        def _decorator(fn):
            return fn

        return _decorator

    def get_current_run_tree():
        return None

try:
    from langsmith.middleware import TracingMiddleware
except Exception:  # pragma: no cover - optional runtime dependency
    TracingMiddleware = None

try:
    from langsmith import tracing_context as langsmith_tracing_context
except Exception:  # pragma: no cover - optional runtime dependency
    langsmith_tracing_context = None

try:
    import jwt
    from jwt import InvalidTokenError, PyJWKClient
except Exception:  # pragma: no cover - optional dependency handling
    jwt = None
    InvalidTokenError = Exception
    PyJWKClient = None

try:
    from livekit import api as livekit_api  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional dependency handling
    livekit_api = None

from db import Database
from deployment_runtime import DeploymentRuntimeStore
from memory import DualMemoryManager  # Upgraded from MemoryManager
from cache import CacheManager
from orchestrator import init_graph
import mcp_client as mcp_module

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
except Exception:  # pragma: no cover - optional dependency handling
    AsyncIOScheduler = None
    CronTrigger = None

logger = logging.getLogger(__name__)

# ── LangSmith (optional observability) ────────────────────────────────────────

_langsmith_enabled = False
_langsmith_client = None
_langsmith_status_reason = "not_initialized"
_langsmith_last_error = ""
_langsmith_tracing_middleware_enabled = False


def _parse_bool_env(value: Optional[str]) -> Optional[bool]:
    """Parse an environment boolean, returning None when unset/invalid."""
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    return None


def _langsmith_endpoint() -> str:
    return os.getenv("LANGSMITH_ENDPOINT") or os.getenv("LANGCHAIN_ENDPOINT") or "https://api.smith.langchain.com"


def _langsmith_project() -> str:
    return os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGCHAIN_PROJECT") or "default"


def _langsmith_ui_base() -> str:
    explicit = (os.getenv("LANGSMITH_UI_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit

    endpoint = _langsmith_endpoint().strip()
    parsed = urlparse(endpoint)
    scheme = parsed.scheme or "https"
    host = parsed.netloc or "api.smith.langchain.com"
    path = (parsed.path or "").rstrip("/")

    if host == "api.smith.langchain.com":
        host = "smith.langchain.com"
    elif host == "eu.api.smith.langchain.com":
        host = "eu.smith.langchain.com"
    elif host.startswith("api."):
        host = host[4:]

    if path.endswith("/api"):
        path = path[:-4]

    base = f"{scheme}://{host}{path}"
    return base.rstrip("/")


def _langsmith_dashboard_url() -> str:
    return f"{_langsmith_ui_base()}/monitor"


def _langsmith_trace_context() -> Dict[str, Any]:
    run_tree = get_current_run_tree()
    if not run_tree:
        return {}

    try:
        run_id = str(getattr(run_tree, "id", "") or "")
        trace_id = str(getattr(run_tree, "trace_id", "") or "")
        if not run_id and not trace_id:
            return {}
        return {
            "root_run_id": run_id,
            "trace_id": trace_id,
            "project": _langsmith_project(),
            "ui_url": _langsmith_ui_base(),
            "dashboard_url": _langsmith_dashboard_url(),
        }
    except Exception:
        return {}

def _init_langsmith() -> bool:
    """Initialize LangSmith tracing if credentials are available.
    
    LangSmith has native integration with LangChain/LangGraph - tracing is 
    automatic when LANGSMITH_TRACING=true and LANGSMITH_API_KEY is set.
    We just need to verify the configuration and create a client for feedback.
    """
    global _langsmith_enabled, _langsmith_client, _langsmith_status_reason, _langsmith_last_error

    api_key = os.getenv("LANGSMITH_API_KEY")
    tracing_preference = _parse_bool_env(os.getenv("LANGSMITH_TRACING"))

    # Also support legacy LANGCHAIN_TRACING_V2 env var.
    if tracing_preference is None:
        tracing_preference = _parse_bool_env(os.getenv("LANGCHAIN_TRACING_V2"))

    # Default to enabled tracing unless explicitly disabled.
    tracing_enabled = True if tracing_preference is None else tracing_preference
    
    # Support LANGCHAIN_API_KEY as fallback
    if not api_key:
        api_key = os.getenv("LANGCHAIN_API_KEY")

    if not api_key:
        _langsmith_status_reason = "missing_api_key"
        _langsmith_last_error = ""
        logger.info("LangSmith disabled: LANGSMITH_API_KEY not set")
        return False

    if not tracing_enabled:
        _langsmith_status_reason = "disabled_by_env"
        _langsmith_last_error = ""
        logger.info("LangSmith disabled: tracing explicitly disabled by env")
        return False

    try:
        from langsmith import Client
        
        endpoint = _langsmith_endpoint()
        project = _langsmith_project()
        
        # Ensure env vars are set for automatic LangChain/LangGraph tracing
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGSMITH_API_KEY"] = api_key
        os.environ["LANGCHAIN_API_KEY"] = api_key
        os.environ["LANGCHAIN_PROJECT"] = project
        if endpoint != "https://api.smith.langchain.com":
            os.environ["LANGSMITH_ENDPOINT"] = endpoint
            os.environ["LANGCHAIN_ENDPOINT"] = endpoint
        
        # Create client for feedback operations
        _langsmith_client = Client(
            api_key=api_key,
            api_url=endpoint,
        )
        
        _langsmith_enabled = True
        _langsmith_status_reason = "enabled"
        _langsmith_last_error = ""
        logger.info("LangSmith initialized successfully (endpoint: %s, project: %s)", endpoint, project)
        return True
    except Exception as e:
        _langsmith_status_reason = "init_error"
        _langsmith_last_error = str(e)
        logger.warning("LangSmith initialization failed: %s", e)
        return False


def _shutdown_langsmith() -> None:
    """Gracefully shutdown LangSmith (flush any pending traces)."""
    global _langsmith_client
    if not _langsmith_enabled:
        return
    try:
        # LangSmith SDK handles flushing automatically, but we can ensure cleanup
        _langsmith_client = None
        logger.info("LangSmith shutdown completed")
    except Exception as e:
        logger.warning("LangSmith shutdown error: %s", e)


def _create_feedback(
    run_id: str,
    key: str,
    score: float,
    comment: str = "",
    trace_id: Optional[str] = None,
) -> bool:
    """
    Add feedback to a LangSmith run/trace.

    Args:
        run_id: The LangSmith run ID to add feedback to
        key: Feedback key (e.g., "user-rating", "relevance", "helpfulness")
        score: Numeric score value (typically 0-1, but 1-5 is also supported)
        comment: Optional comment explaining the feedback
        trace_id: Optional trace ID for batched ingestion (recommended)

    Returns:
        True if feedback was created, False otherwise
    """
    if not _langsmith_enabled or not _langsmith_client:
        return False
    try:
        # Normalize score to 0-1 range if it's in 1-5 range
        normalized_score = score / 5.0 if score > 1 else score
        
        _langsmith_client.create_feedback(
            run_id=run_id,
            key=key,
            score=normalized_score,
            comment=comment or None,
            # trace_id helps with batched ingestion
            **{"trace_id": trace_id} if trace_id else {},
        )
        return True
    except Exception as e:
        logger.warning("Failed to create feedback for run %s: %s", run_id, e)
        return False


def _generate_trace_id(session_id: str, timestamp: Optional[str] = None) -> str:
    """
    Generate a deterministic trace ID for a session.

    This allows the frontend to predict the trace ID and link back to LangSmith.
    """
    import hashlib
    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat()
    seed = f"{session_id}:{timestamp}"
    return hashlib.sha256(seed.encode()).hexdigest()[:32]

# ── Module-level singletons ────────────────────────────────────────────────────

db             = Database()
memory_manager = DualMemoryManager()  # Unified short-term + long-term memory on Mem0 Cloud
cache          = CacheManager()       # Redis cache for frequently-asked queries

# ── Runtime scaling controls ──────────────────────────────────────────────────

MAX_CONCURRENT_GRAPH_RUNS = int(os.getenv("MAX_CONCURRENT_GRAPH_RUNS", "120"))
MAX_PENDING_EVENT_STREAMS = int(os.getenv("MAX_PENDING_EVENT_STREAMS", "2000"))
EVENT_QUEUE_MAXSIZE = int(os.getenv("EVENT_QUEUE_MAXSIZE", "512"))
RUN_REGISTRY_TTL_SECONDS = int(os.getenv("RUN_REGISTRY_TTL_SECONDS", "900"))
RUN_REGISTRY_CLEANUP_INTERVAL_SECONDS = int(
    os.getenv("RUN_REGISTRY_CLEANUP_INTERVAL_SECONDS", "60")
)

# API rate limits (distributed via Redis when available)
ENABLE_ENDPOINT_RATE_LIMITING = os.getenv("ENABLE_ENDPOINT_RATE_LIMITING", "true").lower() == "true"
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_AGENT_PER_WINDOW = int(os.getenv("RATE_LIMIT_AGENT_PER_WINDOW", "30"))
RATE_LIMIT_STREAM_PER_WINDOW = int(os.getenv("RATE_LIMIT_STREAM_PER_WINDOW", "20"))
RATE_LIMIT_EXECUTE_PER_WINDOW = int(os.getenv("RATE_LIMIT_EXECUTE_PER_WINDOW", "20"))

# Fall back to client IP when session_id is absent.
RATE_LIMIT_USE_CLIENT_IP = os.getenv("RATE_LIMIT_USE_CLIENT_IP", "true").lower() == "true"

# LiveKit voice token settings
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "").strip()
LIVEKIT_DEFAULT_ROOM = (os.getenv("LIVEKIT_DEFAULT_ROOM") or "polyu-weather-voice").strip() or "polyu-weather-voice"
LIVEKIT_TOKEN_TTL_SECONDS = max(60, int(os.getenv("LIVEKIT_TOKEN_TTL_SECONDS", "600")))

# Optional neural TTS settings (OpenAI-compatible /audio/speech API)
TTS_BASE_URL = (os.getenv("TTS_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
TTS_MODEL = (os.getenv("TTS_MODEL") or "gpt-4o-mini-tts").strip() or "gpt-4o-mini-tts"
TTS_VOICE = (os.getenv("TTS_VOICE") or "alloy").strip() or "alloy"
TTS_FORMAT = (os.getenv("TTS_FORMAT") or "mp3").strip().lower() or "mp3"
TTS_TIMEOUT_SECONDS = max(10.0, float(os.getenv("TTS_TIMEOUT_SECONDS", "90")))

# CORS hardening
_cors_origins_raw = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:80,http://localhost:5173")
CORS_ALLOW_ORIGINS = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
CORS_ALLOW_CREDENTIALS = os.getenv("CORS_ALLOW_CREDENTIALS", "false").lower() == "true"

# Auth subject extraction for governance/rate-limiting
AUTH_SUBJECT_USER_HEADER = os.getenv("AUTH_SUBJECT_USER_HEADER", "x-user-id")
AUTH_SUBJECT_TENANT_HEADER = os.getenv("AUTH_SUBJECT_TENANT_HEADER", "x-tenant-id")
REQUIRE_AUTH_SUBJECT = os.getenv("REQUIRE_AUTH_SUBJECT", "false").lower() == "true"

# Optional JWT/OIDC verification for subject extraction.
AUTH_VERIFICATION_MODE = os.getenv("AUTH_VERIFICATION_MODE", "none").strip().lower()  # none | jwt
AUTH_ALLOW_HEADER_FALLBACK = os.getenv("AUTH_ALLOW_HEADER_FALLBACK", "true").lower() == "true"
AUTH_REQUIRE_VERIFIED_SUBJECT = os.getenv("AUTH_REQUIRE_VERIFIED_SUBJECT", "false").lower() == "true"
JWT_ISSUER = os.getenv("JWT_ISSUER", "").strip()
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "").strip()
JWT_ALGORITHMS = [
    alg.strip() for alg in os.getenv("JWT_ALGORITHMS", "RS256").split(",") if alg.strip()
]
JWT_JWKS_URL = os.getenv("JWT_JWKS_URL", "").strip()
JWT_PUBLIC_KEY = os.getenv("JWT_PUBLIC_KEY", "")
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_LEEWAY_SECONDS = int(os.getenv("JWT_LEEWAY_SECONDS", "30"))
JWT_SUBJECT_CLAIM = os.getenv("JWT_SUBJECT_CLAIM", "sub").strip()
JWT_USER_ID_CLAIM = os.getenv("JWT_USER_ID_CLAIM", "sub").strip()
JWT_TENANT_ID_CLAIM = os.getenv("JWT_TENANT_ID_CLAIM", "tenant_id").strip()

# Request/input guarding
MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", str(1024 * 1024)))
MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "12000"))
MAX_SESSION_ID_CHARS = int(os.getenv("MAX_SESSION_ID_CHARS", "128"))

# Distributed event + queue execution backends
EVENT_BACKEND = os.getenv("EVENT_BACKEND", "redis").lower()  # redis | memory
REDIS_EVENT_STREAM_MAXLEN = int(os.getenv("REDIS_EVENT_STREAM_MAXLEN", "2000"))
REDIS_EVENT_BLOCK_MS = int(os.getenv("REDIS_EVENT_BLOCK_MS", "60000"))

EXECUTION_MODE = os.getenv("EXECUTION_MODE", "direct").lower()  # direct | queued
WORKFLOW_QUEUE_KEY = os.getenv("WORKFLOW_QUEUE_KEY", "agent:workflow:queue")
WORKFLOW_QUEUE_PROCESSING_KEY = os.getenv(
    "WORKFLOW_QUEUE_PROCESSING_KEY",
    "agent:workflow:processing",
)
WORKFLOW_QUEUE_REQUEUE_ON_START = os.getenv("WORKFLOW_QUEUE_REQUEUE_ON_START", "true").lower() == "true"
ENABLE_WORKFLOW_WORKER = os.getenv("ENABLE_WORKFLOW_WORKER", "false").lower() == "true"
WORKFLOW_WORKER_POLL_SECONDS = float(os.getenv("WORKFLOW_WORKER_POLL_SECONDS", "1"))

# Session continuity guard (helps serialize per-session runs across replicas)
SESSION_RUN_GUARD_ENABLED = os.getenv("SESSION_RUN_GUARD_ENABLED", "true").lower() == "true"
SESSION_RUN_GUARD_TTL_SECONDS = int(os.getenv("SESSION_RUN_GUARD_TTL_SECONDS", "14400"))
SESSION_RUN_GUARD_KEY_PREFIX = os.getenv("SESSION_RUN_GUARD_KEY_PREFIX", "agent:session_guard:")

# Optional promotion of finalized chat turns into session-scoped long-term memory.
CHAT_LONG_TERM_MEMORY_ENABLED = os.getenv("CHAT_LONG_TERM_MEMORY_ENABLED", "false").lower() == "true"
CHAT_LONG_TERM_MEMORY_MIN_CHARS = int(os.getenv("CHAT_LONG_TERM_MEMORY_MIN_CHARS", "120"))

# Deployment runtime compatibility (LangSmith-style primitives on local VM)
DEPLOYMENT_STATE_FILE = os.getenv(
    "DEPLOYMENT_STATE_FILE",
    str(pathlib.Path(__file__).resolve().parent / "data" / "deployment_state.json"),
)
DEPLOYMENT_RUNTIME_MODE = os.getenv("DEPLOYMENT_RUNTIME_MODE", "local").strip().lower()  # local | proxy
DEPLOYMENT_PROXY_URL = os.getenv("LANGSMITH_AGENT_SERVER_URL", "").strip().rstrip("/")
DEPLOYMENT_PROXY_API_KEY = (
    os.getenv("LANGSMITH_AGENT_SERVER_API_KEY")
    or os.getenv("LANGSMITH_API_KEY")
    or ""
).strip()

deployment_store = DeploymentRuntimeStore(DEPLOYMENT_STATE_FILE)

graph_run_semaphore = asyncio.Semaphore(MAX_CONCURRENT_GRAPH_RUNS)

# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global global_graph, global_mcp_client, housekeeper_task, workflow_worker_task, deployment_scheduler

    # Startup
    _init_langsmith()  # Initialize LangSmith early (before graph init)
    await db.connect()
    await memory_manager.init()
    await cache.init()  # Initialize Redis cache
    await deployment_store.load()

    housekeeper_stop_event.clear()
    housekeeper_task = asyncio.create_task(_housekeep_runs_loop())
    workflow_worker_stop_event.clear()
    if ENABLE_WORKFLOW_WORKER:
        workflow_worker_task = asyncio.create_task(_workflow_worker_loop())

    scheduler = None
    if db.available:
        try:
            from ingestion.scheduler import setup_scheduler
            scheduler = setup_scheduler(db)
        except Exception as e:
            logger.warning("Ingestion scheduler unavailable: %s", e)

    deployment_scheduler = None
    if AsyncIOScheduler is None or CronTrigger is None:
        logger.warning("Deployment cron scheduler unavailable: APScheduler cron components not installed")
    else:
        try:
            deployment_scheduler = AsyncIOScheduler(timezone=timezone.utc)
            deployment_scheduler.start()
            await _sync_deployment_cron_jobs()
            logger.info("Deployment cron scheduler started")
        except Exception as e:
            deployment_scheduler = None
            logger.warning("Deployment cron scheduler init failed: %s", e)

    print("Initialising LangGraph agent with MCP servers…")
    try:
        global_graph, global_mcp_client, _ = await init_graph(
            memory_manager=memory_manager, db=db,
        )
        print("LangGraph agent ready.")
    except Exception:
        import traceback
        traceback.print_exc()
        raise

    yield

    # Shutdown
    if scheduler:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass
    if deployment_scheduler:
        try:
            deployment_scheduler.shutdown(wait=False)
        except Exception:
            pass
        deployment_scheduler = None

    for run_id, task in list(background_run_tasks.items()):
        if task and not task.done():
            task.cancel()
        background_run_tasks.pop(run_id, None)
    if global_mcp_client:
        print("Shutting down MCP client…")
        await global_mcp_client.cleanup()

    housekeeper_stop_event.set()
    if housekeeper_task:
        try:
            await housekeeper_task
        except Exception:
            pass

    workflow_worker_stop_event.set()
    if workflow_worker_task:
        try:
            await workflow_worker_task
        except Exception:
            pass

    async with event_queues_lock:
        # Hard cleanup on shutdown to avoid stale in-memory state between restarts.
        for run_id in list(run_started_at.keys()):
            await _cleanup_run_locked(run_id)

    await db.close()
    await cache.close()  # Close Redis connection
    await deployment_store.persist()
    _shutdown_langsmith()  # Shutdown LangSmith


app = FastAPI(lifespan=lifespan)

if TracingMiddleware is not None:
    tracing_pref = _parse_bool_env(os.getenv("LANGSMITH_TRACING"))
    tracing_requested = True if tracing_pref is None else tracing_pref
    has_api_key = bool(os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY"))
    if tracing_requested and has_api_key:
        app.add_middleware(TracingMiddleware)
        _langsmith_tracing_middleware_enabled = True
        logger.info("LangSmith TracingMiddleware enabled for distributed trace propagation")
    elif tracing_requested and not has_api_key:
        logger.info("LangSmith TracingMiddleware not enabled: missing LANGSMITH_API_KEY/LANGCHAIN_API_KEY")
else:
    logger.info("LangSmith TracingMiddleware unavailable; install langsmith>=0.3.13")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=CORS_ALLOW_CREDENTIALS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Requested-With",
        "X-User-Id",
        "X-Tenant-Id",
        "langsmith-trace",
        "baggage",
    ],
)


@app.middleware("http")
async def request_size_guard(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                return JSONResponse(
                    {
                        "error": "Request entity too large",
                        "max_request_bytes": MAX_REQUEST_BYTES,
                    },
                    status_code=413,
                )
        except ValueError:
            pass
    return await call_next(request)


@app.middleware("http")
async def langsmith_parent_trace_middleware(request: Request, call_next):
    # TracingMiddleware already handles this path when available.
    if _langsmith_tracing_middleware_enabled or langsmith_tracing_context is None:
        return await call_next(request)

    if not _langsmith_enabled:
        return await call_next(request)

    # Accept parent trace context from upstream services.
    if not request.headers.get("langsmith-trace") and not request.headers.get("baggage"):
        return await call_next(request)

    with langsmith_tracing_context(parent=request.headers):
        return await call_next(request)


@app.middleware("http")
async def auth_context_middleware(request: Request, call_next):
    request.state.auth_context = {
        "user_id": "",
        "tenant_id": "",
        "subject": "",
        "verified": False,
        "source": "none",
    }

    if AUTH_VERIFICATION_MODE == "jwt":
        token = _extract_bearer_token(request)
        if token:
            claims, err = await _verify_jwt_token(token)
            if claims is not None:
                user_id = str(claims.get(JWT_USER_ID_CLAIM, "") or "").strip()
                tenant_id = str(claims.get(JWT_TENANT_ID_CLAIM, "") or "").strip()
                token_sub = str(claims.get(JWT_SUBJECT_CLAIM, "") or "").strip()

                subject = ""
                if user_id and tenant_id:
                    subject = f"tenant:{tenant_id}:user:{user_id}"
                elif user_id:
                    subject = f"user:{user_id}"
                elif tenant_id:
                    subject = f"tenant:{tenant_id}"
                elif token_sub:
                    subject = f"jwt:{token_sub}"

                request.state.auth_context = {
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "subject": subject,
                    "verified": bool(subject),
                    "source": "jwt",
                }
            elif AUTH_REQUIRE_VERIFIED_SUBJECT or not AUTH_ALLOW_HEADER_FALLBACK:
                return JSONResponse(
                    {
                        "error": "Unauthorized",
                        "details": "Bearer token verification failed",
                        "reason": err or "invalid_token",
                    },
                    status_code=401,
                )
            else:
                logger.warning(
                    "JWT verification failed, continuing with fallback subject extraction: %s",
                    err,
                )
        elif AUTH_REQUIRE_VERIFIED_SUBJECT:
            return JSONResponse(
                {
                    "error": "Unauthorized",
                    "details": "Bearer token is required",
                },
                status_code=401,
            )

    return await call_next(request)


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Basic liveness endpoint for orchestrator and health-check utility."""
    return {
        "status": "ok",
        "service": "agent",
        "version": "1.0.0",
    }


@app.get("/ready")
async def ready() -> JSONResponse:
    """Readiness probe for deployment orchestration (k8s/compose/reverse-proxy)."""
    queue_backend_ok = cache.available if EXECUTION_MODE == "queued" else True
    event_backend_ok = cache.available if EVENT_BACKEND == "redis" else True

    checks = {
        "graph": global_graph is not None,
        "db": db.available,
        "cache": cache.available,
        "short_term_memory": memory_manager.short_term_available,
        "long_term_memory": memory_manager.long_term_available,
        "queue_backend": queue_backend_ok,
        "event_backend": event_backend_ok,
        "langsmith": _langsmith_enabled,
    }
    critical_ok = checks["graph"] and checks["db"] and checks["queue_backend"] and checks["event_backend"]
    status = "ready" if critical_ok else "not_ready"
    code = 200 if critical_ok else 503
    return JSONResponse(
        {
            "status": status,
            "checks": checks,
            "timestamp": _now_iso(),
        },
        status_code=code,
    )


@app.get("/api/status")
async def api_status() -> Dict[str, Any]:
    """Detailed status endpoint for frontend dashboards."""
    queue_backend_ok = cache.available if EXECUTION_MODE == "queued" else True
    event_backend_ok = cache.available if EVENT_BACKEND == "redis" else True
    langsmith_endpoint = _langsmith_endpoint()
    langsmith_project = _langsmith_project()
    langsmith_ui_url = _langsmith_ui_base()
    langsmith_dashboard_url = _langsmith_dashboard_url()

    status_messages = {
        "enabled": "Tracing active",
        "missing_api_key": "Set LANGSMITH_API_KEY to enable tracing",
        "disabled_by_env": "Tracing disabled via LANGSMITH_TRACING/LANGCHAIN_TRACING_V2",
        "init_error": "LangSmith initialization failed",
        "not_initialized": "LangSmith not initialized yet",
    }
    
    return {
        "services": {
            "agent": global_graph is not None,
            "database": db.available,
            "cache": cache.available,
            "langsmith": _langsmith_enabled,
            "short_term_memory": memory_manager.short_term_available,
            "long_term_memory": memory_manager.long_term_available,
        },
        "event_tracking": {
            "backend": EVENT_BACKEND,
            "available": event_backend_ok,
            "active_streams": len(run_started_at) if _redis_events_enabled() else len(event_queues),
            "tracked_sessions": len(session_latest_run),
        },
        "langsmith": {
            "enabled": _langsmith_enabled,
            "endpoint": langsmith_endpoint,
            "project": langsmith_project,
            "ui_url": langsmith_ui_url,
            "dashboard_url": langsmith_dashboard_url,
            "tracing_middleware_enabled": _langsmith_tracing_middleware_enabled,
            "reason": _langsmith_status_reason,
            "message": status_messages.get(_langsmith_status_reason, "Unknown status"),
            "last_error": _langsmith_last_error or None,
        },
        "runtime": _runtime_stats(),
        "timestamp": _now_iso(),
    }


@app.post("/api/livekit/token", status_code=201)
async def livekit_token(request: Request) -> JSONResponse:
    """Generate a LiveKit participant token using the standard endpoint contract."""
    api_key = os.getenv("LIVEKIT_API_KEY", "").strip()
    api_secret = os.getenv("LIVEKIT_API_SECRET", "").strip()
    server_url = (os.getenv("LIVEKIT_URL") or LIVEKIT_URL).strip()
    if not api_key or not api_secret or not server_url:
        return JSONResponse(
            {
                "error": "LiveKit not configured",
                "details": "Set LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET",
            },
            status_code=503,
        )

    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}

    room_name = str(body.get("room_name") or LIVEKIT_DEFAULT_ROOM).strip() or LIVEKIT_DEFAULT_ROOM
    room_name = room_name[:128]

    now_epoch = int(time.time())
    participant_identity = str(body.get("participant_identity") or f"web-{now_epoch}").strip()[:128]
    participant_name = str(body.get("participant_name") or "Web User").strip()[:128]
    participant_metadata = str(body.get("participant_metadata") or "")

    raw_attrs = body.get("participant_attributes")
    participant_attributes: Dict[str, str] = {}
    if isinstance(raw_attrs, dict):
        for key, value in raw_attrs.items():
            participant_attributes[str(key)] = str(value)

    try:
        if livekit_api is not None:
            token = (
                livekit_api.AccessToken(api_key, api_secret)
                .with_identity(participant_identity)
                .with_name(participant_name)
                .with_grants(
                    livekit_api.VideoGrants(
                        room_join=True,
                        room=room_name,
                        can_publish=True,
                        can_subscribe=True,
                        can_publish_data=True,
                    )
                )
                .with_ttl(timedelta(seconds=LIVEKIT_TOKEN_TTL_SECONDS))
            )

            if participant_metadata:
                token = token.with_metadata(participant_metadata)
            if participant_attributes:
                token = token.with_attributes(participant_attributes)

            participant_token = token.to_jwt()
        elif jwt is not None:
            now_epoch = int(time.time())
            claims: Dict[str, Any] = {
                "iss": api_key,
                "sub": participant_identity,
                "nbf": now_epoch,
                "exp": now_epoch + LIVEKIT_TOKEN_TTL_SECONDS,
                "video": {
                    "roomJoin": True,
                    "room": room_name,
                    "canPublish": True,
                    "canSubscribe": True,
                    "canPublishData": True,
                },
            }
            if participant_name:
                claims["name"] = participant_name
            if participant_metadata:
                claims["metadata"] = participant_metadata
            if participant_attributes:
                claims["attributes"] = participant_attributes

            encoded = jwt.encode(claims, api_secret, algorithm="HS256")
            participant_token = encoded.decode("utf-8") if isinstance(encoded, bytes) else str(encoded)
        else:
            raise RuntimeError("No token encoder is available")
    except Exception as e:
        logger.exception("Failed to generate LiveKit token")
        return JSONResponse(
            {
                "error": "Failed to generate token",
                "details": str(e),
            },
            status_code=500,
        )

    return JSONResponse(
        {
            "server_url": server_url,
            "participant_token": participant_token,
            "room_name": room_name,
            "participant_identity": participant_identity,
            "ttl_seconds": LIVEKIT_TOKEN_TTL_SECONDS,
        },
        status_code=201,
    )


@app.post("/api/transcribe", status_code=200)
async def transcribe_audio(request: Request) -> JSONResponse:
    """
    Transcribe audio using OpenAI Whisper API.
    
    This endpoint provides speech-to-text for browsers that don't support
    the Web Speech API (Firefox, Safari, Brave with shields).
    
    Request body:
        audio_base64: Base64-encoded audio data (WebM, WAV, MP3, etc.)
        language: Optional language code (default: "en")
    
    Returns:
        text: Transcribed text
        language: Detected or specified language
    """
    import base64
    import io
    
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        return JSONResponse(
            {"error": "Invalid JSON body"},
            status_code=400,
        )
    
    audio_base64 = body.get("audio_base64", "")
    language = str(body.get("language", "en")).strip()[:10]
    
    if not audio_base64:
        return JSONResponse(
            {"error": "Missing audio_base64 field"},
            status_code=400,
        )
    
    # Use OpenRouter for transcription via audio-capable model
    # Try TRANSCRIBE_API_KEY first, then fall back to LLM_API_KEY
    api_key = os.getenv("TRANSCRIBE_API_KEY", "").strip()
    if not api_key:
        api_key = os.getenv("LLM_API_KEY", "").strip()
    
    if not api_key:
        return JSONResponse(
            {
                "error": "Transcription not configured",
                "details": "Set TRANSCRIBE_API_KEY or LLM_API_KEY for audio transcription",
            },
            status_code=503,
        )
    
    try:
        import httpx
        
        # Decode base64 audio to validate it
        audio_bytes = base64.b64decode(audio_base64)
        
        # Validate audio size (max 25MB)
        if len(audio_bytes) > 25 * 1024 * 1024:
            return JSONResponse(
                {"error": "Audio file too large", "details": "Maximum size is 25MB"},
                status_code=400,
            )
        
        if len(audio_bytes) < 100:
            return JSONResponse(
                {"error": "Audio file too small", "details": "Recording may be empty"},
                status_code=400,
            )
        
        # Determine audio format from the data or default to webm
        audio_format = "webm"
        if audio_bytes[:4] == b'RIFF':
            audio_format = "wav"
        elif audio_bytes[:3] == b'ID3' or (audio_bytes[0:2] == b'\xff\xfb'):
            audio_format = "mp3"
        elif audio_bytes[:4] == b'fLaC':
            audio_format = "flac"
        elif audio_bytes[:4] == b'OggS':
            audio_format = "ogg"
        
        # Use OpenRouter's audio transcription via chat completions
        # Using google/gemini-2.5-flash which supports audio input
        transcribe_model = os.getenv("TRANSCRIBE_MODEL", "google/gemini-2.5-flash")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": transcribe_model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Transcribe this audio exactly as spoken. Output ONLY the transcribed text, nothing else. If the audio is empty or unclear, respond with an empty string. Language hint: {language}",
                                },
                                {
                                    "type": "input_audio",
                                    "input_audio": {
                                        "data": audio_base64,
                                        "format": audio_format,
                                    },
                                },
                            ],
                        },
                    ],
                },
            )
            
            if response.status_code == 401:
                return JSONResponse(
                    {"error": "Invalid API key", "details": "Check your TRANSCRIBE_API_KEY or LLM_API_KEY"},
                    status_code=401,
                )
            elif response.status_code == 429:
                return JSONResponse(
                    {"error": "Rate limit exceeded", "details": "Please try again later"},
                    status_code=429,
                )
            elif response.status_code != 200:
                error_detail = response.text[:200] if response.text else "Unknown error"
                logger.error(f"OpenRouter transcription failed: {response.status_code} - {error_detail}")
                return JSONResponse(
                    {"error": "Transcription failed", "details": f"Service returned {response.status_code}"},
                    status_code=500,
                )
            
            result = response.json()
            transcript_text = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            
            return JSONResponse({
                "text": transcript_text,
                "language": language,
            })
        
    except base64.binascii.Error:
        return JSONResponse(
            {"error": "Invalid base64 audio data"},
            status_code=400,
        )
    except httpx.TimeoutException:
        return JSONResponse(
            {"error": "Transcription timeout", "details": "The service took too long to respond"},
            status_code=504,
        )
    except Exception as e:
        logger.exception("Transcription failed")
        error_msg = str(e)
        # Clean up HTML error messages
        if "<html>" in error_msg.lower() or "<!doctype" in error_msg.lower():
            error_msg = "Transcription service returned an error"
        return JSONResponse(
            {"error": "Transcription failed", "details": error_msg},
            status_code=500,
        )


@app.post("/api/tts", status_code=200)
async def synthesize_speech(request: Request) -> Response:
    """
    Generate neural speech audio from text using an OpenAI-compatible /audio/speech API.

    This endpoint is optional and is intended to provide more human-like output than
    browser speech synthesis when configured.

    Request body:
        text: required text to synthesize
        voice: optional override voice name
        model: optional override model name
        format: optional output format (mp3|wav|opus|aac|flac|pcm)
        speed: optional speaking speed (0.25 - 4.0)
        language: optional language hint (not all providers use this)
    """
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    text = str(body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "Missing text field"}, status_code=400)

    if len(text) > 6000:
        return JSONResponse(
            {"error": "Text too long", "details": "Maximum text length is 6000 characters"},
            status_code=400,
        )

    api_key = (os.getenv("TTS_API_KEY") or os.getenv("LLM_API_KEY") or "").strip()
    if not api_key:
        return JSONResponse(
            {
                "error": "Neural TTS not configured",
                "details": "Set TTS_API_KEY (or fallback LLM_API_KEY) to enable /api/tts",
            },
            status_code=503,
        )

    audio_format = str(body.get("format") or TTS_FORMAT).strip().lower()
    if audio_format not in {"mp3", "wav", "opus", "aac", "flac", "pcm"}:
        audio_format = TTS_FORMAT if TTS_FORMAT in {"mp3", "wav", "opus", "aac", "flac", "pcm"} else "mp3"

    voice = str(body.get("voice") or TTS_VOICE).strip() or TTS_VOICE
    model = str(body.get("model") or TTS_MODEL).strip() or TTS_MODEL

    try:
        speed = float(body.get("speed", 1.0))
    except Exception:
        speed = 1.0
    speed = max(0.25, min(4.0, speed))

    language = str(body.get("language") or "").strip()
    instructions = ""
    if language:
        instructions = f"Speak naturally with clear pronunciation in {language}."

    speech_url = f"{TTS_BASE_URL}/audio/speech"
    payload: Dict[str, Any] = {
        "model": model,
        "voice": voice,
        "input": text,
        "response_format": audio_format,
        "speed": speed,
    }
    if instructions:
        payload["instructions"] = instructions

    try:
        async with httpx.AsyncClient(timeout=TTS_TIMEOUT_SECONDS) as client:
            response = await client.post(
                speech_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.status_code == 401:
            return JSONResponse(
                {"error": "Invalid TTS API key", "details": "Check TTS_API_KEY / LLM_API_KEY"},
                status_code=401,
            )

        if response.status_code == 429:
            return JSONResponse(
                {"error": "TTS rate limit exceeded", "details": "Please try again shortly"},
                status_code=429,
            )

        if response.status_code != 200:
            details = response.text[:240] if response.text else f"HTTP {response.status_code}"
            logger.error(f"Neural TTS failed: {response.status_code} - {details}")
            return JSONResponse(
                {"error": "Neural TTS failed", "details": f"Service returned {response.status_code}"},
                status_code=502,
            )

        audio_bytes = response.content
        if not audio_bytes:
            return JSONResponse(
                {"error": "Neural TTS returned empty audio"},
                status_code=502,
            )

        media_types = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "opus": "audio/ogg",
            "aac": "audio/aac",
            "flac": "audio/flac",
            "pcm": "audio/L16",
        }
        media_type = media_types.get(audio_format, "audio/mpeg")

        return Response(
            content=audio_bytes,
            media_type=media_type,
            headers={
                "Cache-Control": "no-store",
                "X-TTS-Model": model,
                "X-TTS-Voice": voice,
            },
        )
    except httpx.TimeoutException:
        return JSONResponse(
            {"error": "Neural TTS timeout", "details": "TTS service took too long to respond"},
            status_code=504,
        )
    except Exception as e:
        logger.exception("Neural TTS generation failed")
        return JSONResponse(
            {"error": "Neural TTS failed", "details": str(e)},
            status_code=500,
        )

# ── Globals ────────────────────────────────────────────────────────────────────

global_graph = None
global_mcp_client = None
event_queues: Dict[str, list[str]] = {}
event_signals: Dict[str, asyncio.Event] = {}
session_latest_run: Dict[str, str] = {}
run_session_index: Dict[str, str] = {}
run_started_at: Dict[str, float] = {}
run_completed_at: Dict[str, float] = {}
run_dropped_events: Dict[str, int] = {}
active_graph_runs = 0
max_active_graph_runs_seen = 0
event_queues_lock = asyncio.Lock()
housekeeper_stop_event = asyncio.Event()
housekeeper_task: Optional[asyncio.Task] = None
workflow_worker_stop_event = asyncio.Event()
workflow_worker_task: Optional[asyncio.Task] = None
_jwt_jwks_client = None
deployment_scheduler: Optional[Any] = None
deployment_cron_job_ids: Dict[str, str] = {}
background_run_tasks: Dict[str, asyncio.Task] = {}
local_session_run_guards: Dict[str, str] = {}
local_session_run_guard_lock = asyncio.Lock()

SPECIALIST_NODES = {"aviation_weather", "hk_weather", "aircraft", "general", "planning"}

_NODE_LABELS: Dict[str, str] = {
    "router":           "Router",
    "aviation_weather": "Aviation Weather",
    "hk_weather":       "HK Weather",
    "aircraft":         "Aircraft Tracking",
    "general":          "General Assistant",
    "planning":         "Multi-Step Planner",
    "plan":             "Plan Builder",
    "execute":          "Plan Step Executor",
    "synthesize":       "Final Synthesizer",
}

PLANNING_INTERNAL_NODES = {"plan", "execute", "synthesize"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _runtime_stats() -> Dict[str, Any]:
    active_streams = len(run_started_at) if _redis_events_enabled() else len(event_queues)
    return {
        "active_graph_runs": active_graph_runs,
        "max_active_graph_runs_seen": max_active_graph_runs_seen,
        "active_event_streams": active_streams,
        "tracked_sessions": len(session_latest_run),
        "run_registry_size": len(run_started_at),
        "dropped_events_total": sum(run_dropped_events.values()),
        "deployment_runtime": {
            "mode": DEPLOYMENT_RUNTIME_MODE,
            "proxy_enabled": bool(DEPLOYMENT_PROXY_URL),
            "assistants": len(deployment_store.assistants),
            "threads": len(deployment_store.threads),
            "runs": len(deployment_store.runs),
            "crons": len(deployment_store.crons),
            "background_runs": len(background_run_tasks),
            "cron_scheduler_active": deployment_scheduler is not None,
            "local_session_run_guards": len(local_session_run_guards),
        },
        "limits": {
            "max_concurrent_graph_runs": MAX_CONCURRENT_GRAPH_RUNS,
            "max_pending_event_streams": MAX_PENDING_EVENT_STREAMS,
            "event_queue_maxsize": EVENT_QUEUE_MAXSIZE,
            "run_registry_ttl_seconds": RUN_REGISTRY_TTL_SECONDS,
            "rate_limit_window_seconds": RATE_LIMIT_WINDOW_SECONDS,
            "rate_limit_agent_per_window": RATE_LIMIT_AGENT_PER_WINDOW,
            "rate_limit_stream_per_window": RATE_LIMIT_STREAM_PER_WINDOW,
            "rate_limit_execute_per_window": RATE_LIMIT_EXECUTE_PER_WINDOW,
            "max_request_bytes": MAX_REQUEST_BYTES,
            "max_input_chars": MAX_INPUT_CHARS,
            "max_session_id_chars": MAX_SESSION_ID_CHARS,
            "event_backend": EVENT_BACKEND,
            "execution_mode": EXECUTION_MODE,
            "workflow_queue_processing_key": WORKFLOW_QUEUE_PROCESSING_KEY,
            "workflow_queue_requeue_on_start": WORKFLOW_QUEUE_REQUEUE_ON_START,
            "session_run_guard_enabled": SESSION_RUN_GUARD_ENABLED,
            "session_run_guard_ttl_seconds": SESSION_RUN_GUARD_TTL_SECONDS,
        },
    }


def _redis_events_enabled() -> bool:
    return EVENT_BACKEND == "redis" and cache.available and getattr(cache, "_redis", None) is not None


def _run_meta_key(run_id: str) -> str:
    return f"runmeta:{run_id}"


def _session_latest_key(session_id: str) -> str:
    return f"session_latest:{session_id}"


def _run_events_stream_key(run_id: str) -> str:
    return f"run_events:{run_id}"


def _safe_session_id(session_id: str) -> str:
    raw = (session_id or "").strip()
    if not raw:
        return f"sess-{uuid.uuid4().hex}"
    return raw[:MAX_SESSION_ID_CHARS]


def _session_run_guard_key(session_id: str) -> str:
    return f"{SESSION_RUN_GUARD_KEY_PREFIX}{session_id}"


async def _acquire_session_run_guard(session_id: str, run_id: str) -> Tuple[bool, str]:
    """Acquire per-session run guard so only one active run executes per session.

    Returns (acquired, holder_run_id).
    """
    if not SESSION_RUN_GUARD_ENABLED or not session_id:
        return True, ""

    run_id = str(run_id or "").strip() or f"guard-{uuid.uuid4().hex}"

    if cache.available and getattr(cache, "_redis", None) is not None:
        key = _session_run_guard_key(session_id)
        try:
            acquired = await cache._redis.set(
                key,
                run_id,
                ex=max(30, SESSION_RUN_GUARD_TTL_SECONDS),
                nx=True,
            )
            if acquired:
                return True, run_id
            holder = await cache._redis.get(key)
            return False, str(holder or "")
        except Exception:
            pass

    async with local_session_run_guard_lock:
        holder = local_session_run_guards.get(session_id, "")
        if holder and holder != run_id:
            return False, holder
        local_session_run_guards[session_id] = run_id
    return True, run_id


async def _release_session_run_guard(session_id: str, run_id: str) -> None:
    if not SESSION_RUN_GUARD_ENABLED or not session_id:
        return

    run_id = str(run_id or "").strip()
    if not run_id:
        return

    if cache.available and getattr(cache, "_redis", None) is not None:
        key = _session_run_guard_key(session_id)
        try:
            holder = await cache._redis.get(key)
            if str(holder or "") == run_id:
                await cache._redis.delete(key)
                return
        except Exception:
            pass

    async with local_session_run_guard_lock:
        holder = local_session_run_guards.get(session_id, "")
        if holder == run_id:
            local_session_run_guards.pop(session_id, None)


def _validate_user_input_text(value: str) -> Optional[JSONResponse]:
    if not value:
        return JSONResponse({"error": "No input provided"}, status_code=400)
    if len(value) > MAX_INPUT_CHARS:
        return JSONResponse(
            {
                "error": "Input too long",
                "max_input_chars": MAX_INPUT_CHARS,
                "actual_input_chars": len(value),
            },
            status_code=400,
        )
    return None


async def _maybe_store_chat_long_term(
    *,
    session_id: str,
    user_input: str,
    response_text: str,
    route: str,
) -> None:
    """Optionally persist finalized chat turns to session long-term memory."""
    if not CHAT_LONG_TERM_MEMORY_ENABLED:
        return
    if not memory_manager.long_term_available:
        return

    turn_text = f"User: {user_input}\nAssistant: {response_text}".strip()
    if len(turn_text) < max(1, CHAT_LONG_TERM_MEMORY_MIN_CHARS):
        return

    try:
        await memory_manager.add_session_knowledge(
            text=turn_text,
            session_id=session_id,
            metadata={
                "source": "chat_turn",
                "route": route,
                "session_id": session_id,
                "stored_at": _now_iso(),
            },
        )
    except Exception as e:
        logger.warning("Failed to store chat turn in long-term memory: %s", e)


def _deployment_proxy_enabled(request: Optional[Request] = None) -> bool:
    if DEPLOYMENT_RUNTIME_MODE == "proxy":
        return True
    if request is None:
        return False
    return str(request.query_params.get("proxy", "")).lower() in ("1", "true", "yes")


async def _proxy_deployment_request(
    request: Request,
    upstream_path: str,
    payload: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    if not DEPLOYMENT_PROXY_URL:
        return JSONResponse(
            {
                "error": "Deployment proxy is not configured",
                "details": "Set LANGSMITH_AGENT_SERVER_URL and optional LANGSMITH_AGENT_SERVER_API_KEY",
            },
            status_code=503,
        )

    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if DEPLOYMENT_PROXY_API_KEY:
        headers["X-Api-Key"] = DEPLOYMENT_PROXY_API_KEY

    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header and "X-Api-Key" not in headers:
        headers["Authorization"] = auth_header

    url = f"{DEPLOYMENT_PROXY_URL}{upstream_path}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                params=params,
                json=payload,
            )
    except Exception as e:
        return JSONResponse(
            {
                "error": "Deployment proxy request failed",
                "details": str(e),
                "upstream_url": url,
            },
            status_code=502,
        )

    try:
        body = response.json()
    except Exception:
        body = {"raw": response.text}
    return JSONResponse(body, status_code=response.status_code)


def _normalize_run_input(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {"messages": []}
    raw = data.get("input", data)
    if isinstance(raw, dict):
        if isinstance(raw.get("messages"), list):
            return raw
        if isinstance(raw.get("content"), str):
            return {"messages": [{"role": "user", "content": raw.get("content", "")}]}
        if isinstance(raw.get("text"), str):
            return {"messages": [{"role": "user", "content": raw.get("text", "")}]}
    if isinstance(raw, str):
        return {"messages": [{"role": "user", "content": raw}]}
    return {"messages": []}


def _extract_user_input_text(input_payload: Dict[str, Any]) -> str:
    if not isinstance(input_payload, dict):
        return ""

    messages = input_payload.get("messages", [])
    if isinstance(messages, list):
        for msg in reversed(messages):
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "")).lower()
            if role in ("user", "human") and msg.get("content") is not None:
                return str(msg.get("content"))
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("content") is not None:
                return str(msg.get("content"))

    fallback = input_payload.get("input") or input_payload.get("query") or input_payload.get("content")
    return str(fallback or "")


def _assistant_runtime_config(assistant: Dict[str, Any]) -> Dict[str, Any]:
    config = assistant.get("config", {}) if isinstance(assistant, dict) else {}
    if not isinstance(config, dict):
        return {}
    return {
        "model": str(config.get("model", "") or "").strip(),
        "base_url": str(config.get("base_url", "") or "").strip(),
        "api_key": str(config.get("api_key", "") or "").strip(),
        "assistant_system_prompt": str(config.get("assistant_system_prompt", "") or "").strip(),
        "forced_route": str(config.get("forced_route", "") or "").strip(),
    }


def _resolve_auth_subject(request: Request) -> Dict[str, str]:
    state_ctx = getattr(request.state, "auth_context", None)
    if isinstance(state_ctx, dict) and state_ctx.get("subject"):
        return {
            "user_id": str(state_ctx.get("user_id", "")),
            "tenant_id": str(state_ctx.get("tenant_id", "")),
            "subject": str(state_ctx.get("subject", "")),
        }

    if AUTH_VERIFICATION_MODE == "jwt" and not AUTH_ALLOW_HEADER_FALLBACK:
        return {"user_id": "", "tenant_id": "", "subject": ""}

    user_id = request.headers.get(AUTH_SUBJECT_USER_HEADER, "").strip()
    tenant_id = request.headers.get(AUTH_SUBJECT_TENANT_HEADER, "").strip()
    if user_id and tenant_id:
        return {"user_id": user_id, "tenant_id": tenant_id, "subject": f"tenant:{tenant_id}:user:{user_id}"}
    if user_id:
        return {"user_id": user_id, "tenant_id": "", "subject": f"user:{user_id}"}
    if tenant_id:
        return {"user_id": "", "tenant_id": tenant_id, "subject": f"tenant:{tenant_id}"}
    return {"user_id": "", "tenant_id": "", "subject": ""}


async def _set_run_metadata(run_id: str, session_id: str) -> None:
    if not _redis_events_enabled():
        return
    payload = {
        "run_id": run_id,
        "session_id": session_id,
        "started_at": _now_iso(),
        "completed": False,
    }
    await cache._redis.setex(_run_meta_key(run_id), RUN_REGISTRY_TTL_SECONDS, json.dumps(payload))


async def _mark_run_completed(run_id: str) -> None:
    if not _redis_events_enabled():
        return
    raw = await cache._redis.get(_run_meta_key(run_id))
    payload: Dict[str, Any] = {}
    if raw:
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {}
    payload.update({"completed": True, "completed_at": _now_iso()})
    await cache._redis.setex(_run_meta_key(run_id), RUN_REGISTRY_TTL_SECONDS, json.dumps(payload))


async def _set_session_latest(session_id: str, run_id: str) -> None:
    if not _redis_events_enabled():
        return
    await cache._redis.setex(_session_latest_key(session_id), RUN_REGISTRY_TTL_SECONDS, run_id)


async def _register_run_stream(run_id: str, session_id: str) -> Optional[JSONResponse]:
    async with event_queues_lock:
        now = time.time()
        stale = [
            rid for rid, started in run_started_at.items()
            if now - (run_completed_at.get(rid, started)) > RUN_REGISTRY_TTL_SECONDS
        ]
        for rid in stale:
            await _cleanup_run_locked(rid)

        current_streams = len(event_queues) if not _redis_events_enabled() else len(run_started_at)
        if current_streams >= MAX_PENDING_EVENT_STREAMS:
            return JSONResponse(
                {
                    "error": "Server busy",
                    "details": "Too many pending workflow streams",
                    "active_event_streams": current_streams,
                    "max_pending_event_streams": MAX_PENDING_EVENT_STREAMS,
                },
                status_code=503,
            )

        if not _redis_events_enabled():
            event_queues[run_id] = []
            event_signals[run_id] = asyncio.Event()
        session_latest_run[session_id] = run_id
        run_session_index[run_id] = session_id
        run_started_at[run_id] = now
        run_dropped_events[run_id] = 0

    await _set_run_metadata(run_id, session_id)
    await _set_session_latest(session_id, run_id)
    return None


async def _get_session_latest(session_id: str) -> str:
    if not _redis_events_enabled():
        return ""
    raw = await cache._redis.get(_session_latest_key(session_id))
    return str(raw or "")


async def _append_redis_event(run_id: str, data: Dict[str, Any]) -> None:
    if not _redis_events_enabled():
        return
    stream_key = _run_events_stream_key(run_id)
    payload = json.dumps(data)
    await cache._redis.xadd(
        stream_key,
        {"payload": payload},
        maxlen=REDIS_EVENT_STREAM_MAXLEN,
        approximate=True,
    )
    await cache._redis.expire(stream_key, RUN_REGISTRY_TTL_SECONDS)


def _extract_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if not auth_header:
        return ""
    parts = auth_header.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1].strip()


def _get_jwks_client() -> Any:
    global _jwt_jwks_client
    if _jwt_jwks_client is None:
        if not JWT_JWKS_URL:
            raise RuntimeError("JWT_JWKS_URL is not configured")
        if PyJWKClient is None:
            raise RuntimeError("PyJWT with JWK support is unavailable")
        _jwt_jwks_client = PyJWKClient(JWT_JWKS_URL)
    return _jwt_jwks_client


def _decode_jwt_token_sync(token: str) -> Dict[str, Any]:
    if jwt is None:
        raise RuntimeError("PyJWT is not installed")

    key: Any
    if JWT_JWKS_URL:
        key = _get_jwks_client().get_signing_key_from_jwt(token).key
    elif JWT_PUBLIC_KEY:
        key = JWT_PUBLIC_KEY
    elif JWT_SECRET:
        key = JWT_SECRET
    else:
        raise RuntimeError("No JWT key material configured (set JWT_JWKS_URL, JWT_PUBLIC_KEY, or JWT_SECRET)")

    decode_kwargs: Dict[str, Any] = {
        "algorithms": JWT_ALGORITHMS or ["RS256"],
        "leeway": JWT_LEEWAY_SECONDS,
    }
    if JWT_ISSUER:
        decode_kwargs["issuer"] = JWT_ISSUER
    if JWT_AUDIENCE:
        decode_kwargs["audience"] = JWT_AUDIENCE
    else:
        decode_kwargs["options"] = {"verify_aud": False}

    return jwt.decode(token, key=key, **decode_kwargs)


async def _verify_jwt_token(token: str) -> Tuple[Optional[Dict[str, Any]], str]:
    if AUTH_VERIFICATION_MODE != "jwt":
        return None, "jwt_verification_disabled"
    try:
        claims = await asyncio.to_thread(_decode_jwt_token_sync, token)
        return claims, ""
    except InvalidTokenError as e:
        return None, str(e)
    except Exception as e:
        logger.warning("JWT verification error: %s", e)
        return None, str(e)


def _client_identity(request: Request, session_id: str = "") -> str:
    auth = _resolve_auth_subject(request)
    if auth.get("subject"):
        return auth["subject"]

    if session_id:
        return f"session:{session_id}"

    if RATE_LIMIT_USE_CLIENT_IP:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            ip = xff.split(",")[0].strip()
            if ip:
                return f"ip:{ip}"
        if request.client and request.client.host:
            return f"ip:{request.client.host}"

    return "anon"


async def _enforce_rate_limit(
    request: Request,
    bucket: str,
    limit: int,
    session_id: str = "",
) -> Optional[JSONResponse]:
    auth = _resolve_auth_subject(request)
    if (REQUIRE_AUTH_SUBJECT or AUTH_REQUIRE_VERIFIED_SUBJECT) and not auth.get("subject"):
        return JSONResponse(
            {
                "error": "Unauthorized",
                "details": "Authenticated subject is required",
                "auth_mode": AUTH_VERIFICATION_MODE,
                "required_headers": [AUTH_SUBJECT_USER_HEADER, AUTH_SUBJECT_TENANT_HEADER],
            },
            status_code=401,
        )

    if not ENABLE_ENDPOINT_RATE_LIMITING:
        return None

    identity = _client_identity(request, session_id=session_id)
    decision = await cache.check_rate_limit(
        bucket=bucket,
        subject=identity,
        limit=limit,
        window_seconds=RATE_LIMIT_WINDOW_SECONDS,
    )

    if decision.get("allowed", True):
        return None

    retry_after = int(decision.get("retry_after", RATE_LIMIT_WINDOW_SECONDS))
    payload = {
        "error": "Too Many Requests",
        "bucket": bucket,
        "limit": decision.get("limit", limit),
        "window_seconds": decision.get("window_seconds", RATE_LIMIT_WINDOW_SECONDS),
        "retry_after": retry_after,
        "remaining": decision.get("remaining", 0),
    }
    return JSONResponse(payload, status_code=429, headers={"Retry-After": str(retry_after)})


async def _cleanup_run_locked(run_id: str) -> None:
    event_queues.pop(run_id, None)
    event_signals.pop(run_id, None)
    run_started_at.pop(run_id, None)
    run_completed_at.pop(run_id, None)
    run_dropped_events.pop(run_id, None)
    resolved_session = run_session_index.pop(run_id, None)
    if resolved_session and session_latest_run.get(resolved_session) == run_id:
        session_latest_run.pop(resolved_session, None)

    if _redis_events_enabled():
        try:
            await cache._redis.delete(_run_meta_key(run_id))
            await cache._redis.delete(_run_events_stream_key(run_id))
            if resolved_session:
                latest = await cache._redis.get(_session_latest_key(resolved_session))
                if latest == run_id:
                    await cache._redis.delete(_session_latest_key(resolved_session))
        except Exception as e:
            logger.debug("Run cleanup redis error for %s: %s", run_id, e)


async def _cleanup_stale_runs(now_ts: Optional[float] = None) -> int:
    now = now_ts if now_ts is not None else time.time()
    stale: list[str] = []

    async with event_queues_lock:
        for run_id, started in run_started_at.items():
            completed = run_completed_at.get(run_id)
            ref = completed if completed is not None else started
            if now - ref > RUN_REGISTRY_TTL_SECONDS:
                stale.append(run_id)

        for run_id in stale:
            await _cleanup_run_locked(run_id)

    return len(stale)


async def _housekeep_runs_loop() -> None:
    while not housekeeper_stop_event.is_set():
        try:
            await asyncio.wait_for(
                housekeeper_stop_event.wait(),
                timeout=RUN_REGISTRY_CLEANUP_INTERVAL_SECONDS,
            )
        except asyncio.TimeoutError:
            removed = await _cleanup_stale_runs()
            if removed:
                logger.info("Housekeeper removed %d stale run(s)", removed)


async def _enqueue_workflow_job(run_id: str, session_id: str, user_input: str) -> bool:
    if not cache.available or getattr(cache, "_redis", None) is None:
        return False
    job = {
        "run_id": run_id,
        "session_id": session_id,
        "user_input": user_input,
        "enqueued_at": _now_iso(),
        "attempt": 0,
    }
    try:
        await cache._redis.lpush(WORKFLOW_QUEUE_KEY, json.dumps(job))
        return True
    except Exception as e:
        logger.warning("Failed to enqueue workflow job %s: %s", run_id, e)
        return False


async def _requeue_processing_jobs_on_start() -> int:
    """Move abandoned jobs back to the pending queue at worker startup."""
    if not cache.available or getattr(cache, "_redis", None) is None:
        return 0

    moved = 0
    while True:
        raw = await cache._redis.rpop(WORKFLOW_QUEUE_PROCESSING_KEY)
        if not raw:
            break
        await cache._redis.lpush(WORKFLOW_QUEUE_KEY, raw)
        moved += 1
    return moved


async def _workflow_worker_loop() -> None:
    if not cache.available or getattr(cache, "_redis", None) is None:
        logger.warning("Workflow worker requested but Redis cache is unavailable")
        return

    if WORKFLOW_QUEUE_REQUEUE_ON_START:
        moved = await _requeue_processing_jobs_on_start()
        if moved:
            logger.info("Workflow worker recovered %d abandoned job(s)", moved)

    logger.info("Workflow worker started (queue=%s)", WORKFLOW_QUEUE_KEY)
    while not workflow_worker_stop_event.is_set():
        try:
            raw_payload = await cache._redis.brpoplpush(
                WORKFLOW_QUEUE_KEY,
                WORKFLOW_QUEUE_PROCESSING_KEY,
                timeout=5,
            )
            if not raw_payload:
                await asyncio.sleep(WORKFLOW_WORKER_POLL_SECONDS)
                continue

            try:
                job = json.loads(raw_payload)
            except Exception:
                logger.warning("Skipping invalid workflow queue payload")
                await cache._redis.lrem(WORKFLOW_QUEUE_PROCESSING_KEY, 1, raw_payload)
                continue

            run_id = str(job.get("run_id", "")).strip()
            session_id = _safe_session_id(str(job.get("session_id", "")).strip())
            user_input = str(job.get("user_input", ""))
            attempt = int(job.get("attempt", 0) or 0)

            if not run_id or not user_input:
                logger.warning("Skipping workflow job with missing run_id/user_input")
                await cache._redis.lrem(WORKFLOW_QUEUE_PROCESSING_KEY, 1, raw_payload)
                continue

            acquired, holder = await _acquire_session_run_guard(session_id, run_id)
            if not acquired:
                # Another run for the same session is active. Requeue for retry.
                job["attempt"] = attempt + 1
                job["requeued_at"] = _now_iso()
                await cache._redis.lrem(WORKFLOW_QUEUE_PROCESSING_KEY, 1, raw_payload)
                await cache._redis.rpush(WORKFLOW_QUEUE_KEY, json.dumps(job))
                await asyncio.sleep(min(2.0, WORKFLOW_WORKER_POLL_SECONDS + 0.2))
                logger.info(
                    "Workflow job %s deferred; session %s busy with run %s",
                    run_id,
                    session_id,
                    holder or "unknown",
                )
                continue

            try:
                await _run_with_events(
                    user_input,
                    session_id,
                    event_key=run_id,
                    session_guard_owner=run_id,
                )
            finally:
                await cache._redis.lrem(WORKFLOW_QUEUE_PROCESSING_KEY, 1, raw_payload)
        except Exception as e:
            logger.exception("Workflow worker loop error: %s", e)
            await asyncio.sleep(WORKFLOW_WORKER_POLL_SECONDS)


def _extract_planning_data(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract planning metadata from graph result payload or final AI message."""
    if not result:
        return None

    planning_data = result.get("planning_data")
    if isinstance(planning_data, dict):
        return planning_data

    messages = result.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            maybe = getattr(msg, "additional_kwargs", {}).get("planning")
            if isinstance(maybe, dict):
                return maybe
    return None


# ── LangSmith config helpers ──────────────────────────────────────────────────


def _build_config(
    session_id: str,
    trace_name: str = "",
    user_id: str = "",
    assistant_id: str = "",
    assistant_config: Optional[Dict[str, Any]] = None,
) -> dict:
    """
    Build LangGraph config with thread_id and LangSmith metadata.

    LangSmith captures config metadata/tags automatically when tracing is enabled.
    """
    metadata: Dict[str, Any] = {
        "session_id": session_id,
        "thread_id": session_id,
        "conversation_id": session_id,
        "trace_name": trace_name or session_id[:80],
    }
    tags = ["aviation-agent", "langgraph"]

    if session_id:
        tags.append(f"session:{session_id[:16]}")

    if user_id:
        metadata["user_id"] = user_id
        tags.append("has-user")

    if assistant_id:
        metadata["assistant_id"] = assistant_id
        tags.append(f"assistant:{assistant_id[:16]}")

    assistant_config = assistant_config or {}
    runtime_overrides: Dict[str, Any] = {}
    for key in ("model", "base_url", "api_key", "assistant_system_prompt", "forced_route"):
        raw = assistant_config.get(key)
        if raw is None:
            continue
        value = str(raw).strip()
        if value:
            runtime_overrides[key] = value
            metadata[f"assistant_{key}"] = value if key != "api_key" else "provided"

    cfg: dict = {
        "configurable": {"thread_id": session_id, **runtime_overrides},
        "metadata": metadata,
        "tags": tags,
    }
    if trace_name:
        cfg["run_name"] = trace_name[:80]
    return cfg


# ── Workflow-event SSE helpers ─────────────────────────────────────────────────

async def _push(session_id: str, data: Dict[str, Any]) -> None:
    if _redis_events_enabled():
        try:
            await _append_redis_event(session_id, data)
            return
        except Exception as e:
            logger.debug("Redis event push failed for %s: %s", session_id, e)

    buffer = event_queues.get(session_id)
    if buffer is not None:
        payload = json.dumps(data)
        if len(buffer) >= EVENT_QUEUE_MAXSIZE:
            # Keep latest events while allowing all subscribers to replay consistently.
            drop_count = len(buffer) - EVENT_QUEUE_MAXSIZE + 1
            del buffer[:drop_count]
            run_dropped_events[session_id] = run_dropped_events.get(session_id, 0) + drop_count
        buffer.append(payload)
        signal = event_signals.get(session_id)
        if signal is not None:
            signal.set()


def _fmt_input(raw: Any) -> str:
    """Short readable summary of a tool-input dict."""
    if isinstance(raw, dict):
        parts = [f"{k}={repr(v)[:40]}" for k, v in list(raw.items())[:4]]
        return ", ".join(parts)
    return str(raw)[:100]


def _tool_call_names(tool_calls: list) -> str:
    """Return a comma-separated string of tool call names."""
    names = []
    for tc in tool_calls[:6]:  # cap at 6
        if isinstance(tc, dict):
            names.append(tc.get("name", "?"))
        elif hasattr(tc, "name"):
            names.append(tc.name)
    return ", ".join(names)


def _event_trace_fields(ev: Dict[str, Any]) -> Dict[str, Any]:
    run_id = str(ev.get("run_id") or "").strip()
    parent_ids = ev.get("parent_ids") or []
    parent_run_id = ""
    if isinstance(parent_ids, list) and parent_ids:
        parent_run_id = str(parent_ids[-1] or "").strip()

    data: Dict[str, Any] = {}
    if run_id:
        data["run_id"] = run_id
    if parent_run_id:
        data["parent_run_id"] = parent_run_id
    return data


@traceable(name="server.workflow_events", run_type="chain")
async def _run_with_events(
    user_input: str,
    session_id: str,
    event_key: Optional[str] = None,
    assistant_id: str = "",
    assistant_config: Optional[Dict[str, Any]] = None,
    session_guard_owner: str = "",
) -> str:
    """Run graph and push rich SSE workflow events into the session queue."""
    global active_graph_runs, max_active_graph_runs_seen

    graph_session_id = session_id
    session_id = event_key or session_id

    if not global_graph:
        await _push(session_id, {
            "nodeId": "error", "event_type": "error",
            "status": "failed", "details": "Agent not initialised",
            "timestamp": _now_iso(), "raw": {},
        })
        await _push(session_id, {"__done__": True})
        return ""

    config = _build_config(
        graph_session_id,
        trace_name=user_input[:80],
        assistant_id=assistant_id,
        assistant_config=assistant_config,
    )
    active_nodes: set[str] = set()
    node_start: dict[str, float] = {}
    tool_start: dict[str, float] = {}
    current_specialist: str = ""
    routing_emitted: bool = False
    router_started_at: float = 0.0

    # Per-session step tracking (counts LLM → tool-call rounds in a specialist)
    step_counts: dict[str, int] = {}   # keyed by specialist node name
    final_response_text = ""

    INTERNAL = {"agent", "tools", *PLANNING_INTERNAL_NODES}
    INTERNAL_LABELS = {"agent": "LLM Call", "tools": "Tool Execution"}

    await graph_run_semaphore.acquire()
    active_graph_runs += 1
    if active_graph_runs > max_active_graph_runs_seen:
        max_active_graph_runs_seen = active_graph_runs

    try:
        request_id = f"{graph_session_id}:{uuid.uuid4().hex}"
        mcp_module.set_request_context(request_id)

        trace_context = _langsmith_trace_context()
        if trace_context:
            run_tree = get_current_run_tree()
            distributed_headers: Dict[str, Any] = {}
            if run_tree and hasattr(run_tree, "to_headers"):
                try:
                    distributed_headers = run_tree.to_headers() or {}
                except Exception:
                    distributed_headers = {}

            await _push(session_id, {
                "nodeId": "langsmith",
                "event_type": "trace_context",
                "status": "started",
                "label": "LangSmith Trace",
                "details": "Trace context initialized for this run",
                "timestamp": _now_iso(),
                "distributed_headers": distributed_headers,
                **trace_context,
                "raw": {
                    "trace_context": trace_context,
                    "distributed_headers": distributed_headers,
                },
            })

        async for ev in global_graph.astream_events(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
            version="v2",
        ):
            kind    = ev.get("event", "")
            meta    = ev.get("metadata", {})
            node    = meta.get("langgraph_node", "")
            ts      = _now_iso()
            trace_fields = _event_trace_fields(ev)

            # ── Node started ───────────────────────────────────────────────────
            if kind == "on_chain_start" and node and node not in active_nodes:
                active_nodes.add(node)
                node_start[node] = time.monotonic()
                if node == "router":
                    router_started_at = time.monotonic()

                if node in SPECIALIST_NODES:
                    current_specialist = node
                    step_counts[node] = 0
                    if not routing_emitted:
                        routing_emitted = True
                        router_dur = int(
                            (time.monotonic() - router_started_at) * 1000
                        ) if router_started_at else 0
                        await _push(session_id, {
                            "nodeId": "router",
                            "event_type": "routing_decision",
                            "status": "completed",
                            "label": f"Router → {node}",
                            "details": f"Query classified as: {node}",
                            "route": node,
                            "duration_ms": router_dur,
                            "timestamp": ts,
                            **trace_fields,
                            "raw": {"node": "router", "route": node},
                        })

                label      = INTERNAL_LABELS.get(node) or _NODE_LABELS.get(node, node)
                event_type = "internal" if node in INTERNAL else "node"
                await _push(session_id, {
                    "nodeId":      node,
                    "event_type":  event_type,
                    "status":      "started",
                    "label":       label,
                    "details":     f"{label}: processing…",
                    "parent_node": current_specialist if node in INTERNAL else None,
                    "timestamp":   ts,
                    **trace_fields,
                    "raw":         {"node": node},
                })

            # ── Node completed ─────────────────────────────────────────────────
            elif kind == "on_chain_end" and node and node in active_nodes:
                active_nodes.discard(node)
                duration_ms = int(
                    (time.monotonic() - node_start.pop(node, time.monotonic())) * 1000
                )
                if node in SPECIALIST_NODES:
                    total_steps = step_counts.pop(node, 0)
                    current_specialist = ""

                label      = INTERNAL_LABELS.get(node) or _NODE_LABELS.get(node, node)
                event_type = "internal" if node in INTERNAL else "node"

                if node != "router" or not routing_emitted:
                    steps_note = ""
                    if node in SPECIALIST_NODES:
                        steps_note = f" ({total_steps} reasoning step{'s' if total_steps != 1 else ''})"
                    await _push(session_id, {
                        "nodeId":      node,
                        "event_type":  event_type,
                        "status":      "completed",
                        "label":       label,
                        "details":     f"{label} finished{steps_note}.",
                        "parent_node": current_specialist if node in INTERNAL else None,
                        "duration_ms": duration_ms,
                        "timestamp":   ts,
                        **trace_fields,
                        "raw":         {"node": node, "steps": total_steps if node in SPECIALIST_NODES else None},
                    })

                # Emit plan details when the planner node completes.
                if node == "plan":
                    raw_output = ev.get("data", {}).get("output", {})
                    output = raw_output if isinstance(raw_output, dict) else {}
                    plan_steps = output.get("original_plan") or output.get("plan") or []
                    if plan_steps:
                        await _push(session_id, {
                            "nodeId": "planning",
                            "event_type": "plan",
                            "status": "completed",
                            "label": "Execution Plan",
                            "details": f"Generated {len(plan_steps)} steps",
                            "steps": plan_steps,
                            "timestamp": ts,
                            **trace_fields,
                            "raw": {"steps": plan_steps},
                        })

            # ── LLM completed a generation (reasoning event) ───────────────────
            elif kind == "on_chat_model_end" and node and node not in ("router",):
                output     = ev["data"].get("output")
                tool_calls = []
                content    = ""

                if output is not None:
                    if hasattr(output, "tool_calls"):
                        tool_calls = output.tool_calls or []
                    if hasattr(output, "content"):
                        content = output.content or ""
                    # Some models return generations list
                    elif hasattr(output, "generations"):
                        for gen_list in output.generations:
                            for gen in gen_list:
                                msg = getattr(gen, "message", None)
                                if msg:
                                    tool_calls = getattr(msg, "tool_calls", []) or tool_calls
                                    content    = getattr(msg, "content", "") or content

                parent = current_specialist or node

                if tool_calls:
                    # LLM decided to make tool calls → planning step
                    n   = len(tool_calls)
                    tc_names = _tool_call_names(tool_calls)
                    step_num = step_counts.get(parent, 0) + 1
                    step_counts[parent] = step_num
                    await _push(session_id, {
                        "nodeId":      node,
                        "event_type":  "reasoning",
                        "status":      "completed",
                        "label":       f"Step {step_num}: Planning",
                        "details":     f"Planned {n} tool call{'s' if n != 1 else ''}: {tc_names}",
                        "parent_node": parent if parent != node else None,
                        "step":        step_num,
                        "timestamp":   ts,
                        **trace_fields,
                        "raw":         {
                            "node":       node,
                            "step":       step_num,
                            "tool_calls": [
                                (tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "?"))
                                for tc in tool_calls
                            ],
                        },
                    })
                elif content:
                    # LLM generated a final response → synthesis step
                    final_response_text = str(content)
                    step_num = step_counts.get(parent, 0) + 1
                    step_counts[parent] = step_num
                    preview  = content[:120].replace("\n", " ")
                    await _push(session_id, {
                        "nodeId":      node,
                        "event_type":  "reasoning",
                        "status":      "completed",
                        "label":       f"Step {step_num}: Synthesis",
                        "details":     f"Final answer: {preview}{'…' if len(content) > 120 else ''}",
                        "parent_node": parent if parent != node else None,
                        "step":        step_num,
                        "timestamp":   ts,
                        **trace_fields,
                        "raw":         {
                            "node":    node,
                            "step":    step_num,
                            "preview": preview,
                        },
                    })

            # ── Tool call started ─────────────────────────────────────────────
            elif kind == "on_tool_start":
                tool_name  = ev.get("name", "tool")
                tool_input = ev["data"].get("input", {})
                tool_start[tool_name] = time.monotonic()
                parent     = current_specialist or meta.get("langgraph_node", "")

                await _push(session_id, {
                    "nodeId":      tool_name,
                    "event_type":  "tool",
                    "status":      "started",
                    "label":       tool_name,
                    "details":     f"Calling {tool_name}({_fmt_input(tool_input)})",
                    "tool_input":  tool_input if isinstance(tool_input, dict) else {},
                    "parent_node": parent,
                    "timestamp":   ts,
                    **trace_fields,
                    "raw":         {"tool": tool_name, "input": tool_input, "parent": parent},
                })

            # ── Tool call completed ───────────────────────────────────────────
            elif kind == "on_tool_end":
                tool_name   = ev.get("name", "tool")
                duration_ms = int(
                    (time.monotonic() - tool_start.pop(tool_name, time.monotonic())) * 1000
                )
                output          = ev["data"].get("output", "")
                output_str      = str(output) if output else ""
                output_preview  = output_str[:200]
                output_chars    = len(output_str)
                parent          = current_specialist or meta.get("langgraph_node", "")

                await _push(session_id, {
                    "nodeId":       tool_name,
                    "event_type":   "tool",
                    "status":       "completed",
                    "label":        tool_name,
                    "details":      (
                        f"{tool_name} → {output_preview[:80]}"
                        f"{'…' if len(output_preview) > 80 else ''}"
                        f"  ({output_chars} chars)"
                    ),
                    "parent_node":  parent,
                    "duration_ms":  duration_ms,
                    "timestamp":    ts,
                    **trace_fields,
                    "raw":          {
                        "tool":           tool_name,
                        "output_preview": output_preview,
                        "output_chars":   output_chars,
                        "parent":         parent,
                    },
                })

    except Exception as e:
        logger.exception("Orchestration error for session %s", graph_session_id)
        await _push(session_id, {
            "nodeId": "error", "event_type": "error", "status": "failed",
            "details": f"Error: {e}", "timestamp": _now_iso(), "raw": {"error": str(e)},
        })
    finally:
        if active_graph_runs > 0:
            active_graph_runs -= 1
        graph_run_semaphore.release()
        async with event_queues_lock:
            run_completed_at[session_id] = time.time()
        await _mark_run_completed(session_id)
        if session_guard_owner:
            await _release_session_run_guard(graph_session_id, session_guard_owner)
        mcp_module.clear_request_context()
        await _push(session_id, {"__done__": True})
    return final_response_text


TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}


async def _deployment_background_run_task(
    run_id: str,
    thread_id: str,
    assistant_id: str,
    assistant_config: Dict[str, Any],
    user_input: str,
    cleanup_thread_on_complete: bool = False,
) -> None:
    await deployment_store.update_run(run_id, status="running")
    await deployment_store.append_thread_message(thread_id, "human", user_input, run_id=run_id)

    if db.available:
        await db.save_conversation(
            thread_id,
            "human",
            user_input,
            metadata={"run_id": run_id, "assistant_id": assistant_id, "source": "deployment"},
        )

    try:
        response_text = await _run_with_events(
            user_input=user_input,
            session_id=thread_id,
            event_key=run_id,
            assistant_id=assistant_id,
            assistant_config=assistant_config,
            session_guard_owner=run_id,
        )

        if response_text:
            await deployment_store.append_thread_message(thread_id, "assistant", response_text, run_id=run_id)
            if db.available:
                await db.save_conversation(
                    thread_id,
                    "ai",
                    response_text,
                    metadata={"run_id": run_id, "assistant_id": assistant_id, "source": "deployment"},
                )

        await deployment_store.update_run(
            run_id,
            status="completed",
            output={"message": response_text or "", "thread_id": thread_id, "assistant_id": assistant_id},
            error=None,
        )
    except asyncio.CancelledError:
        await deployment_store.update_run(
            run_id,
            status="cancelled",
            error="Run cancelled by user",
        )
        await _push(
            run_id,
            {
                "nodeId": "run",
                "event_type": "run",
                "status": "cancelled",
                "label": "Run Cancelled",
                "details": "Execution cancelled by user",
                "timestamp": _now_iso(),
                "raw": {"run_id": run_id},
            },
        )
        await _push(run_id, {"__done__": True})
        raise
    except Exception as e:
        await deployment_store.update_run(run_id, status="failed", error=str(e))
        await _push(
            run_id,
            {
                "nodeId": "run",
                "event_type": "error",
                "status": "failed",
                "label": "Run Failed",
                "details": str(e),
                "timestamp": _now_iso(),
                "raw": {"run_id": run_id, "error": str(e)},
            },
        )
    finally:
        await _release_session_run_guard(thread_id, run_id)
        background_run_tasks.pop(run_id, None)
        if cleanup_thread_on_complete:
            await deployment_store.delete_thread(thread_id)


async def _start_deployment_background_run(
    thread_id: str,
    assistant_ref: str,
    input_payload: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
    mode: str = "background",
    cleanup_thread_on_complete: bool = False,
) -> Tuple[Optional[Dict[str, Any]], Optional[JSONResponse]]:
    thread = await deployment_store.get_thread(thread_id)
    if not thread:
        return None, JSONResponse({"error": f"Thread not found: {thread_id}"}, status_code=404)

    assistant = await deployment_store.resolve_assistant(assistant_ref)
    if not assistant:
        return None, JSONResponse({"error": f"Assistant not found: {assistant_ref}"}, status_code=404)

    user_input = _extract_user_input_text(input_payload)
    invalid_input = _validate_user_input_text(user_input)
    if invalid_input:
        return None, invalid_input

    assistant_id = str(assistant.get("assistant_id", "")).strip()
    run = await deployment_store.create_run(
        thread_id=thread_id,
        assistant_id=assistant_id,
        input_payload=input_payload,
        metadata=metadata or {},
        mode=mode,
        status="queued",
    )

    run_id = str(run.get("run_id", "")).strip()

    acquired, holder = await _acquire_session_run_guard(thread_id, run_id)
    if not acquired:
        await deployment_store.update_run(
            run_id,
            status="failed",
            error=f"Thread already has an active run: {holder or 'unknown'}",
        )
        return None, JSONResponse(
            {
                "error": "Thread already has an active run",
                "thread_id": thread_id,
                "active_run_id": holder or None,
            },
            status_code=409,
        )

    stream_state_error = await _register_run_stream(run_id=run_id, session_id=thread_id)
    if stream_state_error:
        await deployment_store.update_run(run_id, status="failed", error="Unable to allocate event stream")
        await _release_session_run_guard(thread_id, run_id)
        return None, stream_state_error

    assistant_config = _assistant_runtime_config(assistant)
    task = asyncio.create_task(
        _deployment_background_run_task(
            run_id=run_id,
            thread_id=thread_id,
            assistant_id=assistant_id,
            assistant_config=assistant_config,
            user_input=user_input,
            cleanup_thread_on_complete=cleanup_thread_on_complete,
        )
    )
    background_run_tasks[run_id] = task

    return await deployment_store.get_run(run_id), None


async def _remove_deployment_cron_job(cron_id: str) -> None:
    job_id = deployment_cron_job_ids.pop(cron_id, None)
    if deployment_scheduler and job_id:
        try:
            deployment_scheduler.remove_job(job_id)
        except Exception:
            pass
    await deployment_store.set_cron_next_run(cron_id, None)


async def _register_deployment_cron_job(cron: Dict[str, Any]) -> bool:
    if not deployment_scheduler or CronTrigger is None:
        return False

    cron_id = str(cron.get("cron_id", "")).strip()
    if not cron_id:
        return False

    await _remove_deployment_cron_job(cron_id)

    schedule = str(cron.get("schedule", "")).strip()
    if not schedule:
        return False

    try:
        trigger = CronTrigger.from_crontab(schedule, timezone=timezone.utc)
    except Exception as e:
        logger.warning("Invalid cron schedule for %s: %s", cron_id, e)
        return False

    def _dispatch(c_id: str = cron_id) -> None:
        asyncio.create_task(_fire_deployment_cron_job(c_id))

    job_id = f"deployment-cron:{cron_id}"
    deployment_scheduler.add_job(
        _dispatch,
        trigger=trigger,
        id=job_id,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    deployment_cron_job_ids[cron_id] = job_id

    next_run_at = None
    try:
        job = deployment_scheduler.get_job(job_id)
        if job and job.next_run_time:
            next_run_at = job.next_run_time.isoformat()
    except Exception:
        next_run_at = None

    await deployment_store.set_cron_next_run(cron_id, next_run_at)
    return True


async def _sync_deployment_cron_jobs() -> None:
    if not deployment_scheduler:
        return

    for cron_id in list(deployment_cron_job_ids.keys()):
        await _remove_deployment_cron_job(cron_id)

    crons = await deployment_store.search_crons(limit=10_000, offset=0)
    for cron in crons:
        if cron.get("active"):
            await _register_deployment_cron_job(cron)


async def _fire_deployment_cron_job(cron_id: str) -> None:
    cron = await deployment_store.get_cron(cron_id)
    if not cron or not cron.get("active"):
        return

    assistant_ref = str(cron.get("assistant_id", "")).strip() or "agent"
    input_payload = cron.get("input", {})
    configured_thread_id = str(cron.get("thread_id") or "").strip()
    transient_thread = False

    thread_id = configured_thread_id
    if not thread_id:
        thread = await deployment_store.create_thread(
            metadata={"created_by": "cron", "cron_id": cron_id},
            config={},
            values=None,
        )
        thread_id = str(thread.get("thread_id", ""))
        transient_thread = True

    run_metadata = dict(cron.get("metadata") or {})
    run_metadata["cron_id"] = cron_id

    cleanup_thread = transient_thread and str(cron.get("on_run_completed", "delete")) == "delete"
    run, error_response = await _start_deployment_background_run(
        thread_id=thread_id,
        assistant_ref=assistant_ref,
        input_payload=input_payload if isinstance(input_payload, dict) else {},
        metadata=run_metadata,
        mode="cron",
        cleanup_thread_on_complete=cleanup_thread,
    )
    if error_response:
        logger.warning("Cron %s failed to start run: %s", cron_id, error_response.body)
        return

    next_run_at = None
    job_id = deployment_cron_job_ids.get(cron_id)
    if deployment_scheduler and job_id:
        job = deployment_scheduler.get_job(job_id)
        if job and job.next_run_time:
            next_run_at = job.next_run_time.isoformat()

    await deployment_store.mark_cron_run(cron_id, str(run.get("run_id", "")), next_run_at=next_run_at)


# ── POST /api/agent/execute ────────────────────────────────────────────────────

@app.post("/api/agent/execute")
async def execute_workflow(request: Request):
    data       = await request.json()
    user_input = str(data.get("input", ""))
    invalid_input = _validate_user_input_text(user_input)
    if invalid_input:
        return invalid_input

    session_id = _safe_session_id(str(data.get("session_id") or f"sess-{uuid.uuid4().hex}"))
    run_id = str(data.get("run_id") or f"{session_id}:{uuid.uuid4().hex}")[:256]

    rate_limited = await _enforce_rate_limit(
        request,
        bucket="agent_execute",
        limit=RATE_LIMIT_EXECUTE_PER_WINDOW,
        session_id=session_id,
    )
    if rate_limited:
        return rate_limited

    if not global_graph:
        return JSONResponse({"error": "Agent not initialised"}, status_code=500)

    stream_state_error = await _register_run_stream(run_id=run_id, session_id=session_id)
    if stream_state_error:
        return stream_state_error

    if EXECUTION_MODE == "queued":
        queued = await _enqueue_workflow_job(run_id, session_id, user_input)
        if not queued:
            return JSONResponse(
                {
                    "error": "Queue unavailable",
                    "details": "Queued execution mode requires Redis availability",
                },
                status_code=503,
            )
        return JSONResponse(
            {
                "status": "queued",
                "mode": "queued",
                "session_id": session_id,
                "run_id": run_id,
            }
        )

    acquired, holder = await _acquire_session_run_guard(session_id, run_id)
    if not acquired:
        async with event_queues_lock:
            await _cleanup_run_locked(run_id)
        return JSONResponse(
            {
                "error": "Session already has an active run",
                "session_id": session_id,
                "active_run_id": holder or None,
            },
            status_code=409,
        )

    asyncio.create_task(
        _run_with_events(
            user_input,
            session_id,
            event_key=run_id,
            session_guard_owner=run_id,
        )
    )
    return JSONResponse({
        "status": "started",
        "mode": "direct",
        "session_id": session_id,
        "run_id": run_id,
        "queue_maxsize": EVENT_QUEUE_MAXSIZE,
    })


# ── GET /api/agent/events ──────────────────────────────────────────────────────

@app.get("/api/agent/events")
async def stream_events(request: Request, session_id: str = "default", run_id: str = ""):
    rate_limited = await _enforce_rate_limit(
        request,
        bucket="agent_events",
        limit=RATE_LIMIT_STREAM_PER_WINDOW,
        session_id=session_id,
    )
    if rate_limited:
        return rate_limited

    async def event_stream():
        effective_run_id = run_id.strip()
        safe_session_id = _safe_session_id(session_id)
        saw_done = False

        if not effective_run_id:
            waited, interval, deadline = 0.0, 0.05, 10.0
            while waited < deadline:
                if _redis_events_enabled():
                    effective_run_id = await _get_session_latest(safe_session_id)
                else:
                    effective_run_id = session_latest_run.get(safe_session_id, "")
                if effective_run_id:
                    break
                await asyncio.sleep(interval)
                waited += interval

        if not effective_run_id:
            yield "event: end\ndata: {}\n\n"
            return

        if _redis_events_enabled():
            stream_key = _run_events_stream_key(effective_run_id)
            last_id = "0-0"
            try:
                while True:
                    try:
                        rows = await cache._redis.xread(
                            {stream_key: last_id},
                            count=100,
                            block=REDIS_EVENT_BLOCK_MS,
                        )
                    except Exception:
                        rows = []

                    if not rows:
                        yield ": keepalive\n\n"
                        continue

                    for _, events in rows:
                        for event_id, fields in events:
                            last_id = event_id
                            raw = fields.get("payload")
                            if not raw:
                                continue
                            try:
                                if json.loads(raw).get("__done__"):
                                    saw_done = True
                                    yield "event: end\ndata: {}\n\n"
                                    return
                            except Exception:
                                pass
                            yield f"data: {raw}\n\n"
            finally:
                if saw_done:
                    async with event_queues_lock:
                        await _cleanup_run_locked(effective_run_id)
            return

        waited, interval, deadline = 0.0, 0.05, 10.0
        while effective_run_id not in event_queues and waited < deadline:
            await asyncio.sleep(interval)
            waited += interval

        if effective_run_id not in event_queues:
            yield "event: end\ndata: {}\n\n"
            return

        cursor = 0
        try:
            while True:
                buffer = event_queues.get(effective_run_id)
                if buffer is None:
                    yield "event: end\ndata: {}\n\n"
                    return

                while cursor < len(buffer):
                    raw = buffer[cursor]
                    cursor += 1
                    try:
                        if json.loads(raw).get("__done__"):
                            saw_done = True
                            yield "event: end\ndata: {}\n\n"
                            return
                    except (json.JSONDecodeError, AttributeError):
                        pass
                    yield f"data: {raw}\n\n"

                signal = event_signals.get(effective_run_id)
                if signal is None:
                    yield "event: end\ndata: {}\n\n"
                    return
                try:
                    await asyncio.wait_for(signal.wait(), timeout=60.0)
                    signal.clear()
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
        finally:
            if saw_done:
                async with event_queues_lock:
                    await _cleanup_run_locked(effective_run_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── GET /api/agent/stream ──────────────────────────────────────────────────────

@app.get("/api/agent/stream")
async def stream_chat(request: Request, input: str = "", session_id: str = ""):
    invalid_input = _validate_user_input_text(str(input))
    if invalid_input:
        return invalid_input
    if not global_graph:
        return JSONResponse({"error": "Agent not initialised"}, status_code=500)

    effective_session_id = _safe_session_id(session_id or f"sess-{uuid.uuid4().hex}")
    auth = _resolve_auth_subject(request)
    rate_limited = await _enforce_rate_limit(
        request,
        bucket="agent_stream",
        limit=RATE_LIMIT_STREAM_PER_WINDOW,
        session_id=effective_session_id,
    )
    if rate_limited:
        return rate_limited

    config = _build_config(
        effective_session_id,
        trace_name=str(input)[:80],
        user_id=auth.get("user_id", ""),
    )

    # Register run for workflow events (same as /api/agent/execute)
    run_id = f"run-{uuid.uuid4().hex}"
    stream_state_error = await _register_run_stream(run_id=run_id, session_id=effective_session_id)
    if stream_state_error:
        return stream_state_error

    async def stream_tokens():
        global active_graph_runs, max_active_graph_runs_seen

        current_specialist = ""
        detected_route = "general"
        tool_start_times: Dict[str, float] = {}
        step_counts: Dict[str, int] = {}
        streamed_chunk_counts: Dict[str, int] = {}
        streamed_response_parts: list[str] = []
        router_start = 0.0
        node_start_times: Dict[str, float] = {}
        active_nodes: set[str] = set()
        routing_emitted = False
        request_id = f"{effective_session_id}:{uuid.uuid4().hex}"

        await graph_run_semaphore.acquire()
        active_graph_runs += 1
        if active_graph_runs > max_active_graph_runs_seen:
            max_active_graph_runs_seen = active_graph_runs

        try:
            mcp_module.set_request_context(request_id)

            trace_context = _langsmith_trace_context()
            if trace_context:
                run_tree = get_current_run_tree()
                distributed_headers: Dict[str, Any] = {}
                if run_tree and hasattr(run_tree, "to_headers"):
                    try:
                        distributed_headers = run_tree.to_headers() or {}
                    except Exception:
                        distributed_headers = {}

                await _push(run_id, {
                    "nodeId": "langsmith",
                    "event_type": "trace_context",
                    "status": "started",
                    "label": "LangSmith Trace",
                    "details": "Trace context initialized for this run",
                    "timestamp": _now_iso(),
                    "distributed_headers": distributed_headers,
                    **trace_context,
                    "raw": {
                        "trace_context": trace_context,
                        "distributed_headers": distributed_headers,
                    },
                })

            async for ev in global_graph.astream_events(
                {"messages": [HumanMessage(content=input)]},
                config=config,
                version="v2",
            ):
                kind = ev.get("event", "")
                meta = ev.get("metadata", {})
                node = meta.get("langgraph_node", "")
                ts = _now_iso()
                trace_fields = _event_trace_fields(ev)

                # ── Node started (push workflow event) ───────────────────────
                if kind == "on_chain_start" and node and node not in active_nodes:
                    active_nodes.add(node)
                    node_start_times[node] = time.monotonic()
                    if node == "router":
                        router_start = time.monotonic()
                        await _push(run_id, {
                            "nodeId": "router",
                            "event_type": "node",
                            "status": "started",
                            "label": "🧭 Router",
                            "details": "Classifying query...",
                            "timestamp": ts,
                            **trace_fields,
                            "raw": {},
                        })

                # ── Routing decision ─────────────────────────────────────────
                if kind == "on_chain_start" and node in SPECIALIST_NODES:
                    current_specialist = node
                    detected_route = node
                    step_counts[node] = 0
                    streamed_chunk_counts[node] = 0
                    router_dur = int((time.monotonic() - router_start) * 1000) if router_start else 0
                    yield f"event: route\ndata: {json.dumps({'route': node, 'specialist': node, 'duration': router_dur, 'timestamp': ts})}\n\n"
                    
                    # Push routing decision for workflow visualization
                    if not routing_emitted:
                        routing_emitted = True
                        await _push(run_id, {
                            "nodeId": "router",
                            "event_type": "routing_decision",
                            "status": "completed",
                            "label": f"Router → {node}",
                            "details": f"Query classified as: {node}",
                            "route": node,
                            "duration_ms": router_dur,
                            "timestamp": ts,
                            **trace_fields,
                            "raw": {"node": "router", "route": node},
                        })
                    
                    # Push specialist node started
                    await _push(run_id, {
                        "nodeId": node,
                        "event_type": "node",
                        "status": "started",
                        "label": _NODE_LABELS.get(node, node),
                        "details": "Processing query...",
                        "timestamp": ts,
                        **trace_fields,
                        "raw": {},
                    })

                # Planning internals: emit explicit plan + execution-step telemetry
                if kind == "on_chain_end" and node == "plan":
                    raw_output = ev.get("data", {}).get("output", {})
                    output = raw_output if isinstance(raw_output, dict) else {}
                    plan_steps = output.get("original_plan") or output.get("plan") or []
                    if plan_steps:
                        yield (
                            "event: plan\n"
                            f"data: {json.dumps({'plan': plan_steps, 'steps': plan_steps, 'timestamp': ts})}\n\n"
                        )
                        await _push(run_id, {
                            "nodeId": "planning",
                            "event_type": "plan",
                            "status": "completed",
                            "label": "Execution Plan",
                            "details": f"Generated {len(plan_steps)} steps",
                            "steps": plan_steps,
                            "timestamp": ts,
                            **trace_fields,
                            "raw": {"steps": plan_steps},
                        })

                if kind == "on_chain_end" and node == "execute":
                    raw_output = ev.get("data", {}).get("output", {})
                    output = raw_output if isinstance(raw_output, dict) else {}
                    raw_trace = output.get("execution_trace") or []
                    trace = raw_trace if isinstance(raw_trace, list) else []
                    if trace and isinstance(trace[-1], dict):
                        latest = trace[-1]
                        step_num = int(latest.get("step", len(trace)))
                        task = latest.get("task", "")
                        preview = str(latest.get("result", ""))[:160].replace("\n", " ")
                        yield (
                            "event: thinking\n"
                            f"data: {json.dumps({'type': 'reasoning', 'thinking': f'Step {step_num}: {task}', 'result': preview, 'step': step_num, 'timestamp': ts})}\n\n"
                        )

                # ── Streaming tokens ─────────────────────────────────────────
                if kind == "on_chat_model_stream" and node != "router":
                    chunk = ev["data"]["chunk"]
                    token = chunk.content if hasattr(chunk, "content") else ""
                    if token:
                        parent = current_specialist or node
                        streamed_chunk_counts[parent] = streamed_chunk_counts.get(parent, 0) + 1
                        streamed_response_parts.append(token)
                        yield f"event: chunk\ndata: {json.dumps({'chunk': token})}\n\n"

                # ── Thinking/reasoning events ────────────────────────────────
                elif kind == "on_chat_model_end" and node and node != "router":
                    output = ev["data"].get("output")
                    tool_calls = []
                    content = ""

                    if output is not None:
                        if hasattr(output, "tool_calls"):
                            tool_calls = output.tool_calls or []
                        if hasattr(output, "content"):
                            content = output.content or ""
                        elif hasattr(output, "generations"):
                            for gen_list in output.generations:
                                for gen in gen_list:
                                    msg = getattr(gen, "message", None)
                                    if msg:
                                        tool_calls = getattr(msg, "tool_calls", []) or tool_calls
                                        content = getattr(msg, "content", "") or content

                    parent = current_specialist or node

                    if tool_calls:
                        step_num = step_counts.get(parent, 0) + 1
                        step_counts[parent] = step_num
                        tc_names = _tool_call_names(tool_calls)
                        yield f"event: thinking\ndata: {json.dumps({'type': 'reasoning', 'thinking': f'Step {step_num}: Planning - {tc_names}', 'step': step_num, 'timestamp': ts})}\n\n"
                        await _push(run_id, {
                            "nodeId": node,
                            "event_type": "reasoning",
                            "status": "completed",
                            "label": f"Step {step_num}: Planning",
                            "details": f"Planned {len(tool_calls)} tool call{'s' if len(tool_calls) != 1 else ''}: {tc_names}",
                            "parent_node": parent if parent != node else None,
                            "step": step_num,
                            "timestamp": ts,
                            **trace_fields,
                            "raw": {
                                "node": node,
                                "step": step_num,
                                "tool_calls": [
                                    (tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "?"))
                                    for tc in tool_calls
                                ],
                            },
                        })
                    elif content:
                        # Some providers do not emit token chunks for every model end event.
                        # Emit a synthetic chunk so clients always receive visible answer text.
                        if streamed_chunk_counts.get(parent, 0) == 0:
                            streamed_response_parts.append(content)
                            yield f"event: chunk\ndata: {json.dumps({'chunk': content})}\n\n"
                        step_num = step_counts.get(parent, 0) + 1
                        step_counts[parent] = step_num
                        preview = content[:120].replace("\n", " ")
                        yield f"event: thinking\ndata: {json.dumps({'type': 'synthesis', 'thinking': f'Step {step_num}: Synthesizing response', 'result': preview, 'step': step_num, 'timestamp': ts})}\n\n"
                        await _push(run_id, {
                            "nodeId": node,
                            "event_type": "reasoning",
                            "status": "completed",
                            "label": f"Step {step_num}: Synthesis",
                            "details": f"Final answer: {preview}{'…' if len(content) > 120 else ''}",
                            "parent_node": parent if parent != node else None,
                            "step": step_num,
                            "timestamp": ts,
                            **trace_fields,
                            "raw": {
                                "node": node,
                                "step": step_num,
                                "preview": preview,
                            },
                        })

                # ── Tool start ───────────────────────────────────────────────
                elif kind == "on_tool_start":
                    tool_name = ev.get("name", "tool")
                    tool_input = ev["data"].get("input", {})
                    tool_start_times[tool_name] = time.monotonic()
                    yield f"event: tool_start\ndata: {json.dumps({'tool_start': tool_name, 'name': tool_name, 'tool_input': tool_input, 'input': tool_input, 'timestamp': ts})}\n\n"
                    
                    # Push tool started event for workflow visualization
                    await _push(run_id, {
                        "nodeId": tool_name,
                        "event_type": "tool",
                        "status": "started",
                        "label": tool_name,
                        "details": f"Executing {tool_name}...",
                        "tool_input": tool_input,
                        "parent_node": current_specialist or "general",
                        "timestamp": ts,
                        **trace_fields,
                        "raw": {"tool": tool_name, "input": tool_input},
                    })

                # ── Tool end ─────────────────────────────────────────────────
                elif kind == "on_tool_end":
                    tool_name = ev.get("name", "tool")
                    output = ev["data"].get("output", "")
                    output_str = str(output) if output else ""
                    duration_ms = int((time.monotonic() - tool_start_times.pop(tool_name, time.monotonic())) * 1000)
                    # Truncate output for SSE (full output in workflow events)
                    output_preview = output_str[:500] if output_str else ""
                    yield f"event: tool_end\ndata: {json.dumps({'tool_end': tool_name, 'name': tool_name, 'output': output_preview, 'duration': duration_ms, 'timestamp': ts})}\n\n"
                    
                    # Push tool completed event for workflow visualization
                    await _push(run_id, {
                        "nodeId": tool_name,
                        "event_type": "tool",
                        "status": "completed",
                        "label": tool_name,
                        "details": f"Completed in {duration_ms}ms",
                        "duration_ms": duration_ms,
                        "parent_node": current_specialist or "general",
                        "timestamp": ts,
                        **trace_fields,
                        "raw": {"tool": tool_name, "output": output_preview[:200]},
                    })

                # ── Node completion ──────────────────────────────────────────
                if kind == "on_chain_end" and node in active_nodes:
                    duration_ms = int((time.monotonic() - node_start_times.get(node, time.monotonic())) * 1000)
                    await _push(run_id, {
                        "nodeId": node,
                        "event_type": "node",
                        "status": "completed",
                        "label": _NODE_LABELS.get(node, node),
                        "details": f"Completed in {duration_ms}ms",
                        "duration_ms": duration_ms,
                        "timestamp": ts,
                        **trace_fields,
                        "raw": {},
                    })
                    active_nodes.discard(node)

            final_response_text = "".join(streamed_response_parts).strip()
            if final_response_text:
                if db.available:
                    try:
                        await db.save_conversation(effective_session_id, "human", input)
                        await db.save_conversation(effective_session_id, "ai", final_response_text)
                    except Exception as e:
                        logger.warning("Failed to persist streamed conversation: %s", e)

                if memory_manager.short_term_available:
                    asyncio.create_task(
                        memory_manager.add_conversation(
                            [
                                {"role": "user", "content": input},
                                {"role": "assistant", "content": final_response_text},
                            ],
                            user_id=effective_session_id,
                            metadata={"route": detected_route},
                        )
                    )

                asyncio.create_task(
                    _maybe_store_chat_long_term(
                        session_id=effective_session_id,
                        user_input=input,
                        response_text=final_response_text,
                        route=detected_route,
                    )
                )

                asyncio.create_task(
                    cache.set_llm_response(input, effective_session_id, detected_route, final_response_text)
                )

            # Push done event for workflow visualization
            await _push(run_id, {"__done__": True})
            yield "event: end\ndata: {}\n\n"
        except Exception as e:
            logger.exception("Streaming error for session %s", effective_session_id)
            # Push error event for workflow visualization
            await _push(run_id, {
                "nodeId": "error",
                "event_type": "error",
                "status": "failed",
                "details": str(e),
                "timestamp": _now_iso(),
                "raw": {},
            })
            await _push(run_id, {"__done__": True})
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "event: end\ndata: {}\n\n"
        finally:
            if active_graph_runs > 0:
                active_graph_runs -= 1
            graph_run_semaphore.release()
            mcp_module.clear_request_context()
            # Mark run as completed for cleanup tracking
            run_completed_at[run_id] = time.time()

    return StreamingResponse(
        stream_tokens(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── POST /api/agent ────────────────────────────────────────────────────────────

@app.post("/api/agent")
async def chat_endpoint(request: Request):
    global active_graph_runs, max_active_graph_runs_seen

    data       = await request.json()
    user_input = str(data.get("input", data.get("message", "")))
    invalid_input = _validate_user_input_text(user_input)
    if invalid_input:
        return invalid_input

    session_id = _safe_session_id(str(data.get("session_id") or f"sess-{uuid.uuid4().hex}"))
    auth = _resolve_auth_subject(request)

    rate_limited = await _enforce_rate_limit(
        request,
        bucket="agent_chat",
        limit=RATE_LIMIT_AGENT_PER_WINDOW,
        session_id=session_id,
    )
    if rate_limited:
        return rate_limited

    if not global_graph:
        return JSONResponse({"error": "Agent not initialised"}, status_code=500)

    # Check cache first (only for non-session-specific queries)
    # Cache key includes session to handle context
    route = data.get("route", "unknown")  # Optional pre-classified route
    cached_response = await cache.get_llm_response(user_input, session_id, route)
    if cached_response:
        logger.info("Cache HIT for query: %s", user_input[:80])
        return JSONResponse({"response": cached_response, "cached": True})

    config = _build_config(
        session_id,
        trace_name=user_input[:80],
        user_id=auth.get("user_id", ""),
    )
    request_id = f"{session_id}:{uuid.uuid4().hex}"

    await graph_run_semaphore.acquire()
    active_graph_runs += 1
    if active_graph_runs > max_active_graph_runs_seen:
        max_active_graph_runs_seen = active_graph_runs

    try:
        mcp_module.set_request_context(request_id)
        result = await global_graph.ainvoke(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
        )
        messages      = result.get("messages", [])
        ai_msgs       = [m for m in messages if hasattr(m, "content") and not isinstance(m, HumanMessage)]
        response_text = ai_msgs[-1].content if ai_msgs else "No response generated."
        detected_route = result.get("route", "general")
        planning_data = _extract_planning_data(result)

        # Persist conversation turn to postgres
        if db.available:
            await db.save_conversation(session_id, "human", user_input)
            await db.save_conversation(session_id, "ai", response_text)

        # Store short-term conversation memories (fire-and-forget, non-blocking)
        if memory_manager.short_term_available:
            asyncio.create_task(
                memory_manager.add_conversation(
                    [
                        {"role": "user",      "content": user_input},
                        {"role": "assistant", "content": response_text},
                    ],
                    user_id=session_id,
                    metadata={"route": detected_route},
                )
            )

        asyncio.create_task(
            _maybe_store_chat_long_term(
                session_id=session_id,
                user_input=user_input,
                response_text=response_text,
                route=detected_route,
            )
        )

        # Cache the response (fire-and-forget)
        asyncio.create_task(
            cache.set_llm_response(user_input, session_id, detected_route, response_text)
        )

        return JSONResponse({
            "response": response_text,
            "cached": False,
            "session_id": session_id,
            "route": detected_route,
            "plan": planning_data.get("plan", []) if planning_data else [],
            "execution_trace": planning_data.get("execution_trace", []) if planning_data else [],
            "multi_step": bool(planning_data),
        })
    except Exception as e:
        logger.exception("Chat endpoint error for session %s", session_id)
        return JSONResponse({"response": f"Error: {e}"}, status_code=500)
    finally:
        if active_graph_runs > 0:
            active_graph_runs -= 1
        graph_run_semaphore.release()
        mcp_module.clear_request_context()


async def _wait_for_run_completion(run_id: str, timeout_seconds: float = 60.0, poll_interval: float = 0.2) -> Dict[str, Any]:
    deadline = time.time() + max(timeout_seconds, 0.1)
    while time.time() < deadline:
        run = await deployment_store.get_run(run_id)
        if not run:
            return {"error": "Run not found", "run_id": run_id}
        if str(run.get("status", "")).lower() in TERMINAL_RUN_STATUSES:
            return run
        await asyncio.sleep(poll_interval)

    run = await deployment_store.get_run(run_id)
    if run:
        run["timed_out"] = True
        run["timeout_seconds"] = timeout_seconds
        return run
    return {"error": "Run not found", "run_id": run_id}


# ── Deployment Runtime Endpoints (Assistants/Threads/Runs/Crons) ─────────────


@app.get("/api/deployment/status")
async def deployment_runtime_status(request: Request):
    if _deployment_proxy_enabled(request):
        return await _proxy_deployment_request(request, "/system/info")

    return JSONResponse(
        {
            "mode": DEPLOYMENT_RUNTIME_MODE,
            "proxy_configured": bool(DEPLOYMENT_PROXY_URL),
            "proxy_url": DEPLOYMENT_PROXY_URL or None,
            "state_file": DEPLOYMENT_STATE_FILE,
            "assistants": len(deployment_store.assistants),
            "threads": len(deployment_store.threads),
            "runs": len(deployment_store.runs),
            "crons": len(deployment_store.crons),
            "background_runs": len(background_run_tasks),
            "cron_scheduler_active": deployment_scheduler is not None,
            "features": {
                "assistants": True,
                "threads": True,
                "thread_runs": True,
                "stateless_runs": True,
                "crons": True,
                "streaming": True,
                "durable_local_state": True,
                "proxy_to_langsmith_agent_server": bool(DEPLOYMENT_PROXY_URL),
            },
            "timestamp": _now_iso(),
        }
    )


@app.api_route(
    "/api/deployment/proxy/{upstream_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def deployment_proxy_passthrough(request: Request, upstream_path: str):
    body: Optional[Dict[str, Any]] = None
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            payload = await request.json()
            if isinstance(payload, dict):
                body = payload
        except Exception:
            body = None
    return await _proxy_deployment_request(
        request,
        f"/{upstream_path}",
        payload=body,
        params=dict(request.query_params),
    )


@app.post("/api/deployment/assistants/search")
async def deployment_search_assistants(request: Request):
    if _deployment_proxy_enabled(request):
        payload = await request.json()
        return await _proxy_deployment_request(request, "/assistants/search", payload=payload if isinstance(payload, dict) else {})

    data = await request.json()
    metadata = data.get("metadata") if isinstance(data, dict) and isinstance(data.get("metadata"), dict) else None
    limit = int(data.get("limit", 10)) if isinstance(data, dict) else 10
    offset = int(data.get("offset", 0)) if isinstance(data, dict) else 0
    rows = await deployment_store.search_assistants(metadata=metadata, limit=max(1, min(limit, 200)), offset=max(0, offset))
    return JSONResponse({"assistants": rows, "limit": limit, "offset": offset})


@app.post("/api/deployment/assistants/count")
async def deployment_count_assistants(request: Request):
    if _deployment_proxy_enabled(request):
        payload = await request.json()
        return await _proxy_deployment_request(request, "/assistants/count", payload=payload if isinstance(payload, dict) else {})

    data = await request.json()
    metadata = data.get("metadata") if isinstance(data, dict) and isinstance(data.get("metadata"), dict) else None
    count = await deployment_store.count_assistants(metadata=metadata)
    return JSONResponse({"count": count})


@app.post("/api/deployment/assistants")
async def deployment_create_assistant(request: Request):
    if _deployment_proxy_enabled(request):
        payload = await request.json()
        return await _proxy_deployment_request(request, "/assistants", payload=payload if isinstance(payload, dict) else {})

    data = await request.json()
    if not isinstance(data, dict):
        return JSONResponse({"error": "Invalid request body"}, status_code=400)

    try:
        assistant = await deployment_store.create_assistant(
            name=str(data.get("name") or "").strip(),
            graph_id=str(data.get("graph_id") or "agent").strip() or "agent",
            config=data.get("config") if isinstance(data.get("config"), dict) else {},
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
            description=str(data.get("description") or "").strip(),
            assistant_id=str(data.get("assistant_id") or "").strip(),
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)

    return JSONResponse(assistant, status_code=201)


@app.get("/api/deployment/assistants/{assistant_id}")
async def deployment_get_assistant(request: Request, assistant_id: str):
    if _deployment_proxy_enabled(request):
        return await _proxy_deployment_request(request, f"/assistants/{assistant_id}")

    assistant = await deployment_store.get_assistant(assistant_id)
    if not assistant:
        return JSONResponse({"error": "Assistant not found"}, status_code=404)
    return JSONResponse(assistant)


@app.patch("/api/deployment/assistants/{assistant_id}")
async def deployment_patch_assistant(request: Request, assistant_id: str):
    if _deployment_proxy_enabled(request):
        payload = await request.json()
        return await _proxy_deployment_request(request, f"/assistants/{assistant_id}", payload=payload if isinstance(payload, dict) else {})

    data = await request.json()
    if not isinstance(data, dict):
        return JSONResponse({"error": "Invalid request body"}, status_code=400)

    assistant = await deployment_store.patch_assistant(
        assistant_id,
        name=data.get("name") if "name" in data else None,
        description=data.get("description") if "description" in data else None,
        config=data.get("config") if "config" in data and isinstance(data.get("config"), dict) else None,
        metadata=data.get("metadata") if "metadata" in data and isinstance(data.get("metadata"), dict) else None,
    )
    if not assistant:
        return JSONResponse({"error": "Assistant not found"}, status_code=404)
    return JSONResponse(assistant)


@app.delete("/api/deployment/assistants/{assistant_id}")
async def deployment_delete_assistant(request: Request, assistant_id: str):
    if _deployment_proxy_enabled(request):
        return await _proxy_deployment_request(request, f"/assistants/{assistant_id}")

    deleted = await deployment_store.delete_assistant(assistant_id)
    if not deleted:
        return JSONResponse({"error": "Assistant not found or protected default assistant"}, status_code=404)
    return JSONResponse({"deleted": True, "assistant_id": assistant_id})


@app.post("/api/deployment/threads")
async def deployment_create_thread(request: Request):
    if _deployment_proxy_enabled(request):
        payload = await request.json()
        return await _proxy_deployment_request(request, "/threads", payload=payload if isinstance(payload, dict) else {})

    data = await request.json()
    if not isinstance(data, dict):
        data = {}
    try:
        thread = await deployment_store.create_thread(
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
            config=data.get("config") if isinstance(data.get("config"), dict) else {},
            values=data.get("values"),
            thread_id=str(data.get("thread_id") or "").strip(),
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    return JSONResponse(thread, status_code=201)


@app.post("/api/deployment/threads/search")
async def deployment_search_threads(request: Request):
    if _deployment_proxy_enabled(request):
        payload = await request.json()
        return await _proxy_deployment_request(request, "/threads/search", payload=payload if isinstance(payload, dict) else {})

    data = await request.json()
    metadata = data.get("metadata") if isinstance(data, dict) and isinstance(data.get("metadata"), dict) else None
    limit = int(data.get("limit", 10)) if isinstance(data, dict) else 10
    offset = int(data.get("offset", 0)) if isinstance(data, dict) else 0
    rows = await deployment_store.search_threads(metadata=metadata, limit=max(1, min(limit, 200)), offset=max(0, offset))
    return JSONResponse({"threads": rows, "limit": limit, "offset": offset})


@app.post("/api/deployment/threads/count")
async def deployment_count_threads(request: Request):
    if _deployment_proxy_enabled(request):
        payload = await request.json()
        return await _proxy_deployment_request(request, "/threads/count", payload=payload if isinstance(payload, dict) else {})

    data = await request.json()
    metadata = data.get("metadata") if isinstance(data, dict) and isinstance(data.get("metadata"), dict) else None
    count = await deployment_store.count_threads(metadata=metadata)
    return JSONResponse({"count": count})


@app.get("/api/deployment/threads/{thread_id}")
async def deployment_get_thread(request: Request, thread_id: str):
    if _deployment_proxy_enabled(request):
        return await _proxy_deployment_request(request, f"/threads/{thread_id}")

    thread = await deployment_store.get_thread(thread_id)
    if not thread:
        return JSONResponse({"error": "Thread not found"}, status_code=404)
    return JSONResponse(thread)


@app.get("/api/deployment/threads/{thread_id}/state")
async def deployment_get_thread_state(request: Request, thread_id: str):
    if _deployment_proxy_enabled(request):
        return await _proxy_deployment_request(request, f"/threads/{thread_id}/state")

    thread = await deployment_store.get_thread(thread_id)
    if not thread:
        return JSONResponse({"error": "Thread not found"}, status_code=404)

    runs = await deployment_store.list_runs(thread_id, limit=50, offset=0)
    return JSONResponse(
        {
            "thread_id": thread_id,
            "status": thread.get("status", "idle"),
            "messages": thread.get("messages", []),
            "metadata": thread.get("metadata", {}),
            "runs": runs,
            "updated_at": thread.get("updated_at"),
        }
    )


@app.patch("/api/deployment/threads/{thread_id}")
async def deployment_patch_thread(request: Request, thread_id: str):
    if _deployment_proxy_enabled(request):
        payload = await request.json()
        return await _proxy_deployment_request(request, f"/threads/{thread_id}", payload=payload if isinstance(payload, dict) else {})

    data = await request.json()
    if not isinstance(data, dict):
        return JSONResponse({"error": "Invalid request body"}, status_code=400)
    thread = await deployment_store.patch_thread(
        thread_id,
        metadata=data.get("metadata") if "metadata" in data and isinstance(data.get("metadata"), dict) else None,
        config=data.get("config") if "config" in data and isinstance(data.get("config"), dict) else None,
        values=data.get("values") if "values" in data else None,
    )
    if not thread:
        return JSONResponse({"error": "Thread not found"}, status_code=404)
    return JSONResponse(thread)


@app.delete("/api/deployment/threads/{thread_id}")
async def deployment_delete_thread(request: Request, thread_id: str):
    if _deployment_proxy_enabled(request):
        return await _proxy_deployment_request(request, f"/threads/{thread_id}")

    deleted = await deployment_store.delete_thread(thread_id)
    if not deleted:
        return JSONResponse({"error": "Thread not found"}, status_code=404)
    return JSONResponse({"deleted": True, "thread_id": thread_id})


@app.post("/api/deployment/threads/{thread_id}/runs/background")
async def deployment_create_thread_background_run(request: Request, thread_id: str):
    if _deployment_proxy_enabled(request):
        payload = await request.json()
        return await _proxy_deployment_request(
            request,
            f"/threads/{thread_id}/runs",
            payload=payload if isinstance(payload, dict) else {},
        )

    data = await request.json()
    if not isinstance(data, dict):
        return JSONResponse({"error": "Invalid request body"}, status_code=400)

    normalized_input = _normalize_run_input(data)
    assistant_ref = str(data.get("assistant_id") or data.get("graph_id") or "agent")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}

    run, error = await _start_deployment_background_run(
        thread_id=thread_id,
        assistant_ref=assistant_ref,
        input_payload=normalized_input,
        metadata=metadata,
        mode="background",
    )
    if error:
        return error

    run_id = str(run.get("run_id", ""))
    return JSONResponse(
        {
            **run,
            "stream_url": f"/api/deployment/threads/{thread_id}/runs/{run_id}/stream",
            "join_url": f"/api/deployment/threads/{thread_id}/runs/{run_id}/join",
        },
        status_code=202,
    )


@app.post("/api/deployment/threads/{thread_id}/runs/wait")
async def deployment_create_thread_wait_run(request: Request, thread_id: str):
    if _deployment_proxy_enabled(request):
        payload = await request.json()
        return await _proxy_deployment_request(
            request,
            f"/threads/{thread_id}/runs/wait",
            payload=payload if isinstance(payload, dict) else {},
        )

    data = await request.json()
    if not isinstance(data, dict):
        return JSONResponse({"error": "Invalid request body"}, status_code=400)

    normalized_input = _normalize_run_input(data)
    assistant_ref = str(data.get("assistant_id") or data.get("graph_id") or "agent")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    timeout_seconds = float(data.get("timeout_seconds", 120.0))

    run, error = await _start_deployment_background_run(
        thread_id=thread_id,
        assistant_ref=assistant_ref,
        input_payload=normalized_input,
        metadata=metadata,
        mode="wait",
    )
    if error:
        return error

    run_id = str(run.get("run_id", ""))
    completed = await _wait_for_run_completion(run_id, timeout_seconds=timeout_seconds)
    return JSONResponse(completed)


@app.get("/api/deployment/threads/{thread_id}/runs")
async def deployment_list_thread_runs(request: Request, thread_id: str, limit: int = 20, offset: int = 0):
    if _deployment_proxy_enabled(request):
        return await _proxy_deployment_request(
            request,
            f"/threads/{thread_id}/runs",
            params={"limit": limit, "offset": offset},
        )

    runs = await deployment_store.list_runs(thread_id, limit=max(1, min(limit, 200)), offset=max(0, offset))
    return JSONResponse({"runs": runs, "thread_id": thread_id, "limit": limit, "offset": offset})


@app.get("/api/deployment/threads/{thread_id}/runs/{run_id}")
async def deployment_get_run(request: Request, thread_id: str, run_id: str):
    if _deployment_proxy_enabled(request):
        return await _proxy_deployment_request(request, f"/threads/{thread_id}/runs/{run_id}")

    run = await deployment_store.get_run(run_id)
    if not run or str(run.get("thread_id")) != thread_id:
        return JSONResponse({"error": "Run not found"}, status_code=404)
    return JSONResponse(run)


@app.get("/api/deployment/threads/{thread_id}/runs/{run_id}/join")
async def deployment_join_run(request: Request, thread_id: str, run_id: str, timeout_seconds: float = 120.0):
    if _deployment_proxy_enabled(request):
        return await _proxy_deployment_request(
            request,
            f"/threads/{thread_id}/runs/{run_id}/join",
            params={"timeout_seconds": timeout_seconds},
        )

    run = await deployment_store.get_run(run_id)
    if not run or str(run.get("thread_id")) != thread_id:
        return JSONResponse({"error": "Run not found"}, status_code=404)

    completed = await _wait_for_run_completion(run_id, timeout_seconds=timeout_seconds)
    return JSONResponse(completed)


@app.get("/api/deployment/threads/{thread_id}/runs/{run_id}/stream")
async def deployment_stream_run_events(request: Request, thread_id: str, run_id: str):
    if _deployment_proxy_enabled(request):
        return JSONResponse(
            {
                "error": "Streaming proxy mode is not supported via JSON proxy helper",
                "details": "Use /api/deployment/proxy/... directly with a streaming-capable client.",
            },
            status_code=501,
        )
    return await stream_events(request=request, session_id=thread_id, run_id=run_id)


@app.post("/api/deployment/threads/{thread_id}/runs/{run_id}/cancel")
async def deployment_cancel_run(request: Request, thread_id: str, run_id: str):
    if _deployment_proxy_enabled(request):
        return await _proxy_deployment_request(request, f"/threads/{thread_id}/runs/{run_id}/cancel")

    run = await deployment_store.get_run(run_id)
    if not run or str(run.get("thread_id")) != thread_id:
        return JSONResponse({"error": "Run not found"}, status_code=404)

    task = background_run_tasks.get(run_id)
    if task and not task.done():
        task.cancel()
    else:
        await deployment_store.update_run(run_id, status="cancelled", error="Run cancelled by user")
        await _push(run_id, {"__done__": True})

    cancelled = await deployment_store.get_run(run_id)
    return JSONResponse(cancelled or {"run_id": run_id, "status": "cancelled"})


@app.post("/api/deployment/runs/background")
async def deployment_create_stateless_background_run(request: Request):
    if _deployment_proxy_enabled(request):
        payload = await request.json()
        return await _proxy_deployment_request(request, "/runs", payload=payload if isinstance(payload, dict) else {})

    data = await request.json()
    if not isinstance(data, dict):
        return JSONResponse({"error": "Invalid request body"}, status_code=400)

    thread = await deployment_store.create_thread(
        metadata={"created_by": "stateless_run"},
        config={},
        values=None,
    )
    thread_id = str(thread.get("thread_id", ""))

    normalized_input = _normalize_run_input(data)
    assistant_ref = str(data.get("assistant_id") or data.get("graph_id") or "agent")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    on_run_completed = str(data.get("on_run_completed", "delete")).lower()
    cleanup_thread = on_run_completed != "keep"

    run, error = await _start_deployment_background_run(
        thread_id=thread_id,
        assistant_ref=assistant_ref,
        input_payload=normalized_input,
        metadata=metadata,
        mode="stateless_background",
        cleanup_thread_on_complete=cleanup_thread,
    )
    if error:
        return error

    return JSONResponse({**run, "thread_id": thread_id}, status_code=202)


@app.post("/api/deployment/runs/wait")
async def deployment_create_stateless_wait_run(request: Request):
    if _deployment_proxy_enabled(request):
        payload = await request.json()
        return await _proxy_deployment_request(request, "/runs/wait", payload=payload if isinstance(payload, dict) else {})

    data = await request.json()
    if not isinstance(data, dict):
        return JSONResponse({"error": "Invalid request body"}, status_code=400)

    thread = await deployment_store.create_thread(
        metadata={"created_by": "stateless_run"},
        config={},
        values=None,
    )
    thread_id = str(thread.get("thread_id", ""))

    normalized_input = _normalize_run_input(data)
    assistant_ref = str(data.get("assistant_id") or data.get("graph_id") or "agent")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    timeout_seconds = float(data.get("timeout_seconds", 120.0))
    on_run_completed = str(data.get("on_run_completed", "delete")).lower()

    run, error = await _start_deployment_background_run(
        thread_id=thread_id,
        assistant_ref=assistant_ref,
        input_payload=normalized_input,
        metadata=metadata,
        mode="stateless_wait",
        cleanup_thread_on_complete=on_run_completed != "keep",
    )
    if error:
        return error

    completed = await _wait_for_run_completion(str(run.get("run_id", "")), timeout_seconds=timeout_seconds)
    completed["thread_id"] = thread_id
    return JSONResponse(completed)


@app.post("/api/deployment/crons")
async def deployment_create_cron(request: Request):
    if _deployment_proxy_enabled(request):
        payload = await request.json()
        return await _proxy_deployment_request(request, "/crons", payload=payload if isinstance(payload, dict) else {})

    data = await request.json()
    if not isinstance(data, dict):
        return JSONResponse({"error": "Invalid request body"}, status_code=400)

    assistant_ref = str(data.get("assistant_id") or data.get("graph_id") or "agent").strip() or "agent"
    assistant = await deployment_store.resolve_assistant(assistant_ref)
    if not assistant:
        return JSONResponse({"error": f"Assistant not found: {assistant_ref}"}, status_code=404)

    schedule = str(data.get("schedule") or "").strip()
    if not schedule:
        return JSONResponse({"error": "schedule is required"}, status_code=400)
    if CronTrigger is None:
        return JSONResponse({"error": "Cron scheduler support unavailable"}, status_code=503)
    try:
        CronTrigger.from_crontab(schedule, timezone=timezone.utc)
    except Exception as e:
        return JSONResponse({"error": f"Invalid cron schedule: {e}"}, status_code=400)

    input_payload = _normalize_run_input(data)
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    on_run_completed = str(data.get("on_run_completed", "delete")).lower()

    thread_id = ""
    if str(data.get("thread_id") or "").strip():
        thread_id = str(data.get("thread_id")).strip()
        if not await deployment_store.get_thread(thread_id):
            return JSONResponse({"error": f"Thread not found: {thread_id}"}, status_code=404)

    try:
        cron = await deployment_store.create_cron(
            assistant_id=str(assistant.get("assistant_id", "")),
            schedule=schedule,
            input_payload=input_payload,
            thread_id=thread_id,
            metadata=metadata,
            on_run_completed=on_run_completed,
            cron_id=str(data.get("cron_id") or "").strip(),
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)

    await _register_deployment_cron_job(cron)
    resolved = await deployment_store.get_cron(str(cron.get("cron_id", "")))
    return JSONResponse(resolved or cron, status_code=201)


@app.get("/api/deployment/crons/{cron_id}")
async def deployment_get_cron(request: Request, cron_id: str):
    if _deployment_proxy_enabled(request):
        return await _proxy_deployment_request(request, f"/crons/{cron_id}")

    cron = await deployment_store.get_cron(cron_id)
    if not cron:
        return JSONResponse({"error": "Cron not found"}, status_code=404)
    return JSONResponse(cron)


@app.post("/api/deployment/crons/search")
async def deployment_search_crons(request: Request):
    if _deployment_proxy_enabled(request):
        payload = await request.json()
        return await _proxy_deployment_request(request, "/crons/search", payload=payload if isinstance(payload, dict) else {})

    data = await request.json()
    metadata = data.get("metadata") if isinstance(data, dict) and isinstance(data.get("metadata"), dict) else None
    limit = int(data.get("limit", 20)) if isinstance(data, dict) else 20
    offset = int(data.get("offset", 0)) if isinstance(data, dict) else 0
    rows = await deployment_store.search_crons(metadata=metadata, limit=max(1, min(limit, 200)), offset=max(0, offset))
    return JSONResponse({"crons": rows, "limit": limit, "offset": offset})


@app.post("/api/deployment/crons/count")
async def deployment_count_crons(request: Request):
    if _deployment_proxy_enabled(request):
        payload = await request.json()
        return await _proxy_deployment_request(request, "/crons/count", payload=payload if isinstance(payload, dict) else {})

    data = await request.json()
    metadata = data.get("metadata") if isinstance(data, dict) and isinstance(data.get("metadata"), dict) else None
    count = await deployment_store.count_crons(metadata=metadata)
    return JSONResponse({"count": count})


@app.patch("/api/deployment/crons/{cron_id}")
async def deployment_patch_cron(request: Request, cron_id: str):
    if _deployment_proxy_enabled(request):
        payload = await request.json()
        return await _proxy_deployment_request(request, f"/crons/{cron_id}", payload=payload if isinstance(payload, dict) else {})

    data = await request.json()
    if not isinstance(data, dict):
        return JSONResponse({"error": "Invalid request body"}, status_code=400)

    if "schedule" in data and data.get("schedule") is not None:
        if CronTrigger is None:
            return JSONResponse({"error": "Cron scheduler support unavailable"}, status_code=503)
        try:
            CronTrigger.from_crontab(str(data.get("schedule")).strip(), timezone=timezone.utc)
        except Exception as e:
            return JSONResponse({"error": f"Invalid cron schedule: {e}"}, status_code=400)

    updated = await deployment_store.update_cron(
        cron_id,
        schedule=str(data.get("schedule")).strip() if "schedule" in data and data.get("schedule") is not None else None,
        input_payload=_normalize_run_input(data) if "input" in data or "messages" in data else None,
        metadata=data.get("metadata") if "metadata" in data and isinstance(data.get("metadata"), dict) else None,
        active=bool(data.get("active")) if "active" in data else None,
        on_run_completed=str(data.get("on_run_completed")).lower() if "on_run_completed" in data else None,
    )
    if not updated:
        return JSONResponse({"error": "Cron not found"}, status_code=404)

    if updated.get("active"):
        await _register_deployment_cron_job(updated)
    else:
        await _remove_deployment_cron_job(cron_id)

    resolved = await deployment_store.get_cron(cron_id)
    return JSONResponse(resolved or updated)


@app.delete("/api/deployment/crons/{cron_id}")
async def deployment_delete_cron(request: Request, cron_id: str):
    if _deployment_proxy_enabled(request):
        return await _proxy_deployment_request(request, f"/crons/{cron_id}")

    await _remove_deployment_cron_job(cron_id)
    deleted = await deployment_store.delete_cron(cron_id)
    if not deleted:
        return JSONResponse({"error": "Cron not found"}, status_code=404)
    return JSONResponse({"deleted": True, "cron_id": cron_id})


# ── Knowledge Graph / Document Ingestion Endpoints ────────────────────────────


@app.post("/api/knowledge/ingest")
async def ingest_document(request: Request):
    """
    Ingest a document into long-term memory (Mem0 Cloud).

    Body:
        {
            "text": "document content...",
            "metadata": {"source": "NTSB", "date": "2024-01-15", ...},
            "dataset": "aviation_knowledge"  # optional
        }

    Returns:
        {"success": true} or {"success": false, "error": "..."}
    """
    if not memory_manager.long_term_available:
        return JSONResponse(
            {"success": False, "error": "Long-term memory (mem0 cloud) unavailable"},
            status_code=503,
        )

    try:
        data = await request.json()
        text = data.get("text", "")
        metadata = data.get("metadata", {})
        dataset = data.get("dataset", "")
        scope = str(data.get("scope", "common")).lower()
        scope_session_id = data.get("session_id", "")

        if not text:
            return JSONResponse(
                {"success": False, "error": "No text provided"},
                status_code=400,
            )

        if scope == "session":
            if not scope_session_id:
                return JSONResponse(
                    {"success": False, "error": "session_id required when scope=session"},
                    status_code=400,
                )
            if dataset:
                success = await memory_manager.add_knowledge(
                    text=text,
                    metadata=metadata,
                    dataset_name=dataset,
                )
            else:
                success = await memory_manager.add_session_knowledge(
                    text=text,
                    session_id=scope_session_id,
                    metadata=metadata,
                )
        else:
            resolved_dataset = dataset or memory_manager.get_common_dataset_name()
            success = await memory_manager.add_knowledge(
                text=text,
                metadata=metadata,
                dataset_name=resolved_dataset,
            )

        if success:
            resolved_dataset = dataset
            if not resolved_dataset and scope == "session":
                resolved_dataset = memory_manager.get_session_dataset_name(scope_session_id)
            elif not resolved_dataset:
                resolved_dataset = memory_manager.get_common_dataset_name()

            logger.info("Ingested document: %d chars, dataset=%s", len(text), resolved_dataset)
            return JSONResponse({
                "success": True,
                "dataset": resolved_dataset,
                "scope": scope,
                "session_id": scope_session_id or None,
            })
        else:
            return JSONResponse(
                {"success": False, "error": "Ingestion failed"},
                status_code=500,
            )

    except Exception as e:
        logger.exception("Document ingestion error")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@app.post("/api/knowledge/ingest-batch")
async def ingest_documents_batch(request: Request):
    """
    Ingest multiple documents in batch.

    Body:
        {
            "documents": [
                {"text": "...", "metadata": {...}},
                {"text": "...", "metadata": {...}},
                ...
            ],
            "dataset": "aviation_knowledge"  # optional
        }

    Returns:
        {"success": N, "total": M, "failed": K}
    """
    if not memory_manager.long_term_available:
        return JSONResponse(
            {"success": False, "error": "Long-term memory (mem0 cloud) unavailable"},
            status_code=503,
        )

    try:
        data = await request.json()
        documents = data.get("documents", [])
        dataset = data.get("dataset", "")
        scope = str(data.get("scope", "common")).lower()
        scope_session_id = data.get("session_id", "")

        if not documents:
            return JSONResponse(
                {"success": False, "error": "No documents provided"},
                status_code=400,
            )

        if scope == "session":
            if not scope_session_id:
                return JSONResponse(
                    {"success": False, "error": "session_id required when scope=session"},
                    status_code=400,
                )
            if dataset:
                success_count = await memory_manager.add_knowledge_batch(
                    documents=documents,
                    dataset_name=dataset,
                )
            else:
                success_count = await memory_manager.add_session_knowledge_batch(
                    documents=documents,
                    session_id=scope_session_id,
                )
        else:
            resolved_dataset = dataset or memory_manager.get_common_dataset_name()
            success_count = await memory_manager.add_knowledge_batch(
                documents=documents,
                dataset_name=resolved_dataset,
            )

        resolved_dataset = dataset
        if not resolved_dataset and scope == "session":
            resolved_dataset = memory_manager.get_session_dataset_name(scope_session_id)
        elif not resolved_dataset:
            resolved_dataset = memory_manager.get_common_dataset_name()

        return JSONResponse({
            "success": success_count,
            "total": len(documents),
            "failed": len(documents) - success_count,
            "dataset": resolved_dataset,
            "scope": scope,
            "session_id": scope_session_id or None,
        })

    except Exception as e:
        logger.exception("Batch ingestion error")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@app.get("/api/knowledge/search")
async def search_knowledge(
    query: str = "",
    dataset: str = "",
    scope: str = "common",
    session_id: str = "",
    limit: int = 5,
):
    """
    Search long-term memory.

    Query params:
        - query: Search query (required)
        - dataset: Dataset name (default: aviation_knowledge)
        - limit: Max results (default: 5, max: 10)

    Returns:
        {"results": "formatted long-term memory results", "cached": bool}
    """
    if not query:
        return JSONResponse(
            {"error": "No query provided"},
            status_code=400,
        )

    if not memory_manager.long_term_available:
        return JSONResponse(
            {"results": "Long-term memory (mem0 cloud) unavailable"},
        )

    try:
        limit = max(1, min(limit, 10))
        scope = scope.lower()

        if scope == "session" and not session_id and not dataset:
            return JSONResponse(
                {"error": "session_id required when scope=session and dataset is not provided"},
                status_code=400,
            )

        if dataset:
            resolved_dataset = dataset
        elif scope == "session":
            resolved_dataset = memory_manager.get_session_dataset_name(session_id)
        else:
            resolved_dataset = memory_manager.get_common_dataset_name()

        # Check cache first
        cached_results = await cache.get_knowledge_search(query, resolved_dataset)
        if cached_results:
            logger.debug("Cache HIT for knowledge search: %s", query[:80])
            return JSONResponse({
                "query": query,
                "dataset": resolved_dataset,
                "scope": scope,
                "session_id": session_id or None,
                "results": cached_results,
                "cached": True,
            })

        # Cache miss: query long-term memory
        results = await memory_manager.search_long_term(
            query=query,
            dataset_name=resolved_dataset,
            limit=limit,
        )

        # Cache the results (fire-and-forget)
        asyncio.create_task(cache.set_knowledge_search(query, resolved_dataset, results))

        return JSONResponse({
            "query": query,
            "dataset": resolved_dataset,
            "scope": scope,
            "session_id": session_id or None,
            "results": results or "No results found",
            "cached": False,
        })

    except Exception as e:
        logger.exception("Knowledge search error")
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


@app.get("/api/knowledge/entity/{entity_name}")
async def get_entity_info(
    entity_name: str,
    dataset: str = "",
    scope: str = "common",
    session_id: str = "",
):
    """
    Retrieve entity information from long-term memory.

    Path params:
        - entity_name: Entity identifier (e.g., "EGLL", "Boeing 737")

    Query params:
        - dataset: Dataset name (default: aviation_knowledge)

    Returns:
        {"entity": {...}} or {"error": "Not found"}
    """
    if not memory_manager.long_term_available:
        return JSONResponse(
            {"error": "Long-term memory (mem0 cloud) unavailable"},
            status_code=503,
        )

    try:
        scope = scope.lower()
        if dataset:
            resolved_dataset = dataset
        elif scope == "session":
            if not session_id:
                return JSONResponse(
                    {"error": "session_id required when scope=session and dataset is not provided"},
                    status_code=400,
                )
            resolved_dataset = memory_manager.get_session_dataset_name(session_id)
        else:
            resolved_dataset = memory_manager.get_common_dataset_name()

        entity = await memory_manager.get_entity(
            entity_name=entity_name,
            dataset_name=resolved_dataset,
        )

        if entity:
            return JSONResponse({
                "entity": entity,
                "dataset": resolved_dataset,
                "scope": scope,
                "session_id": session_id or None,
            })
        else:
            return JSONResponse(
                {"error": f"Entity not found: {entity_name}"},
                status_code=404,
            )

    except Exception as e:
        logger.exception("Entity retrieval error")
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


@app.get("/api/memory/status")
async def memory_status():
    """
    Get memory system status.

    Returns:
        {
            "short_term": {"available": true, "provider": "mem0"},
            "long_term": {"available": true, "provider": "mem0-cloud"},
            "cache": {"available": true, "provider": "redis", "hit_rate": 0.85}
        }
    """
    cache_stats = await cache.get_stats() if cache.available else {"available": False}

    return JSONResponse({
        "short_term": {
            "available": memory_manager.short_term_available,
            "provider": "mem0",
            "description": "Recent conversational context (last N turns)",
        },
        "long_term": {
            "available": memory_manager.long_term_available,
            "provider": "mem0-cloud",
            "description": "Persistent domain knowledge memory",
        },
        "knowledge_scopes": {
            "common_dataset": memory_manager.get_common_dataset_name(),
            "session_dataset_prefix": os.getenv("SESSION_KNOWLEDGE_PREFIX", "session_knowledge"),
            "supported_scopes": ["common", "session"],
        },
        "cache": {
            "available": cache.available,
            "provider": "redis",
            "description": "High-performance query cache",
            **cache_stats,
        },
        "dual_memory": {
            "enabled": memory_manager.short_term_available or memory_manager.long_term_available,
            "both_available": memory_manager.short_term_available and memory_manager.long_term_available,
        },
    })


@app.post("/api/memory/smoke")
async def memory_smoke_validation(request: Request):
    """
    Smoke validation for both short-term and long-term memory paths.

    Body (optional):
        {
            "query": "validation query",
            "cleanup": true,
            "include_long_term": true
        }

    Returns detailed pass/fail diagnostics for both memory tiers.
    """
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    include_long_term = bool(payload.get("include_long_term", True))
    cleanup = bool(payload.get("cleanup", True))
    query = str(payload.get("query") or "memory smoke validation").strip()

    token = uuid.uuid4().hex[:10]
    smoke_session = _safe_session_id(f"smoke-{token}")
    smoke_dataset = f"aviation_knowledge_smoke_{token}"

    short_result: Dict[str, Any] = {
        "available": memory_manager.short_term_available,
        "stored": False,
        "found": False,
        "preview": "",
        "wait_seconds": 0,
    }
    long_result: Dict[str, Any] = {
        "available": memory_manager.long_term_available,
        "stored": False,
        "found": False,
        "preview": "",
        "dataset": smoke_dataset,
        "cleanup": "skipped",
        "wait_seconds": 0,
    }

    short_query = "favorite airport"
    long_query = "runway incursion prevention protocol"
    long_query_fallbacks = [
        long_query,
        "readback-hearback protocol",
        "hold-short compliance",
    ]

    if short_result["available"]:
        await memory_manager.add_conversation(
            [
                {
                    "role": "user",
                    "content": (
                        "I prefer concise responses and my favorite airport is VHHH in Hong Kong. "
                        f"Context: {query}"
                    ),
                },
                {
                    "role": "assistant",
                    "content": "Understood. I will keep responses concise and remember your airport preference.",
                },
            ],
            user_id=smoke_session,
            metadata={"source": "smoke_validation"},
        )
        short_result["stored"] = True

        short_hits = ""
        waited = 0
        for wait_for in (2, 5, 10, 15):
            await asyncio.sleep(wait_for)
            waited += wait_for
            short_hits = await memory_manager.search_short_term(short_query, user_id=smoke_session, limit=5)
            if short_hits:
                break
        short_result["wait_seconds"] = waited
        short_result["preview"] = str(short_hits)[:300]
        short_result["found"] = bool(short_hits)

    if include_long_term and long_result["available"]:
        long_stored = await memory_manager.add_knowledge(
            text=(
                "Runway incursion prevention includes explicit readback-hearback protocol, "
                "and hold-short compliance."
            ),
            metadata={"source": "smoke_validation", "smoke_token": token},
            dataset_name=smoke_dataset,
        )
        long_result["stored"] = bool(long_stored)

        long_hits = ""
        waited = 0
        for wait_for in (2, 5, 10, 15, 20):
            await asyncio.sleep(wait_for)
            waited += wait_for
            for candidate_query in long_query_fallbacks:
                long_hits = await memory_manager.search_long_term(
                    query=candidate_query,
                    dataset_name=smoke_dataset,
                    limit=5,
                )
                if long_hits:
                    break
            if long_hits:
                break
        long_result["wait_seconds"] = waited
        long_result["preview"] = str(long_hits)[:300]
        long_result["found"] = bool(long_hits)

        if cleanup:
            cleaned = await memory_manager.reset_long_term(smoke_dataset)
            long_result["cleanup"] = "done" if cleaned else "failed"

    short_pass = short_result["available"] and short_result["stored"] and short_result["found"]
    if include_long_term:
        long_pass = long_result["available"] and long_result["stored"] and long_result["found"]
    else:
        long_pass = True

    overall_pass = short_pass and long_pass
    status_code = 200 if overall_pass else 503

    return JSONResponse(
        {
            "overall_pass": overall_pass,
            "short_term": short_result,
            "long_term": long_result,
            "chat_long_term_promotion": {
                "enabled": CHAT_LONG_TERM_MEMORY_ENABLED,
                "min_chars": CHAT_LONG_TERM_MEMORY_MIN_CHARS,
            },
            "notes": [
                "Set CHAT_LONG_TERM_MEMORY_ENABLED=true to persist finalized chat turns into session long-term memory.",
                "If long_term.available=false, verify MEM0_API_KEY and MEM0_LONG_TERM_ENABLED.",
            ],
        },
        status_code=status_code,
    )


# ── Cache Management Endpoints ────────────────────────────────────────────────


@app.get("/api/cache/stats")
async def cache_stats_endpoint():
    """
    Get cache statistics (hit rate, keyspace info).

    Returns:
        {"available": true, "hit_rate": 0.85, "keyspace_hits": 1234, ...}
    """
    if not cache.available:
        return JSONResponse(
            {"available": False, "error": "Cache not available"},
            status_code=503,
        )

    try:
        stats = await cache.get_stats()
        return JSONResponse(stats)
    except Exception as e:
        logger.exception("Cache stats error")
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


# ── Phase 13/14 Data APIs ──────────────────────────────────────────────────────

_AIRPORT_COORDS: Dict[str, Dict[str, float]] = {
    "VHHH": {"lat": 22.3080, "lon": 113.9185},
    "EGLL": {"lat": 51.4700, "lon": -0.4543},
    "KJFK": {"lat": 40.6413, "lon": -73.7781},
    "WSSS": {"lat": 1.3644, "lon": 103.9915},
    "OMDB": {"lat": 25.2532, "lon": 55.3657},
    "RJTT": {"lat": 35.5494, "lon": 139.7798},
    "YSSY": {"lat": -33.9399, "lon": 151.1753},
    "LFPG": {"lat": 49.0097, "lon": 2.5479},
}


@app.get("/api/visualizations/airport-map")
async def airport_map_data(limit: int = 12):
    if not db.available:
        return JSONResponse({"airports": [], "error": "Database unavailable"}, status_code=503)
    rows = await db.latest_metar_by_airport(limit=limit)
    airports = []
    for r in rows:
        icao = str(r["icao"]).strip().upper()
        coords = _AIRPORT_COORDS.get(icao)
        if not coords:
            continue
        airports.append({
            "icao": icao,
            "lat": coords["lat"],
            "lon": coords["lon"],
            "obs_time": r["obs_time"].isoformat() if r["obs_time"] else None,
            "flight_cat": r["flight_cat"],
            "temp_c": r["temp_c"],
            "wind_speed_kt": r["wind_speed_kt"],
            "visibility_sm": r["visibility_sm"],
        })
    return JSONResponse({"airports": airports})


@app.get("/api/visualizations/weather-trends")
async def weather_trends_data(icaos: str = "VHHH,EGLL,KJFK", hours: int = 72):
    if not db.available:
        return JSONResponse({"points": [], "error": "Database unavailable"}, status_code=503)
    selected = [x.strip().upper()[:4] for x in icaos.split(",") if x.strip()]
    rows = await db.metar_trends(selected, hours=hours)
    points = [
        {
            "icao": str(r["icao"]).strip().upper(),
            "obs_time": r["obs_time"].isoformat() if r["obs_time"] else None,
            "wind_speed_kt": r["wind_speed_kt"],
            "temp_c": r["temp_c"],
        }
        for r in rows
    ]
    return JSONResponse({"points": points, "icaos": selected, "hours": hours})


@app.get("/api/visualizations/flight-paths")
async def flight_paths_data(limit: int = 8):
    """
    Build simple route-like edges from airport coordinates for workflow-style path viz.
    """
    selected = list(_AIRPORT_COORDS.keys())[: max(2, min(limit, len(_AIRPORT_COORDS)))]
    nodes = [
        {"id": icao, "label": icao, "lat": _AIRPORT_COORDS[icao]["lat"], "lon": _AIRPORT_COORDS[icao]["lon"]}
        for icao in selected
    ]
    edges = []
    for i in range(len(selected) - 1):
        src = selected[i]
        dst = selected[i + 1]
        edges.append({"id": f"{src}-{dst}", "source": src, "target": dst})
    return JSONResponse({"nodes": nodes, "edges": edges})


@app.get("/api/visualizations/safety-heatmap")
async def safety_heatmap_data(limit: int = 20):
    if not db.available:
        return JSONResponse({"cells": [], "error": "Database unavailable"}, status_code=503)
    rows = await db.safety_heatmap(limit=limit)
    cells = []
    for r in rows:
        icao = str(r["airport_icao"]).strip().upper()
        coords = _AIRPORT_COORDS.get(icao)
        if not coords:
            continue
        cells.append({
            "icao": icao,
            "lat": coords["lat"],
            "lon": coords["lon"],
            "incidents": int(r["incidents"]),
            "severity_score": int(r["severity_score"]),
        })
    return JSONResponse({"cells": cells})


@app.post("/api/performance/refresh-airport-stats")
async def refresh_airport_stats():
    if not db.available:
        return JSONResponse({"refreshed": False, "error": "Database unavailable"}, status_code=503)
    refreshed = await db.refresh_airport_stats()
    if not refreshed:
        return JSONResponse(
            {"refreshed": False, "error": "airport_stats materialized view not found"},
            status_code=404,
        )
    top = await db.airport_stats_view()
    return JSONResponse(
        {
            "refreshed": True,
            "top": [{"icao": r["icao"], "avg_wind": r["avg_wind"], "metar_count": r["metar_count"]} for r in top],
        }
    )


@app.post("/api/cache/clear")
async def clear_cache(request: Request):
    """
    Clear cache by pattern.

    Body:
        {"pattern": "weather:*"}  # pattern to clear (default: all)

    Returns:
        {"cleared": N}  # number of keys deleted
    """
    if not cache.available:
        return JSONResponse(
            {"error": "Cache not available"},
            status_code=503,
        )

    try:
        data = await request.json()
        pattern = data.get("pattern", "*")  # default: clear all

        cleared = await cache.clear_pattern(pattern)
        return JSONResponse({"cleared": cleared, "pattern": pattern})
    except Exception as e:
        logger.exception("Cache clear error")
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


@app.post("/api/cache/invalidate-knowledge")
async def invalidate_knowledge_cache():
    """
    Invalidate all long-term memory caches.

    Use this after batch document ingestion to ensure fresh results.

    Returns:
        {"cleared": N}
    """
    if not cache.available:
        return JSONResponse(
            {"error": "Cache not available"},
            status_code=503,
        )

    try:
        cleared = await cache.invalidate_knowledge_cache()
        return JSONResponse({
            "cleared": cleared,
            "message": "Long-term memory cache invalidated",
        })
    except Exception as e:
        logger.exception("Knowledge cache invalidation error")
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


# ── LangSmith Observability Endpoints ─────────────────────────────────────────


@app.post("/api/feedback")
async def submit_feedback(request: Request):
    """
    Submit user feedback as LangSmith feedback.

    Body:
        {
            "run_id": "2f3a2f5f-...",
            "trace_id": "abc123...",  # optional, helps LangSmith batched ingestion
            "session_id": "user-session-id",
            "score": 5,              # 1-5 rating
            "feedback_type": "user-rating",  # e.g., "user-rating", "relevance", "helpfulness"
            "comment": "Great answer!"  # optional
        }

    Returns:
        {"success": true} or {"success": false, "error": "..."}
    """
    try:
        data = await request.json()
        run_id = str(data.get("run_id") or data.get("trace_id") or "").strip()
        trace_id = str(data.get("trace_id") or "").strip() or None
        session_id = data.get("session_id", "unknown")
        score = data.get("score", 0)
        feedback_type = data.get("feedback_type", "user-rating")
        comment = data.get("comment", "")

        if not run_id:
            return JSONResponse(
                {"success": False, "error": "run_id required"},
                status_code=400,
            )

        if not isinstance(score, (int, float)) or score < 1 or score > 5:
            return JSONResponse(
                {"success": False, "error": "score must be a number between 1 and 5"},
                status_code=400,
            )

        success = _create_feedback(
            run_id=run_id,
            key=feedback_type,
            score=float(score),
            comment=comment,
            trace_id=trace_id,
        )

        if success:
            logger.info(
                "Feedback recorded: run=%s, score=%s, type=%s, session=%s",
                run_id[:8], score, feedback_type, session_id
            )
            return JSONResponse({"success": True})
        else:
            return JSONResponse(
                {"success": False, "error": "LangSmith not enabled or feedback submission failed"},
                status_code=503,
            )

    except Exception as e:
        logger.exception("Feedback endpoint error")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@app.get("/api/observability/status")
async def observability_status():
    """
    Check LangSmith observability status.

    Returns:
        {
            "langsmith_enabled": true/false,
            "endpoint": "https://api.smith.langchain.com",
            "features": ["tracing", "scoring"]
        }
    """
    return JSONResponse({
        "langsmith_enabled": _langsmith_enabled,
        "endpoint": _langsmith_endpoint(),
        "project": _langsmith_project(),
        "ui_url": _langsmith_ui_base(),
        "dashboard_url": _langsmith_dashboard_url(),
        "tracing_middleware_enabled": _langsmith_tracing_middleware_enabled,
        "reason": _langsmith_status_reason,
        "last_error": _langsmith_last_error or None,
        "features": ["tracing", "feedback", "session_tracking"] if _langsmith_enabled else [],
        "runtime": _runtime_stats(),
    })


@app.get("/api/runtime/status")
async def runtime_status():
    """Operational runtime status for autoscaling and production readiness checks."""
    return JSONResponse({
        "status": "ok",
        "runtime": _runtime_stats(),
        "timestamp": _now_iso(),
    })


async def run_queue_worker_forever() -> None:
    """Run only the workflow queue worker loop (no FastAPI server)."""
    global global_mcp_client, global_graph

    logging.basicConfig(level=logging.INFO)
    await db.connect()
    await memory_manager.init()
    await cache.init()

    if not global_graph:
        global_graph, global_mcp_client, _ = await init_graph(memory_manager=memory_manager, db=db)

    try:
        await _workflow_worker_loop()
    finally:
        if global_mcp_client:
            await global_mcp_client.cleanup()
        await db.close()
        await cache.close()


if __name__ == "__main__":
    process_mode = os.getenv("AGENT_PROCESS_MODE", "api").lower()
    if process_mode == "worker":
        asyncio.run(run_queue_worker_forever())
    else:
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8000)
