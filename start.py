#!/usr/bin/env python3
"""
Unified entry point for Aviation Intelligence Platform.

Features:
- Environment validation
- Service orchestration (MCP servers → Agent → Frontend)
- Health checks with retries
- Graceful shutdown
- Integration testing

Usage:
    python start.py                    # Start all services
    python start.py --check-only       # Health checks only (no startup)
    python start.py --test             # Start + run integration tests
    python start.py --docker           # Use Docker Compose instead
    python start.py --skip-frontend    # Skip frontend dev server
    python start.py --help             # Show all options
"""
import argparse
import asyncio
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Paths
BASE_DIR = Path(__file__).parent.resolve()
AGENT_DIR = BASE_DIR / "agent"
FRONTEND_DIR = BASE_DIR / "frontend-app"
ROOT_VENV = BASE_DIR / ".venv"
ROOT_ENV = BASE_DIR / ".env"
AGENT_ENV = AGENT_DIR / ".env"
MCP_DIRS = {
    "aviation-weather": BASE_DIR / "aviation-weather-mcp-python",
    "hk-climate": BASE_DIR / "hk-climate-mcp-server-python",
    "adsb": BASE_DIR / "adsb_mcp",
}

MCP_MODULES = {
    "aviation-weather": "aviation_weather_mcp_server",
    "hk-climate": "hk_climate_mcp_server",
}

def load_env_files() -> bool:
    """Load env from root .env and optionally agent/.env (overrides)."""
    loaded = False
    if ROOT_ENV.exists():
        load_dotenv(ROOT_ENV)
        loaded = True
    if AGENT_ENV.exists():
        load_dotenv(AGENT_ENV, override=True)
        loaded = True
    return loaded


load_env_files()


class ServiceOrchestrator:
    """Manages startup, health checks, and shutdown of all services."""

    def __init__(self, args):
        self.args = args
        self.processes: Dict[str, subprocess.Popen] = {}
        self.shutdown_requested = False

        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        if not self.shutdown_requested:
            logger.info("\n🛑 Shutdown requested...")
            self.shutdown_requested = True
            self.stop_all_services()
            sys.exit(0)

    def _venv_python_for_service(self, service_dir: Path) -> Optional[Path]:
        """Return python executable for a service, preferring local .venv then shared root .venv."""
        local_py = service_dir / ".venv" / "bin" / "python3"
        if local_py.exists():
            return local_py

        shared_py = ROOT_VENV / "bin" / "python3"
        if shared_py.exists():
            return shared_py

        return None

    # ── Pre-flight checks ─────────────────────────────────────────────────────

    def validate_environment(self) -> bool:
        """Validate environment setup."""
        logger.info("🔍 Validating environment...")

        # Check Python version
        if sys.version_info < (3, 10):
            logger.error("  ❌ Python 3.10+ required (found %s)", sys.version)
            return False

        # Check .env file
        if not (ROOT_ENV.exists() or AGENT_ENV.exists()):
            logger.error("  ❌ Missing .env file")
            logger.info("     Copy .env.example to .env (repo root) and configure")
            logger.info("     Alternatively, place an override at agent/.env")
            return False

        # Check required env vars
        required = ["LLM_API_KEY", "BASE_URL", "MODEL_CHOICE"]
        missing = [key for key in required if not os.getenv(key)]

        if missing:
            logger.error("  ❌ Missing environment variables: %s", ", ".join(missing))
            return False

        # Check virtual environment availability
        shared_venv = ROOT_VENV / "bin" / "python3"
        if not shared_venv.exists():
            logger.warning("  ⚠️  Missing shared .venv (recommended for local dev)")

        for name, mcp_dir in MCP_DIRS.items():
            if not self._venv_python_for_service(mcp_dir):
                logger.warning("  ⚠️  Missing python env for %s (create %s/.venv or root .venv)", name, mcp_dir.name)

        if not self._venv_python_for_service(AGENT_DIR):
            logger.error("  ❌ Missing Python environment for agent (create agent/.venv or root .venv)")
            logger.info("     Recommended: bash ./start-local-new-drive.sh")
            return False

        # Check frontend node_modules
        if not self.args.skip_frontend:
            node_modules = FRONTEND_DIR / "node_modules"
            if not node_modules.exists():
                logger.warning("  ⚠️  Missing frontend/node_modules (run: cd frontend-app && npm install)")

        logger.info("  ✅ Environment validation passed")
        return True

    # ── Service Management ────────────────────────────────────────────────────

    def start_mcp_servers(self) -> bool:
        """Start all MCP servers in SSE mode."""
        logger.info("🚀 Starting MCP servers...")

        ports = {
            "aviation-weather": 8001,
            "hk-climate": 8002,
            "adsb": 8003,
        }

        for name, mcp_dir in MCP_DIRS.items():
            if not mcp_dir.exists():
                logger.warning(f"  ⚠️  Skipping {name} (directory not found)")
                continue

            venv_python = self._venv_python_for_service(mcp_dir)
            if not venv_python:
                logger.warning(f"  ⚠️  Skipping {name} (python env not found)")
                continue

            port = ports[name]

            env = os.environ.copy()
            env.update({
                "PYTHONPATH": str(mcp_dir),
                "TRANSPORT_MODE": "sse",
                "PORT": str(port),
                "HOST": "0.0.0.0",
            })

            # Determine module/script
            if name == "adsb":
                cmd = [str(venv_python), str(mcp_dir / "server.py")]
            else:
                module = MCP_MODULES.get(name, name.replace("-", "_") + "_server")
                cmd = [str(venv_python), "-m", module]

            try:
                process = subprocess.Popen(
                    cmd,
                    cwd=str(mcp_dir),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

                self.processes[f"mcp-{name}"] = process
                logger.info(f"  ✅ {name} → http://localhost:{port}/sse (pid {process.pid})")

            except Exception as e:
                logger.error(f"  ❌ Failed to start {name}: {e}")
                return False

        # Wait for MCP servers to be ready
        logger.info("⏳ Waiting 6s for MCP servers to initialize...")
        time.sleep(6)

        return True

    def start_agent_server(self) -> bool:
        """Start FastAPI agent server."""
        logger.info("🚀 Starting FastAPI agent server...")

        venv_python = self._venv_python_for_service(AGENT_DIR)
        if not venv_python:
            logger.error("  ❌ Agent python environment not found")
            return False

        env = os.environ.copy()
        # Load root .env, then agent/.env overrides
        for env_file in (ROOT_ENV, AGENT_ENV):
            if env_file.exists():
                with open(env_file) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            env[key.strip()] = value.strip()

        cmd = [
            str(venv_python),
            "-m",
            "uvicorn",
            "server:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ]

        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(AGENT_DIR),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.processes["agent"] = process
            logger.info(f"  ✅ Agent API → http://localhost:8000 (pid {process.pid})")

            # Wait for agent to be ready
            logger.info("⏳ Waiting 10s for agent to initialize...")
            time.sleep(10)

            return True

        except Exception as e:
            logger.error(f"  ❌ Failed to start agent: {e}")
            return False

    def start_frontend_server(self) -> bool:
        """Start Vite frontend dev server."""
        if self.args.skip_frontend:
            logger.info("⏭️  Skipping frontend (--skip-frontend)")
            return True

        logger.info("🚀 Starting Vite frontend...")

        node_modules = FRONTEND_DIR / "node_modules"
        if not node_modules.exists():
            logger.warning("  ⚠️  Running npm install first...")
            npm_install = subprocess.run(
                ["npm", "install"],
                cwd=str(FRONTEND_DIR),
                capture_output=True,
                text=True,
            )
            if npm_install.returncode != 0:
                logger.error(f"  ❌ npm install failed: {npm_install.stderr}")
                return False

        cmd = ["npm", "run", "dev"]

        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(FRONTEND_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.processes["frontend"] = process
            logger.info(f"  ✅ Frontend → http://localhost:5173 (pid {process.pid})")

            return True

        except Exception as e:
            logger.error(f"  ❌ Failed to start frontend: {e}")
            return False

    def stop_all_services(self):
        """Stop all running services."""
        logger.info("🛑 Stopping all services...")

        for name, process in self.processes.items():
            try:
                logger.info(f"  Stopping {name} (pid {process.pid})...")
                process.terminate()

                # Wait up to 5s for graceful shutdown
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(f"  Force-killing {name}...")
                    process.kill()

            except Exception as e:
                logger.error(f"  ❌ Error stopping {name}: {e}")

        logger.info("✅ All services stopped")

    # ── Health Checks ─────────────────────────────────────────────────────────

    async def run_health_checks(self, retry: int = 3) -> bool:
        """Run health checks with retries."""
        logger.info("🏥 Running health checks...")

        sys_path_backup = sys.path.copy()

        try:
            # Add agent dir to path temporarily
            sys.path.insert(0, str(AGENT_DIR))

            from health_check import HealthChecker

            checker = HealthChecker(skip_frontend=self.args.skip_frontend)

            for attempt in range(1, retry + 1):
                if attempt > 1:
                    logger.info(f"  Retry {attempt}/{retry}...")

                success = await checker.check_all()

                if success:
                    return True

                if attempt < retry:
                    logger.info("  ⏳ Waiting 5s before retry...")
                    await asyncio.sleep(5)

            logger.error("❌ Health checks failed after %d attempts", retry)
            return False

        finally:
            sys.path = sys_path_backup

    async def run_integration_tests(self) -> bool:
        """Run integration tests."""
        logger.info("🧪 Running integration tests...")

        sys_path_backup = sys.path.copy()

        try:
            sys.path.insert(0, str(AGENT_DIR))

            from system_test import SystemTester

            tester = SystemTester()
            success = await tester.run_all_tests()

            return success

        finally:
            sys.path = sys_path_backup

    # ── Main Workflow ─────────────────────────────────────────────────────────

    async def start_all(self) -> bool:
        """Start all services and run checks."""
        try:
            # 1. Validate environment
            if not self.validate_environment():
                return False

            # 2. Start MCP servers
            if not self.start_mcp_servers():
                return False

            # 3. Start agent server
            if not self.start_agent_server():
                return False

            # 4. Start frontend (optional)
            if not self.start_frontend_server():
                return False

            logger.info("\n" + "=" * 60)
            logger.info("  ✅ ALL SERVICES STARTED")
            logger.info("=" * 60)
            logger.info("  Agent API:  http://localhost:8000")
            logger.info("  Frontend:   http://localhost:5173")
            logger.info("  MCP Servers:")
            logger.info("    - Aviation Weather: http://localhost:8001/sse")
            logger.info("    - HK Climate:       http://localhost:8002/sse")
            logger.info("    - ADS-B:            http://localhost:8003/sse")
            logger.info("=" * 60 + "\n")

            # 5. Run health checks
            if not await self.run_health_checks():
                logger.warning("⚠️  Some health checks failed (services may still be starting)")

            # 6. Run integration tests (optional)
            if self.args.test:
                await asyncio.sleep(2)  # Brief pause
                if not await self.run_integration_tests():
                    logger.warning("⚠️  Some integration tests failed")

            # 7. Keep running
            if not self.args.detach:
                logger.info("✨ System ready! Press Ctrl+C to stop all services.\n")
                try:
                    # Monitor processes
                    while not self.shutdown_requested:
                        await asyncio.sleep(1)

                        # Check if any process died
                        for name, process in list(self.processes.items()):
                            if process.poll() is not None:
                                logger.error(f"❌ {name} exited unexpectedly (code {process.returncode})")

                                # Show last few lines of stderr
                                if process.stderr:
                                    stderr_lines = process.stderr.read().split("\n")[-5:]
                                    for line in stderr_lines:
                                        if line.strip():
                                            logger.error(f"   {line}")

                except asyncio.CancelledError:
                    pass

            return True

        except Exception as e:
            logger.error(f"❌ Startup failed: {e}")
            import traceback
            traceback.print_exc()
            return False

        finally:
            if not self.args.detach:
                self.stop_all_services()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Aviation Intelligence Platform - Unified Startup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Run health checks only (no service startup)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run integration tests after startup",
    )
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Use Docker Compose instead of local services",
    )
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="Skip frontend dev server",
    )
    parser.add_argument(
        "--detach",
        action="store_true",
        help="Start services in background and exit",
    )

    args = parser.parse_args()

    # Handle Docker mode
    if args.docker:
        logger.info("🐳 Starting services with Docker Compose...")
        cmd = ["docker", "compose", "up", "-d"]

        if args.test:
            cmd.remove("-d")  # Run in foreground for tests

        result = subprocess.run(cmd, cwd=str(BASE_DIR))
        sys.exit(result.returncode)

    # Handle check-only mode
    if args.check_only:
        logger.info("🔍 Health check mode (no service startup)")
        orchestrator = ServiceOrchestrator(args)
        success = asyncio.run(orchestrator.run_health_checks())
        sys.exit(0 if success else 1)

    # Normal startup
    orchestrator = ServiceOrchestrator(args)

    try:
        success = asyncio.run(orchestrator.start_all())
        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        logger.info("\n👋 Goodbye!")
        orchestrator.stop_all_services()
        sys.exit(0)


if __name__ == "__main__":
    main()
