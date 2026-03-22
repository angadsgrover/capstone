#!/usr/bin/env python3
"""
Comprehensive test suite for agent workflow.
Diagnoses tool call issues, routing, and result handling.
"""
import asyncio
import json
import logging
import sys
from typing import Any, Dict

from langchain_core.messages import HumanMessage, AIMessage
from orchestrator import init_graph
import mcp_client as mcp_module

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)

# Silence noisy loggers
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


class AgentTracer:
    """Trace agent execution flow."""

    def __init__(self):
        self.tool_calls = []
        self.errors = []
        self.routing = None

    def on_tool_start(self, tool_name: str, inputs: Dict[str, Any]):
        logger.info(f"🔧 TOOL START: {tool_name}({json.dumps(inputs)[:80]})")
        self.tool_calls.append({
            'name': tool_name,
            'inputs': inputs,
            'output': None,
            'status': 'started'
        })

    def on_tool_end(self, tool_name: str, output: Any):
        output_str = str(output)
        logger.info(f"✓ TOOL END: {tool_name} -> {len(output_str)} chars")

        # Show first 300 chars for debugging
        preview = output_str[:300]
        if "[LIMIT]" in preview or "[CACHED]" in preview:
            logger.warning(f"   ⚠️  GUARD MESSAGE: {preview}")
        else:
            logger.debug(f"   Output preview: {preview}")

        # Find matching call
        for call in reversed(self.tool_calls):
            if call['name'] == tool_name and call['status'] == 'started':
                call['output'] = output_str
                call['output_preview'] = preview
                call['status'] = 'completed'
                break

    def on_routing(self, route: str):
        logger.info(f"🧭 ROUTING: {route}")
        self.routing = route

    def on_llm_response(self, content: str, node: str):
        preview = content[:150] if content else "EMPTY"
        logger.info(f"💬 LLM ({node}): {preview}...")

    def summary(self):
        """Print execution summary."""
        print("\n" + "="*70)
        print("EXECUTION SUMMARY")
        print("="*70)
        print(f"Route: {self.routing}")
        print(f"Total tool calls: {len(self.tool_calls)}")

        # Group by tool name
        by_name = {}
        for call in self.tool_calls:
            name = call['name']
            by_name.setdefault(name, []).append(call)

        print("\nTool usage:")
        for name, calls in by_name.items():
            print(f"  {name}: {len(calls)} calls")
            for i, call in enumerate(calls):
                output_len = len(call['output']) if call['output'] else 0
                preview = call.get('output_preview', '')[:100] if call.get('output_preview') else ''
                status = "✓" if call['status'] == 'completed' else "✗"
                is_guard = "[LIMIT]" in preview or "[CACHED]" in preview
                guard_marker = " ⚠️ GUARD" if is_guard else ""
                print(f"    {status} Call {i+1}: {output_len} chars{guard_marker}")
                if preview:
                    print(f"       Preview: {preview}")

        if self.errors:
            print(f"\n⚠️  Errors: {len(self.errors)}")
            for err in self.errors:
                print(f"  - {err}")

        print("="*70)


async def test_query(query: str, graph, expected_route: str = None) -> bool:
    """Test a single query and verify routing and tool calls."""
    print(f"\n{'='*70}")
    print(f"TEST: {query}")
    print(f"{'='*70}")

    tracer = AgentTracer()

    request_id = f"test-{hash(query)}"
    mcp_module.set_request_context(request_id)

    try:
        config = {'configurable': {'thread_id': f'test-session-{hash(query)}'}}

        # Stream events to trace execution
        async for event in graph.astream_events(
            {'messages': [HumanMessage(content=query)]},
            config=config,
            version='v2',
        ):
            kind = event.get('event', '')
            meta = event.get('metadata', {})
            node = meta.get('langgraph_node', '')

            if kind == 'on_chain_start' and node:
                specialist_nodes = {'aviation_weather', 'hk_weather', 'aircraft', 'general', 'planning'}
                if node in specialist_nodes:
                    tracer.on_routing(node)

            elif kind == 'on_tool_start':
                name = event.get('name', 'unknown')
                inputs = event['data'].get('input', {})
                tracer.on_tool_start(name, inputs)

            elif kind == 'on_tool_end':
                name = event.get('name', 'unknown')
                output = event['data'].get('output', '')
                tracer.on_tool_end(name, output)

            elif kind == 'on_chat_model_end' and node and node != 'router':
                output_data = event['data'].get('output')
                if output_data and hasattr(output_data, 'content'):
                    tracer.on_llm_response(output_data.content, node)

        tracer.summary()

        # Validate results
        success = True

        if expected_route and tracer.routing != expected_route:
            print(f"\n❌ ROUTING FAILED: Expected {expected_route}, got {tracer.routing}")
            success = False
        else:
            print(f"\n✅ Routing correct: {tracer.routing}")

        # Check for excessive tool calls
        if len(tracer.tool_calls) > 20:
            print(f"⚠️  WARNING: Excessive tool calls ({len(tracer.tool_calls)})")
            success = False

        # Check for empty results
        empty_count = sum(1 for call in tracer.tool_calls if not call['output'])
        if empty_count > 0:
            print(f"⚠️  WARNING: {empty_count} tools returned empty results")
            success = False

        # Check for guard messages
        guard_count = sum(1 for call in tracer.tool_calls
                         if call['output'] and ("[LIMIT]" in call['output'] or "[CACHED]" in call['output']))
        if guard_count > 0:
            print(f"⚠️  WARNING: {guard_count} tool calls blocked by guards")
            success = False

        return success

    finally:
        mcp_module.clear_request_context(request_id)


async def main():
    """Run all test cases."""
    print("\n" + "="*70)
    print("AGENT WORKFLOW TEST SUITE")
    print("="*70)

    # Initialize graph once
    print("\nInitializing agent...")
    graph, mcp, _ = await init_graph()
    print("Agent initialized\n!")

    test_cases = [
        ("What is the METAR for VHHH?", "aviation_weather"),
        ("Get current weather in Hong Kong", "hk_weather"),
        ("Show flight patterns for India and HK", "planning"),
        ("What aircraft are flying over Hong Kong right now?", "aircraft"),
    ]

    results = []

    try:
        for query, expected_route in test_cases:
            try:
                success = await test_query(query, graph, expected_route)
                results.append((query, success))
            except Exception as e:
                logger.error(f"Test failed: {e}", exc_info=True)
                results.append((query, False))
    finally:
        # Cleanup MCP connections
        await mcp.cleanup()

    # Final summary
    print("\n" + "="*70)
    print("FINAL RESULTS")
    print("="*70)

    passed = sum(1 for _, s in results if s)
    total = len(results)

    for query, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {query}")

    print(f"\nTotal: {passed}/{total} passed")

    return 0 if passed == total else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
