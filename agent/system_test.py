"""
End-to-end system integration tests.

Tests:
1. Simple query → Aviation weather specialist
2. Multi-turn conversation with memory
3. Tool composition (if advanced_tools available)
4. Plan-and-execute mode (if planning available)
5. Error handling and self-healing

Usage:
    python system_test.py                    # Run all tests
    python system_test.py --test=memory      # Run specific test
    python system_test.py --quick            # Quick smoke test only
"""
import asyncio
import json
import logging
import os
import sys
import time
import uuid
from typing import Dict, List, Tuple

import httpx
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

AGENT_URL = os.getenv("AGENT_URL", "http://localhost:8000")


class SystemTester:
    """End-to-end integration test suite."""

    def __init__(self):
        self.results: Dict[str, bool] = {}
        self.session_id = f"test-{uuid.uuid4().hex[:8]}"

    async def run_all_tests(self, quick: bool = False) -> bool:
        """Run all integration tests."""
        logger.info("🧪 Running system integration tests...")
        logger.info(f"   Session ID: {self.session_id}")

        tests = [
            ("smoke", self.test_smoke),
        ]

        if not quick:
            tests.extend([
                ("simple_query", self.test_simple_query),
                ("memory", self.test_memory),
                ("streaming", self.test_streaming),
                ("tool_composition", self.test_tool_composition),
                ("planning", self.test_planning_mode),
                ("error_handling", self.test_error_handling),
            ])

        for name, test_fn in tests:
            logger.info(f"\n▶ Running test: {name}")
            try:
                await test_fn()
                self.results[name] = True
                logger.info(f"  ✅ {name}: PASS")
            except Exception as e:
                self.results[name] = False
                logger.error(f"  ❌ {name}: FAIL - {e}")

        # Summary
        passed = sum(self.results.values())
        total = len(self.results)

        logger.info(f"\n📊 Test Summary: {passed}/{total} passed")

        if passed == total:
            logger.info("✅ All tests passed")
            return True
        else:
            logger.warning(f"⚠️  {total - passed} test(s) failed")
            return False

    # ── Test Cases ────────────────────────────────────────────────────────────

    async def test_smoke(self):
        """Smoke test: Check server is responding."""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{AGENT_URL}/health", timeout=5.0)
            response.raise_for_status()

            assert response.status_code == 200

    async def test_simple_query(self):
        """Test simple query to aviation weather specialist."""
        query = "What is the METAR for EGLL?"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AGENT_URL}/api/agent",
                json={"input": query, "session_id": self.session_id},
                timeout=30.0,
            )
            response.raise_for_status()

            data = response.json()

            assert "response" in data
            assert len(data["response"]) > 10, "Response too short"

            # Check if routed to aviation weather
            if "routing_decision" in data:
                assert data["routing_decision"] == "aviation_weather"

            logger.info(f"   Response: {data['response'][:100]}...")

    async def test_memory(self):
        """Test multi-turn conversation with memory."""
        # Turn 1: Ask about EGLL
        query1 = "What's the weather at London Heathrow?"
        session_id = f"test-memory-{uuid.uuid4().hex[:8]}"

        async with httpx.AsyncClient() as client:
            response1 = await client.post(
                f"{AGENT_URL}/api/agent",
                json={"input": query1, "session_id": session_id},
                timeout=30.0,
            )
            response1.raise_for_status()
            data1 = response1.json()

            logger.info(f"   Turn 1: {data1['response'][:80]}...")

            # Turn 2: Follow-up (should remember EGLL)
            await asyncio.sleep(1)  # Brief pause

            query2 = "What about the TAF for that airport?"

            response2 = await client.post(
                f"{AGENT_URL}/api/agent",
                json={"input": query2, "session_id": session_id},
                timeout=30.0,
            )
            response2.raise_for_status()
            data2 = response2.json()

            logger.info(f"   Turn 2: {data2['response'][:80]}...")

            # Verify response mentions TAF or EGLL
            assert any(
                keyword in data2["response"].upper()
                for keyword in ["TAF", "EGLL", "FORECAST"]
            ), "Memory not working (didn't recall airport)"

    async def test_streaming(self):
        """Test SSE streaming endpoint."""
        query = "Give me the METAR for KJFK"

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "GET",
                f"{AGENT_URL}/api/agent/stream",
                params={"input": query, "session_id": self.session_id},
                timeout=30.0,
            ) as response:
                response.raise_for_status()

                current_event = ""
                chunks = []
                reasoning = []
                generic_events = 0
                stream_error = None
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                        continue

                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str and data_str != "[DONE]":
                            try:
                                chunk_data = json.loads(data_str)
                                if current_event == "chunk" and "chunk" in chunk_data:
                                    chunks.append(chunk_data["chunk"])
                                elif current_event == "thinking":
                                    text = chunk_data.get("result") or chunk_data.get("thinking")
                                    if text:
                                        reasoning.append(text)
                                elif "error" in chunk_data and chunk_data.get("error"):
                                    stream_error = str(chunk_data.get("error"))
                                else:
                                    generic_events += 1
                            except json.JSONDecodeError:
                                pass

                full_response = "".join(chunks)
                stream_text = full_response or " ".join(reasoning)

                assert not stream_error, f"Streaming returned error: {stream_error}"
                assert (
                    len(stream_text.strip()) > 10
                    or generic_events > 0
                ), "Streaming produced no usable events"
                logger.info(
                    "   Streamed %d chunks and %d reasoning events: %s...",
                    len(chunks),
                    len(reasoning),
                    stream_text[:80],
                )

    async def test_tool_composition(self):
        """Test tool composition (if advanced_tools available)."""
        try:
            from advanced_tools import ToolComposer

            logger.info("   Tool composition available - testing...")

            # Check if agent supports composite tools
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{AGENT_URL}/api/capabilities", timeout=5.0)

                if response.status_code == 404:
                    logger.info("   Skipping: Agent doesn't expose capabilities endpoint")
                    return

                data = response.json()
                if not data.get("tool_composition"):
                    logger.info("   Skipping: Tool composition not enabled")
                    return

                # Test with query that benefits from composition
                query = "Get full weather briefing for EGLL (METAR, TAF, PIREPs)"

                response = await client.post(
                    f"{AGENT_URL}/api/agent",
                    json={"input": query, "session_id": self.session_id},
                    timeout=60.0,
                )
                response.raise_for_status()

                data = response.json()
                assert "response" in data
                logger.info(f"   Composite tool result: {data['response'][:80]}...")

        except ImportError:
            logger.info("   Skipping: advanced_tools not available")

    async def test_planning_mode(self):
        """Test plan-and-execute mode for complex queries."""
        try:
            from planning import should_use_planning

            logger.info("   Planning mode available - testing...")

            # Complex query that should trigger planning
            query = "Compare weather at EGLL and KJFK, then recommend the better airport for departure"

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{AGENT_URL}/api/agent",
                    json={"input": query, "session_id": self.session_id, "enable_planning": True},
                    timeout=90.0,
                )
                response.raise_for_status()

                data = response.json()

                # Check if planning was used
                if "plan_steps" in data:
                    logger.info(f"   Plan had {len(data['plan_steps'])} steps")
                    assert len(data["plan_steps"]) >= 2, "Plan too simple"

                assert "response" in data
                assert len(data["response"]) > 50, "Planning response too short"

                logger.info(f"   Planning result: {data['response'][:80]}...")

        except ImportError:
            logger.info("   Skipping: planning module not available")

    async def test_error_handling(self):
        """Test error handling with invalid input."""
        query = "Get METAR for INVALID_ICAO_CODE_XYZ123"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AGENT_URL}/api/agent",
                json={"input": query, "session_id": self.session_id},
                timeout=30.0,
            )

            # Should still return 200 with error message in response
            if response.status_code == 200:
                data = response.json()
                assert "response" in data

                # Check if error is gracefully handled
                response_text = data["response"].lower()
                assert any(
                    keyword in response_text
                    for keyword in ["error", "invalid", "not found", "unable"]
                ), "Error not properly communicated"

                logger.info(f"   Error handled gracefully: {data['response'][:80]}...")

            elif response.status_code in [400, 422]:
                # Also acceptable: explicit error response
                logger.info(f"   Error returned as {response.status_code} (acceptable)")
            else:
                raise AssertionError(f"Unexpected status code: {response.status_code}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def print_report(self):
        """Print test report."""
        print("\n" + "=" * 60)
        print("  INTEGRATION TEST REPORT")
        print("=" * 60)

        for name, passed in self.results.items():
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{status}  {name}")

        print("=" * 60 + "\n")


async def main():
    """Run integration tests."""
    import argparse

    parser = argparse.ArgumentParser(description="System integration tester")
    parser.add_argument(
        "--test",
        help="Run specific test only",
        choices=[
            "smoke", "simple_query", "memory", "streaming",
            "tool_composition", "planning", "error_handling"
        ],
    )
    parser.add_argument("--quick", action="store_true", help="Quick smoke test only")
    parser.add_argument("--json", action="store_true", help="Output JSON format")

    args = parser.parse_args()

    tester = SystemTester()

    if args.test:
        # Run single test
        test_map = {
            "smoke": tester.test_smoke,
            "simple_query": tester.test_simple_query,
            "memory": tester.test_memory,
            "streaming": tester.test_streaming,
            "tool_composition": tester.test_tool_composition,
            "planning": tester.test_planning_mode,
            "error_handling": tester.test_error_handling,
        }

        test_fn = test_map[args.test]
        try:
            await test_fn()
            tester.results[args.test] = True
            logger.info(f"✅ {args.test}: PASS")
            success = True
        except Exception as e:
            tester.results[args.test] = False
            logger.error(f"❌ {args.test}: FAIL - {e}")
            success = False

    else:
        # Run all tests
        success = await tester.run_all_tests(quick=args.quick)

    if args.json:
        print(json.dumps(tester.results, indent=2))
    else:
        tester.print_report()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
