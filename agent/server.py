"""
FastAPI server for the LangGraph aviation weather agent.
"""
import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

try:
    import jwt
    from jwt import InvalidTokenError, PyJWKClient
except Exception:  # pragma: no cover - optional dependency handling
    jwt = None
    InvalidTokenError = Exception
    PyJWKClient = None

from db import Database
from memory import DualMemoryManager  # Upgraded from MemoryManager
from cache import CacheManager
from orchestrator import init_graph
import mcp_client as mcp_module

logger = logging.getLogger(__name__)

# ── Langfuse (optional observability) ─────────────────────────────────────────

_langfuse_enabled = False

def _init_langfuse() -> bool:
    """Initialize Langfuse SDK v3+ singleton if credentials are available."""
    global _langfuse_enabled

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")

    if not public_key or not secret_key:
        logger.info("Langfuse disabled: LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY not set")
        return False

    try:
        from langfuse import Langfuse

        # Support both LANGFUSE_HOST and LANGFUSE_BASE_URL for flexibility
        langfuse_host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com"
        
        # Initialize the singleton with explicit keys
        # This sets up the global client that get_client() will return
        Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=langfuse_host,
            enabled=True,
        )
        _langfuse_enabled = True
        logger.info("Langfuse initialized successfully (host: %s)", langfuse_host)
        return True
    except Exception as e:
        logger.warning("Langfuse initialization failed: %s", e)
        return False


def _shutdown_langfuse() -> None:
    """Flush and shutdown Langfuse client gracefully."""
    if not _langfuse_enabled:
        return
    try:
        from langfuse import get_client
        client = get_client()
        client.flush()
        client.shutdown()
        logger.info("Langfuse shutdown completed")
    except Exception as e:
        logger.warning("Langfuse shutdown error: %s", e)


def _score_trace(
    trace_id: str,
    name: str,
    value: float,
    data_type: str = "NUMERIC",
    comment: str = "",
) -> bool:
    """
    Add a score to a Langfuse trace.

    Args:
        trace_id: The Langfuse trace ID to score
        name: Score name (e.g., "user-feedback", "relevance")
        value: Numeric score value
        data_type: "NUMERIC" or "CATEGORICAL"
        comment: Optional comment explaining the score

    Returns:
        True if score was created, False otherwise
    """
    if not _langfuse_enabled:
        return False
    try:
        from langfuse import get_client
        client = get_client()
        client.create_score(
            trace_id=trace_id,
            name=name,
            value=value,
            data_type=data_type,
            comment=comment or None,
        )
        return True
    except Exception as e:
        logger.warning("Failed to score trace %s: %s", trace_id, e)
        return False


def _generate_trace_id(session_id: str, timestamp: Optional[str] = None) -> str:
    """
    Generate a deterministic trace ID for a session.

    This allows the frontend to predict the trace ID and link back to Langfuse.
    """
    import hashlib
    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat()
    seed = f"{session_id}:{timestamp}"
    return hashlib.sha256(seed.encode()).hexdigest()[:32]

# ── Module-level singletons ────────────────────────────────────────────────────

db             = Database()
memory_manager = DualMemoryManager()  # Unified short-term (mem0) + long-term (cognee)
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
ENABLE_WORKFLOW_WORKER = os.getenv("ENABLE_WORKFLOW_WORKER", "false").lower() == "true"
WORKFLOW_WORKER_POLL_SECONDS = float(os.getenv("WORKFLOW_WORKER_POLL_SECONDS", "1"))

graph_run_semaphore = asyncio.Semaphore(MAX_CONCURRENT_GRAPH_RUNS)

# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global global_graph, global_mcp_client, housekeeper_task, workflow_worker_task

    # Startup
    _init_langfuse()  # Initialize Langfuse early (before graph init)
    await db.connect()
    await memory_manager.init()
    await cache.init()  # Initialize Redis cache

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
    _shutdown_langfuse()  # Flush and shutdown Langfuse


app = FastAPI(lifespan=lifespan)
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
        "langfuse": _langfuse_enabled,
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
    
    return {
        "services": {
            "agent": global_graph is not None,
            "database": db.available,
            "cache": cache.available,
            "langfuse": _langfuse_enabled,
            "short_term_memory": memory_manager.short_term_available,
            "long_term_memory": memory_manager.long_term_available,
        },
        "event_tracking": {
            "backend": EVENT_BACKEND,
            "available": event_backend_ok,
            "active_streams": len(run_started_at) if _redis_events_enabled() else len(event_queues),
            "tracked_sessions": len(session_latest_run),
        },
        "langfuse": {
            "enabled": _langfuse_enabled,
            "host": (os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com") if _langfuse_enabled else None,
        },
        "runtime": _runtime_stats(),
        "timestamp": _now_iso(),
    }

# ── Globals ────────────────────────────────────────────────────────────────────

global_graph = None
global_mcp_client = None
event_queues: Dict[str, asyncio.Queue] = {}
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
    }
    try:
        await cache._redis.lpush(WORKFLOW_QUEUE_KEY, json.dumps(job))
        return True
    except Exception as e:
        logger.warning("Failed to enqueue workflow job %s: %s", run_id, e)
        return False


async def _workflow_worker_loop() -> None:
    if not cache.available or getattr(cache, "_redis", None) is None:
        logger.warning("Workflow worker requested but Redis cache is unavailable")
        return

    logger.info("Workflow worker started (queue=%s)", WORKFLOW_QUEUE_KEY)
    while not workflow_worker_stop_event.is_set():
        try:
            item = await cache._redis.brpop(WORKFLOW_QUEUE_KEY, timeout=5)
            if not item:
                await asyncio.sleep(WORKFLOW_WORKER_POLL_SECONDS)
                continue

            _, raw_payload = item
            try:
                job = json.loads(raw_payload)
            except Exception:
                logger.warning("Skipping invalid workflow queue payload")
                continue

            run_id = str(job.get("run_id", "")).strip()
            session_id = _safe_session_id(str(job.get("session_id", "")).strip())
            user_input = str(job.get("user_input", ""))

            if not run_id or not user_input:
                logger.warning("Skipping workflow job with missing run_id/user_input")
                continue

            await _run_with_events(user_input, session_id, event_key=run_id)
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


# ── Langfuse callback helpers ─────────────────────────────────────────────────

def _make_langfuse_callback():
    """
    Create a Langfuse CallbackHandler for LangChain/LangGraph tracing.

    In SDK v3+, the CallbackHandler uses the pre-initialized singleton client.
    Trace attributes (session_id, user_id, tags) are passed via metadata in invoke().
    """
    if not _langfuse_enabled:
        return None
    try:
        from langfuse.langchain import CallbackHandler
        # v3+ pattern: no constructor args, uses singleton client
        return CallbackHandler()
    except Exception as e:
        logger.warning("Langfuse callback unavailable: %s", e)
        return None


def _build_config(session_id: str, trace_name: str = "", user_id: str = "") -> dict:
    """
    Build LangGraph config with thread_id and optional Langfuse callbacks.

    Trace attributes are passed via metadata (v3+ pattern):
    - langfuse_session_id: Groups traces into a session
    - langfuse_user_id: Associates traces with a user
    - langfuse_tags: List of tags for filtering
    """
    cfg: dict = {
        "configurable": {"thread_id": session_id},
        "metadata": {
            "langfuse_session_id": session_id,
            "langfuse_trace_name": trace_name or session_id[:80],
        },
    }
    if user_id:
        cfg["metadata"]["langfuse_user_id"] = user_id

    lf = _make_langfuse_callback()
    if lf:
        cfg["callbacks"] = [lf]
    return cfg


# ── Workflow-event SSE helpers ─────────────────────────────────────────────────

async def _push(session_id: str, data: Dict[str, Any]) -> None:
    if _redis_events_enabled():
        try:
            await _append_redis_event(session_id, data)
            return
        except Exception as e:
            logger.debug("Redis event push failed for %s: %s", session_id, e)

    q = event_queues.get(session_id)
    if q:
        payload = json.dumps(data)
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            # Backpressure strategy for scale: drop oldest event to keep freshest state.
            try:
                _ = q.get_nowait()
                q.put_nowait(payload)
                run_dropped_events[session_id] = run_dropped_events.get(session_id, 0) + 1
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                run_dropped_events[session_id] = run_dropped_events.get(session_id, 0) + 1


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


async def _run_with_events(user_input: str, session_id: str, event_key: Optional[str] = None) -> None:
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
        return

    config = _build_config(graph_session_id, trace_name=user_input[:80])
    active_nodes: set[str] = set()
    node_start: dict[str, float] = {}
    tool_start: dict[str, float] = {}
    current_specialist: str = ""
    routing_emitted: bool = False
    router_started_at: float = 0.0

    # Per-session step tracking (counts LLM → tool-call rounds in a specialist)
    step_counts: dict[str, int] = {}   # keyed by specialist node name

    INTERNAL = {"agent", "tools", *PLANNING_INTERNAL_NODES}
    INTERNAL_LABELS = {"agent": "LLM Call", "tools": "Tool Execution"}

    await graph_run_semaphore.acquire()
    active_graph_runs += 1
    if active_graph_runs > max_active_graph_runs_seen:
        max_active_graph_runs_seen = active_graph_runs

    try:
        request_id = f"{graph_session_id}:{uuid.uuid4().hex}"
        mcp_module.set_request_context(request_id)
        async for ev in global_graph.astream_events(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
            version="v2",
        ):
            kind    = ev.get("event", "")
            meta    = ev.get("metadata", {})
            node    = meta.get("langgraph_node", "")
            ts      = _now_iso()

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
        mcp_module.clear_request_context()
        await _push(session_id, {"__done__": True})


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

    async with event_queues_lock:
        # Opportunistic cleanup before admission checks.
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
            event_queues[run_id] = asyncio.Queue(maxsize=EVENT_QUEUE_MAXSIZE)
        session_latest_run[session_id] = run_id
        run_session_index[run_id] = session_id
        run_started_at[run_id] = now
        run_dropped_events[run_id] = 0

    await _set_run_metadata(run_id, session_id)
    await _set_session_latest(session_id, run_id)

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

    asyncio.create_task(_run_with_events(user_input, session_id, event_key=run_id))
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

        q: Optional[asyncio.Queue] = event_queues.get(effective_run_id)
        if q is None:
            yield "event: end\ndata: {}\n\n"
            return

        try:
            while True:
                try:
                    raw = await asyncio.wait_for(q.get(), timeout=60.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                try:
                    if json.loads(raw).get("__done__"):
                        saw_done = True
                        yield "event: end\ndata: {}\n\n"
                        break
                except (json.JSONDecodeError, AttributeError):
                    pass
                yield f"data: {raw}\n\n"
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
    now = time.time()
    if not _redis_events_enabled():
        event_queues[run_id] = asyncio.Queue(maxsize=EVENT_QUEUE_MAXSIZE)
    session_latest_run[effective_session_id] = run_id
    run_session_index[run_id] = effective_session_id
    run_started_at[run_id] = now
    run_dropped_events[run_id] = 0
    
    # Set Redis metadata for workflow events (if Redis enabled)
    await _set_run_metadata(run_id, effective_session_id)
    await _set_session_latest(effective_session_id, run_id)

    async def stream_tokens():
        global active_graph_runs, max_active_graph_runs_seen

        current_specialist = ""
        tool_start_times: Dict[str, float] = {}
        step_counts: Dict[str, int] = {}
        streamed_chunk_counts: Dict[str, int] = {}
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
            async for ev in global_graph.astream_events(
                {"messages": [HumanMessage(content=input)]},
                config=config,
                version="v2",
            ):
                kind = ev.get("event", "")
                meta = ev.get("metadata", {})
                node = meta.get("langgraph_node", "")
                ts = _now_iso()

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
                            "raw": {},
                        })

                # ── Routing decision ─────────────────────────────────────────
                if kind == "on_chain_start" and node in SPECIALIST_NODES:
                    current_specialist = node
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
                    elif content:
                        # Some providers do not emit token chunks for every model end event.
                        # Emit a synthetic chunk so clients always receive visible answer text.
                        if streamed_chunk_counts.get(parent, 0) == 0:
                            yield f"event: chunk\ndata: {json.dumps({'chunk': content})}\n\n"
                        step_num = step_counts.get(parent, 0) + 1
                        step_counts[parent] = step_num
                        preview = content[:120].replace("\n", " ")
                        yield f"event: thinking\ndata: {json.dumps({'type': 'synthesis', 'thinking': f'Step {step_num}: Synthesizing response', 'result': preview, 'step': step_num, 'timestamp': ts})}\n\n"

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
                        "raw": {},
                    })
                    active_nodes.discard(node)

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


# ── Knowledge Graph / Document Ingestion Endpoints ────────────────────────────


@app.post("/api/knowledge/ingest")
async def ingest_document(request: Request):
    """
    Ingest a document into long-term knowledge graph (cognee).

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
            {"success": False, "error": "Long-term memory (cognee) unavailable"},
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
            {"success": False, "error": "Long-term memory (cognee) unavailable"},
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
    Search long-term knowledge graph.

    Query params:
        - query: Search query (required)
        - dataset: Dataset name (default: aviation_knowledge)
        - limit: Max results (default: 5, max: 10)

    Returns:
        {"results": "formatted knowledge graph results", "cached": bool}
    """
    if not query:
        return JSONResponse(
            {"error": "No query provided"},
            status_code=400,
        )

    if not memory_manager.long_term_available:
        return JSONResponse(
            {"results": "Long-term memory (cognee) unavailable"},
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

        # Cache miss: query knowledge graph
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
    Retrieve entity information from knowledge graph.

    Path params:
        - entity_name: Entity identifier (e.g., "EGLL", "Boeing 737")

    Query params:
        - dataset: Dataset name (default: aviation_knowledge)

    Returns:
        {"entity": {...}} or {"error": "Not found"}
    """
    if not memory_manager.long_term_available:
        return JSONResponse(
            {"error": "Long-term memory (cognee) unavailable"},
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
            "long_term": {"available": true, "provider": "cognee"},
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
            "provider": "cognee",
            "description": "Persistent knowledge graph (domain expertise)",
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
    Invalidate all knowledge graph caches.

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
            "message": "Knowledge graph cache invalidated",
        })
    except Exception as e:
        logger.exception("Knowledge cache invalidation error")
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


# ── Langfuse Observability Endpoints ──────────────────────────────────────────


@app.post("/api/feedback")
async def submit_feedback(request: Request):
    """
    Submit user feedback as a Langfuse score.

    Body:
        {
            "trace_id": "abc123...",
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
        trace_id = data.get("trace_id")
        session_id = data.get("session_id", "unknown")
        score = data.get("score", 0)
        feedback_type = data.get("feedback_type", "user-rating")
        comment = data.get("comment", "")

        if not trace_id:
            return JSONResponse(
                {"success": False, "error": "trace_id required"},
                status_code=400,
            )

        if not isinstance(score, (int, float)) or score < 1 or score > 5:
            return JSONResponse(
                {"success": False, "error": "score must be a number between 1 and 5"},
                status_code=400,
            )

        success = _score_trace(
            trace_id=trace_id,
            name=feedback_type,
            value=float(score),
            data_type="NUMERIC",
            comment=comment,
        )

        if success:
            logger.info(
                "Feedback recorded: trace=%s, score=%s, type=%s",
                trace_id[:8], score, feedback_type
            )
            return JSONResponse({"success": True})
        else:
            return JSONResponse(
                {"success": False, "error": "Langfuse not enabled or scoring failed"},
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
    Check Langfuse observability status.

    Returns:
        {
            "langfuse_enabled": true/false,
            "host": "https://cloud.langfuse.com",
            "features": ["tracing", "scoring"]
        }
    """
    return JSONResponse({
        "langfuse_enabled": _langfuse_enabled,
        "host": os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com") if _langfuse_enabled else None,
        "features": ["tracing", "scoring", "session_tracking"] if _langfuse_enabled else [],
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
