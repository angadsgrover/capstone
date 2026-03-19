"""
Health check utility for all system components.

Validates:
- Environment variables
- Database connectivity (PostgreSQL, Redis, Neo4j)
- MCP servers (aviation-weather, hk-climate, adsb)
- FastAPI agent server
- Frontend build

Usage:
    python health_check.py               # Check all services
    python health_check.py --service=postgres  # Check specific service
"""
import asyncio
import json
import logging
import os
import sys
from typing import Dict, Optional
from pathlib import Path

import httpx
import asyncpg
import redis.asyncio as aioredis
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.resolve()
AGENT_DIR = Path(__file__).parent.resolve()
ROOT_ENV = BASE_DIR / ".env"
AGENT_ENV = AGENT_DIR / ".env"


def load_env_files() -> bool:
    loaded = False
    if ROOT_ENV.exists():
        load_dotenv(ROOT_ENV)
        loaded = True
    if AGENT_ENV.exists():
        load_dotenv(AGENT_ENV, override=True)
        loaded = True
    return loaded


load_env_files()


class HealthChecker:
    """Comprehensive health checker for all system components."""

    def __init__(self, skip_frontend: Optional[bool] = None):
        if skip_frontend is None:
            env_skip = os.getenv("SKIP_FRONTEND_CHECK", "")
            skip_frontend = env_skip.lower() in {"1", "true", "yes"}
        self.skip_frontend = skip_frontend
        self.results: Dict[str, Dict[str, any]] = {}

    async def check_all(self) -> bool:
        """Run all health checks. Returns True if all pass."""
        logger.info("🏥 Running health checks...")

        checks = [
            ("environment", self.check_environment),
            ("postgres", self.check_postgres),
            ("redis", self.check_redis),
            ("neo4j", self.check_neo4j),
            ("mcp_aviation", lambda: self.check_mcp_server("aviation-weather", 8001)),
            ("mcp_hk", lambda: self.check_mcp_server("hk-climate", 8002)),
            ("mcp_adsb", lambda: self.check_mcp_server("adsb", 8003)),
            ("agent", self.check_agent_server),
        ]
        if not self.skip_frontend:
            checks.append(("frontend", self.check_frontend_build))

        for name, check_fn in checks:
            try:
                result = await check_fn() if asyncio.iscoroutinefunction(check_fn) else check_fn()
                self.results[name] = {"status": "✅ PASS", **result}
                logger.info(f"  ✅ {name}: {result.get('message', 'OK')}")
            except Exception as e:
                self.results[name] = {"status": "❌ FAIL", "error": str(e)}
                logger.error(f"  ❌ {name}: {e}")

        # Summary
        passed = sum(1 for r in self.results.values() if r["status"] == "✅ PASS")
        total = len(self.results)

        logger.info(f"\n📊 Health Check Summary: {passed}/{total} passed")

        if passed == total:
            logger.info("✅ All systems operational")
            return True
        else:
            logger.warning(f"⚠️  {total - passed} service(s) failed")
            return False

    # ── Environment ───────────────────────────────────────────────────────────

    def check_environment(self) -> Dict:
        """Check required environment variables."""
        required = ["LLM_API_KEY", "BASE_URL", "MODEL_CHOICE"]
        optional = [
            "POSTGRES_DSN",
            "REDIS_URL",
            "NEO4J_PASSWORD",
            "LANGFUSE_PUBLIC_KEY",
            "EMBED_MODEL",
        ]

        missing = [key for key in required if not os.getenv(key)]

        if missing:
            raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

        present_optional = [key for key in optional if os.getenv(key)]

        return {
            "message": f"Required: {len(required)}/{len(required)}, Optional: {len(present_optional)}/{len(optional)}",
            "model": os.getenv("MODEL_CHOICE"),
            "optional_enabled": present_optional,
        }

    # ── Databases ─────────────────────────────────────────────────────────────

    async def check_postgres(self) -> Dict:
        """Check PostgreSQL connectivity and schema."""
        dsn = os.getenv("POSTGRES_DSN")
        if not dsn:
            return {"message": "Not configured (optional)", "optional": True}

        conn = await asyncpg.connect(dsn, timeout=5)

        try:
            # Check tables
            tables = await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
            )
            table_names = [r["tablename"] for r in tables]

            # Check pgvector extension
            extensions = await conn.fetch("SELECT extname FROM pg_extension")
            has_vector = any(e["extname"] == "vector" for e in extensions)

            return {
                "message": f"{len(table_names)} tables, pgvector={'✓' if has_vector else '✗'}",
                "tables": table_names,
                "pgvector": has_vector,
            }

        finally:
            await conn.close()

    async def check_redis(self) -> Dict:
        """Check Redis connectivity."""
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            return {"message": "Not configured (optional)", "optional": True}

        client = aioredis.from_url(redis_url, decode_responses=True)

        try:
            # Ping test
            await client.ping()

            # Get info
            info = await client.info("server")

            return {
                "message": f"Redis {info.get('redis_version', 'unknown')}",
                "version": info.get("redis_version"),
            }

        finally:
            await client.aclose()

    async def check_neo4j(self) -> Dict:
        """Check Neo4j connectivity (optional)."""
        neo4j_uri = os.getenv("NEO4J_URI")
        if not neo4j_uri:
            return {"message": "Not configured (optional)", "optional": True}

        try:
            from neo4j import AsyncGraphDatabase

            neo4j_user = os.getenv("NEO4J_USER", "neo4j")
            neo4j_password = os.getenv("NEO4J_PASSWORD")

            if not neo4j_password:
                raise RuntimeError("NEO4J_PASSWORD not set")

            driver = AsyncGraphDatabase.driver(
                neo4j_uri, auth=(neo4j_user, neo4j_password)
            )

            async with driver.session() as session:
                result = await session.run("CALL dbms.components()")
                components = await result.single()
                version = components["versions"][0] if components else "unknown"

            await driver.close()

            return {"message": f"Neo4j {version}", "version": version}

        except ImportError:
            return {"message": "neo4j driver not installed (optional)", "optional": True}

    # ── MCP Servers ───────────────────────────────────────────────────────────

    async def check_mcp_server(self, name: str, port: int) -> Dict:
        """Check MCP server health (SSE mode)."""
        url = f"http://localhost:{port}/sse"

        async with httpx.AsyncClient() as client:
            # Test connection (HEAD or GET with short timeout)
            response = await client.get(url, timeout=3.0, follow_redirects=True)

            if response.status_code >= 500:
                raise RuntimeError(f"Server error: {response.status_code}")

            return {"message": f"Responding on port {port}", "port": port, "url": url}

    # ── Agent Server ──────────────────────────────────────────────────────────

    async def check_agent_server(self) -> Dict:
        """Check FastAPI agent server."""
        url = "http://localhost:8000/health"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, timeout=5.0)
                response.raise_for_status()

                data = response.json()
                return {
                    "message": f"Healthy (v{data.get('version', 'unknown')})",
                    "version": data.get("version"),
                    "uptime": data.get("uptime"),
                }

            except httpx.HTTPStatusError:
                # Fallback: try root endpoint
                response = await client.get("http://localhost:8000/", timeout=5.0)
                if response.status_code == 200:
                    return {"message": "Responding (no /health endpoint)", "legacy": True}
                raise

    # ── Frontend ──────────────────────────────────────────────────────────────

    def check_frontend_build(self) -> Dict:
        """Check frontend build artifacts."""
        frontend_dir = BASE_DIR / "frontend-app"
        dist_dir = frontend_dir / "dist"

        if not dist_dir.exists():
            try:
                response = httpx.get("http://localhost:5173", timeout=3.0)
                if response.status_code >= 500:
                    raise RuntimeError(f"Dev server error: {response.status_code}")
                return {
                    "message": "Dev server responding on port 5173",
                    "dev_server": True,
                }
            except Exception as e:
                raise FileNotFoundError(
                    f"Frontend not built and dev server not responding: {e}"
                ) from e

        # Count files
        files = list(dist_dir.rglob("*"))
        js_files = list(dist_dir.glob("assets/*.js"))
        css_files = list(dist_dir.glob("assets/*.css"))

        # Check index.html
        index_html = dist_dir / "index.html"
        if not index_html.exists():
            raise FileNotFoundError("index.html not found in dist/")

        return {
            "message": f"{len(js_files)} JS, {len(css_files)} CSS files",
            "files_count": len(files),
            "js_files": len(js_files),
            "css_files": len(css_files),
        }

    # ── Report ────────────────────────────────────────────────────────────────

    def print_report(self):
        """Print detailed health check report."""
        print("\n" + "=" * 60)
        print("  HEALTH CHECK REPORT")
        print("=" * 60)

        for name, result in self.results.items():
            status = result["status"]
            message = result.get("message", result.get("error", ""))
            print(f"{status} {name:20s} {message}")

        print("=" * 60 + "\n")


async def main():
    """Run health checks."""
    import argparse

    parser = argparse.ArgumentParser(description="System health checker")
    parser.add_argument(
        "--service", help="Check specific service only", choices=[
            "environment", "postgres", "redis", "neo4j",
            "mcp_aviation", "mcp_hk", "mcp_adsb",
            "agent", "frontend"
        ]
    )
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="Skip frontend health checks",
    )

    args = parser.parse_args()

    checker = HealthChecker(skip_frontend=args.skip_frontend)

    if args.service:
        # Check single service
        check_map = {
            "environment": checker.check_environment,
            "postgres": checker.check_postgres,
            "redis": checker.check_redis,
            "neo4j": checker.check_neo4j,
            "mcp_aviation": lambda: checker.check_mcp_server("aviation-weather", 8001),
            "mcp_hk": lambda: checker.check_mcp_server("hk-climate", 8002),
            "mcp_adsb": lambda: checker.check_mcp_server("adsb", 8003),
            "agent": checker.check_agent_server,
            "frontend": checker.check_frontend_build,
        }

        check_fn = check_map[args.service]
        try:
            result = await check_fn() if asyncio.iscoroutinefunction(check_fn) else check_fn()
            checker.results[args.service] = {"status": "✅ PASS", **result}
            logger.info(f"✅ {args.service}: {result.get('message', 'OK')}")
            success = True
        except Exception as e:
            checker.results[args.service] = {"status": "❌ FAIL", "error": str(e)}
            logger.error(f"❌ {args.service}: {e}")
            success = False

    else:
        # Check all
        success = await checker.check_all()

    if args.json:
        print(json.dumps(checker.results, indent=2))
    else:
        checker.print_report()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
