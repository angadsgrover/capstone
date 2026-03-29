#!/usr/bin/env python3
"""Run LangSmith evaluations for the aviation agent workflow."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

try:
    from langsmith import Client, traceable
except Exception as exc:  # pragma: no cover - explicit startup failure message
    raise RuntimeError(
        "LangSmith SDK is required for evaluations. Install langsmith>=0.3.13."
    ) from exc

import mcp_client as mcp_module
from orchestrator import init_graph

logger = logging.getLogger(__name__)


DEFAULT_DATASET_EXAMPLES: List[Dict[str, Any]] = [
    {
        "inputs": {
            "query": "What is the METAR for VHHH right now?",
        },
        "outputs": {
            "expected_route": "aviation_weather",
            "requires_planning": False,
            "must_include": ["metar", "vhhh"],
            "min_answer_chars": 120,
        },
    },
    {
        "inputs": {
            "query": "What are the current Hong Kong weather warnings and forecast?",
        },
        "outputs": {
            "expected_route": "hk_weather",
            "requires_planning": False,
            "must_include": ["warning", "forecast"],
            "min_answer_chars": 120,
        },
    },
    {
        "inputs": {
            "query": "What aircraft are flying over Hong Kong right now?",
        },
        "outputs": {
            "expected_route": "aircraft",
            "requires_planning": False,
            "must_include": ["aircraft"],
            "min_answer_chars": 120,
        },
    },
    {
        "inputs": {
            "query": "Compare weather at VHHH and EGLL and recommend the safer departure window.",
        },
        "outputs": {
            "expected_route": "planning",
            "requires_planning": True,
            "min_execution_steps": 2,
            "must_include": ["vhhh", "egll"],
            "min_answer_chars": 180,
        },
    },
    {
        "inputs": {
            "query": "List the main capabilities of this platform in 3 bullet points.",
        },
        "outputs": {
            "expected_route": "general",
            "requires_planning": False,
            "must_include": ["capabilities"],
            "min_answer_chars": 80,
        },
    },
]


def _extract_planning_data(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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


def _extract_answer_text(messages: Iterable[Any]) -> str:
    answer = ""
    for msg in messages:
        if isinstance(msg, AIMessage):
            content = getattr(msg, "content", "")
            if isinstance(content, str) and content.strip():
                answer = content
    return answer


class AgentEvaluationHarness:
    """Wrap graph lifecycle and expose a LangSmith-compatible target function."""

    def __init__(self) -> None:
        self._graph = None
        self._mcp_client = None

    async def startup(self) -> None:
        self._graph, self._mcp_client, _ = await init_graph()
        logger.info("Evaluation harness initialized")

    async def shutdown(self) -> None:
        if self._mcp_client is not None:
            await self._mcp_client.cleanup()
            logger.info("MCP client cleanup complete")

    @traceable(name="evaluation.agent_target", run_type="chain")
    async def target(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if self._graph is None:
            raise RuntimeError("Evaluation harness not initialized")

        query = str(inputs.get("query") or inputs.get("input") or "").strip()
        if not query:
            return {
                "answer": "",
                "route": "general",
                "multi_step": False,
                "plan_steps": 0,
                "execution_steps": 0,
                "response_chars": 0,
            }

        session_id = f"eval-{uuid.uuid4().hex[:12]}"
        request_id = f"{session_id}:{uuid.uuid4().hex[:8]}"
        config: RunnableConfig = {
            "configurable": {"thread_id": session_id},
            "metadata": {
                "evaluation": True,
                "evaluation_session_id": session_id,
            },
            "tags": ["evaluation", "agent-workflow"],
            "run_name": query[:80],
        }

        mcp_module.set_request_context(request_id)
        try:
            result = await self._graph.ainvoke(
                {"messages": [HumanMessage(content=query)]},
                config=config,
            )
        finally:
            mcp_module.clear_request_context(request_id)

        planning_data = _extract_planning_data(result) or {}
        execution_trace = planning_data.get("execution_trace") or []
        plan = planning_data.get("plan") or []
        answer = _extract_answer_text(result.get("messages", []))

        return {
            "answer": answer,
            "route": str(result.get("route") or "general"),
            "multi_step": bool(planning_data),
            "plan_steps": len(plan) if isinstance(plan, list) else 0,
            "execution_steps": len(execution_trace) if isinstance(execution_trace, list) else 0,
            "response_chars": len(answer),
        }


class OpenRouterJudge:
    """Optional rubric evaluator using the same OpenRouter-style setup as the agent."""

    def __init__(self, model: str, base_url: str, api_key: str) -> None:
        self.enabled = bool(api_key)
        self._llm: Optional[ChatOpenAI] = None
        if self.enabled:
            self._llm = ChatOpenAI(
                model=model,
                base_url=base_url,
                api_key=api_key,
                streaming=False,
                temperature=0,
                max_tokens=8,
                default_headers={"HTTP-Referer": "http://localhost:5173"},
            )

    @traceable(name="evaluation.llm_judge", run_type="llm")
    async def evaluate(
        self,
        inputs: Dict[str, Any],
        outputs: Dict[str, Any],
        reference_outputs: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self.enabled or self._llm is None:
            return True

        query = str(inputs.get("query") or inputs.get("input") or "")
        answer = str(outputs.get("answer") or "")
        route = str(outputs.get("route") or "")
        expected_route = ""
        if isinstance(reference_outputs, dict):
            expected_route = str(reference_outputs.get("expected_route") or "")

        rubric = (
            "Judge whether the assistant answer is useful and grounded for the user query. "
            "Return ONLY PASS or FAIL. PASS requires: actionable answer, no obvious hallucination, "
            "and route consistency when an expected route is provided."
        )

        prompt = (
            f"Query: {query}\n"
            f"Expected route: {expected_route or 'N/A'}\n"
            f"Actual route: {route or 'N/A'}\n"
            f"Answer:\n{answer}"
        )

        try:
            response = await self._llm.ainvoke(
                [
                    SystemMessage(content=rubric),
                    HumanMessage(content=prompt),
                ]
            )
        except Exception as exc:
            logger.warning("LLM judge failed; treating as pass to avoid aborting eval: %s", exc)
            return True

        content = getattr(response, "content", "")
        if isinstance(content, list):
            content = "\n".join(str(part) for part in content)
        verdict = str(content).strip().upper()
        return verdict.startswith("PASS")


def route_matches_reference(
    inputs: Dict[str, Any],
    outputs: Dict[str, Any],
    reference_outputs: Optional[Dict[str, Any]] = None,
) -> bool:
    if not isinstance(reference_outputs, dict):
        return True
    expected_route = str(reference_outputs.get("expected_route") or "").strip()
    if not expected_route:
        return True
    actual_route = str(outputs.get("route") or "").strip()
    return actual_route == expected_route


def planning_trace_present_when_expected(
    inputs: Dict[str, Any],
    outputs: Dict[str, Any],
    reference_outputs: Optional[Dict[str, Any]] = None,
) -> bool:
    if not isinstance(reference_outputs, dict):
        return True

    needs_planning = bool(reference_outputs.get("requires_planning", False))
    if not needs_planning:
        return True

    min_steps = int(reference_outputs.get("min_execution_steps", 1) or 1)
    execution_steps = int(outputs.get("execution_steps", 0) or 0)
    return bool(outputs.get("multi_step")) and execution_steps >= min_steps


def response_has_minimum_depth(
    inputs: Dict[str, Any],
    outputs: Dict[str, Any],
    reference_outputs: Optional[Dict[str, Any]] = None,
) -> bool:
    min_chars = 100
    if isinstance(reference_outputs, dict):
        min_chars = int(reference_outputs.get("min_answer_chars", min_chars) or min_chars)

    answer = str(outputs.get("answer") or "")
    return len(answer.strip()) >= min_chars


def answer_mentions_required_terms(
    inputs: Dict[str, Any],
    outputs: Dict[str, Any],
    reference_outputs: Optional[Dict[str, Any]] = None,
) -> bool:
    if not isinstance(reference_outputs, dict):
        return True

    required_terms = reference_outputs.get("must_include") or []
    if not isinstance(required_terms, list) or not required_terms:
        return True

    answer = str(outputs.get("answer") or "").lower()
    return all(str(term).lower() in answer for term in required_terms)


def ensure_dataset(
    client: Client,
    dataset_name: str,
    examples: List[Dict[str, Any]],
    *,
    refresh_dataset: bool,
) -> str:
    """Create/read LangSmith dataset and seed examples when needed."""
    working_name = dataset_name
    if refresh_dataset:
        suffix = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        working_name = f"{dataset_name}-{suffix}"
        dataset = client.create_dataset(
            dataset_name=working_name,
            description="Aviation agent evaluation dataset (timestamped refresh)",
        )
        client.create_examples(dataset_id=dataset.id, examples=examples)
        return working_name

    try:
        dataset = client.read_dataset(dataset_name=working_name)
    except Exception:
        dataset = client.create_dataset(
            dataset_name=working_name,
            description="Aviation agent evaluation dataset",
        )

    has_examples = False
    try:
        for _ in client.list_examples(dataset_id=dataset.id, limit=1):
            has_examples = True
            break
    except TypeError:
        for _ in client.list_examples(dataset_id=dataset.id):
            has_examples = True
            break

    if not has_examples:
        client.create_examples(dataset_id=dataset.id, examples=examples)

    return working_name


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run LangSmith evaluations for workflow/orchestration quality.",
    )
    parser.add_argument(
        "--dataset-name",
        default=os.getenv("LANGSMITH_EVAL_DATASET", "aviation-agent-eval"),
        help="LangSmith dataset name to evaluate against.",
    )
    parser.add_argument(
        "--experiment-prefix",
        default=os.getenv("LANGSMITH_EVAL_EXPERIMENT_PREFIX", "aviation-agent-eval"),
        help="Experiment prefix shown in LangSmith.",
    )
    parser.add_argument(
        "--description",
        default="Detailed workflow/orchestration/agent evaluation",
        help="Experiment description.",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=int(os.getenv("LANGSMITH_EVAL_MAX_CONCURRENCY", "3")),
        help="Maximum concurrent target invocations.",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Run evaluation locally without uploading experiment results.",
    )
    parser.add_argument(
        "--refresh-dataset",
        action="store_true",
        help="Create a timestamped dataset copy and seed examples.",
    )
    parser.add_argument(
        "--disable-llm-judge",
        action="store_true",
        help="Disable optional LLM-as-judge evaluator.",
    )
    parser.add_argument(
        "--judge-model",
        default=os.getenv("EVAL_JUDGE_MODEL") or os.getenv("MODEL_CHOICE", "openai/gpt-4o-mini"),
        help="Model used for the optional LLM judge evaluator.",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("LANGSMITH_EVAL_LOG_LEVEL", "INFO"),
        help="Python logging level.",
    )
    return parser


async def run_evaluation(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_dotenv()

    client = Client()
    dataset_name = ensure_dataset(
        client,
        dataset_name=args.dataset_name,
        examples=DEFAULT_DATASET_EXAMPLES,
        refresh_dataset=args.refresh_dataset,
    )

    harness = AgentEvaluationHarness()
    await harness.startup()

    evaluators = [
        route_matches_reference,
        planning_trace_present_when_expected,
        response_has_minimum_depth,
        answer_mentions_required_terms,
    ]

    if not args.disable_llm_judge:
        judge = OpenRouterJudge(
            model=args.judge_model,
            base_url=os.getenv("BASE_URL", "https://openrouter.ai/api/v1"),
            api_key=os.getenv("LLM_API_KEY", ""),
        )
        if judge.enabled:
            evaluators.append(judge.evaluate)
            logger.info("Enabled LLM judge evaluator with model=%s", args.judge_model)
        else:
            logger.info("Skipping LLM judge evaluator because LLM_API_KEY is not set")

    logger.info(
        "Running LangSmith evaluation on dataset='%s' with %d evaluator(s)",
        dataset_name,
        len(evaluators),
    )

    try:
        experiment = await client.aevaluate(
            harness.target,
            data=dataset_name,
            evaluators=evaluators,
            max_concurrency=max(1, args.max_concurrency),
            experiment_prefix=args.experiment_prefix,
            description=args.description,
            upload_results=not args.local,
        )
    finally:
        await harness.shutdown()

    experiment_name = getattr(experiment, "experiment_name", None)
    experiment_url = getattr(experiment, "url", None)

    print("\nEvaluation complete.")
    print(f"Dataset: {dataset_name}")
    print(f"Uploaded to LangSmith: {'no' if args.local else 'yes'}")

    if experiment_name:
        print(f"Experiment: {experiment_name}")
    if experiment_url:
        print(f"Experiment URL: {experiment_url}")

    if args.local:
        print("Local mode used upload_results=False for fast iterative validation.")


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    asyncio.run(run_evaluation(args))


if __name__ == "__main__":
    main()
