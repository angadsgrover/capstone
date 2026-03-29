"""
Multi-turn planning agent using LangGraph Plan-and-Execute pattern.

Breaks complex queries into step-by-step plans, executes each step sequentially,
and synthesizes a final response. Useful for queries requiring multiple sub-tasks.

Architecture:
  User Query → Planner → Step 1 → Step 2 → ... → Step N → Synthesize → Response

Example:
  "Compare weather at EGLL and KJFK, then recommend best flight time"

  Plan:
  1. Get METAR/TAF for EGLL
  2. Get METAR/TAF for KJFK
  3. Analyze flight categories
  4. Recommend optimal departure time based on weather

Features:
- Auto-detects if query needs planning (vs single-step execution)
- Tracks past steps for context
- Synthesizes final answer from all step results
- Visualizes plan + execution in UI

Configuration:
  ENABLE_PLANNING=true  # Enable/disable planning mode (default: false for now)
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse
from typing import Any, Dict, List, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

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

logger = logging.getLogger(__name__)


def _infer_provider(base_url: str) -> str:
    host = (urlparse(base_url or "").netloc or "").lower()
    if "openrouter" in host:
        return "openrouter"
    if "openai" in host:
        return "openai"
    if "anthropic" in host:
        return "anthropic"
    return host.split(":", 1)[0] if host else "custom"


def _extract_usage_metadata(message: Any) -> Dict[str, Any]:
    usage = getattr(message, "usage_metadata", None)
    if isinstance(usage, dict) and usage:
        normalized: Dict[str, Any] = {
            "input_tokens": int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0),
            "output_tokens": int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0),
        }
        total = usage.get("total_tokens")
        if total is not None:
            normalized["total_tokens"] = int(total)
        elif normalized["input_tokens"] or normalized["output_tokens"]:
            normalized["total_tokens"] = normalized["input_tokens"] + normalized["output_tokens"]
        return normalized

    response_metadata = getattr(message, "response_metadata", None)
    if isinstance(response_metadata, dict):
        token_usage = response_metadata.get("token_usage") or response_metadata.get("usage") or {}
        if isinstance(token_usage, dict):
            input_tokens = int(token_usage.get("prompt_tokens", token_usage.get("input_tokens", 0)) or 0)
            output_tokens = int(token_usage.get("completion_tokens", token_usage.get("output_tokens", 0)) or 0)
            total_tokens = token_usage.get("total_tokens")
            normalized = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
            if total_tokens is not None:
                normalized["total_tokens"] = int(total_tokens)
            elif input_tokens or output_tokens:
                normalized["total_tokens"] = input_tokens + output_tokens
            return normalized

    return {}


def _to_langsmith_messages(messages: List[Any]) -> List[Dict[str, Any]]:
    role_map = {
        "human": "user",
        "ai": "assistant",
        "system": "system",
        "tool": "tool",
    }
    formatted: List[Dict[str, Any]] = []
    for msg in messages:
        msg_type = getattr(msg, "type", "")
        role = role_map.get(msg_type, "user")
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            blocks = [{"type": "text", "text": content}]
        elif isinstance(content, list):
            blocks: List[Dict[str, Any]] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") in {"text", "reasoning"} and "text" in block:
                    blocks.append({"type": block["type"], "text": str(block["text"])})
                else:
                    blocks.append({"type": "text", "text": str(block)})
        else:
            blocks = [{"type": "text", "text": str(content)}]
        formatted.append({"role": role, "content": blocks})
    return formatted


def _process_llm_inputs(inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {"messages": _to_langsmith_messages(inputs.get("messages", []))}


def _process_llm_output(output: Any) -> Dict[str, Any]:
    if isinstance(output, AIMessage):
        payload: Dict[str, Any] = {"messages": _to_langsmith_messages([output])}
        usage_metadata = _extract_usage_metadata(output)
        if usage_metadata:
            payload["usage_metadata"] = usage_metadata
        return payload
    return {"messages": [{"role": "assistant", "content": [{"type": "text", "text": str(output)}]}]}


def _annotate_llm_run(model: str, base_url: str, thread_id: str, response: Any) -> None:
    run_tree = get_current_run_tree()
    if not run_tree:
        return

    try:
        metadata = dict(getattr(run_tree, "metadata", {}) or {})
        metadata["ls_provider"] = _infer_provider(base_url)
        metadata["ls_model_name"] = model
        if thread_id:
            metadata["session_id"] = thread_id
            metadata["thread_id"] = thread_id
            metadata["conversation_id"] = thread_id
        run_tree.metadata = metadata
    except Exception:
        pass

    usage_metadata = _extract_usage_metadata(response)
    if usage_metadata:
        try:
            run_tree.usage_metadata = usage_metadata
        except Exception:
            pass


def _invoke_llm(
    messages: List[Any],
    model: str,
    base_url: str,
    api_key: str,
    temperature: float,
    max_tokens: int,
    thread_id: str = "",
) -> AIMessage:
    llm = ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    response = llm.invoke(messages)
    _annotate_llm_run(model=model, base_url=base_url, thread_id=thread_id, response=response)
    return response


@traceable(
    name="planning.plan_llm",
    run_type="llm",
    process_inputs=_process_llm_inputs,
    process_outputs=_process_llm_output,
)
def _invoke_planner_llm(
    messages: List[Any],
    model: str,
    base_url: str,
    api_key: str,
    thread_id: str = "",
) -> AIMessage:
    return _invoke_llm(
        messages=messages,
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=0,
        max_tokens=500,
        thread_id=thread_id,
    )


@traceable(
    name="planning.synthesize_llm",
    run_type="llm",
    process_inputs=_process_llm_inputs,
    process_outputs=_process_llm_output,
)
def _invoke_synthesizer_llm(
    messages: List[Any],
    model: str,
    base_url: str,
    api_key: str,
    thread_id: str = "",
) -> AIMessage:
    return _invoke_llm(
        messages=messages,
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=0,
        max_tokens=2048,
        thread_id=thread_id,
    )


@traceable(
    name="planning.detector_llm",
    run_type="llm",
    process_inputs=_process_llm_inputs,
    process_outputs=_process_llm_output,
)
def _invoke_detector_llm(
    messages: List[Any],
    model: str,
    base_url: str,
    api_key: str,
    thread_id: str = "",
) -> AIMessage:
    return _invoke_llm(
        messages=messages,
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=0,
        max_tokens=10,
        thread_id=thread_id,
    )

# ── State ─────────────────────────────────────────────────────────────────────

class PlanExecuteState(TypedDict):
    """State for Plan-and-Execute agent."""
    input: str                          # Original user query
    plan: List[str]                     # List of steps to execute
    original_plan: List[str]            # Immutable copy of generated plan
    past_steps: List[tuple[str, str]]   # (step, result) history
    execution_trace: List[Dict[str, str]]  # Structured trace for UI/API
    response: str                       # Final synthesized response
    current_step_idx: int               # Which step we're on


# ── Planning ──────────────────────────────────────────────────────────────────

PLANNER_PROMPT = """\
You are an expert planning module for aviation and weather queries.

Task:
Break down the user's complex query into a step-by-step executable plan.
Each step must be a single atomic task.

Guidelines:
- Keep steps simple and actionable
- Number steps (1., 2., 3., ...)
- Each step should be executable by a single tool call or specialist
- Don't include synthesis step (that's automatic)
- Use explicit domain wording (e.g., METAR, TAF, arrivals, warnings) when possible
- Do not include branching logic, alternatives, or explanations
- Keep the plan to the minimum steps needed to answer the query fully

Examples:

Query: "Compare weather at EGLL and KJFK"
Plan:
1. Get METAR for EGLL
2. Get TAF for EGLL
3. Get METAR for KJFK
4. Get TAF for KJFK

Query: "Find the busiest airport in my watchlist and check its current delays"
Plan:
1. List airports in watchlist
2. Get departure counts for each airport
3. Identify busiest airport
4. Check delay status for busiest airport

Now create a plan for the user's query.

Output format:
- Reply with ONLY the numbered list.
- No prose before or after the list.
"""


@traceable(name="planning.create_plan", run_type="chain")
def create_plan(state: PlanExecuteState, config: RunnableConfig) -> Dict[str, Any]:
    """Generate step-by-step plan from user query."""
    model = config.get("model", "openai/gpt-4o-mini")
    base_url = config.get("base_url", "https://openrouter.ai/api/v1")
    api_key = config.get("api_key", "")
    thread_id = config.get("session_id", "")

    messages = [
        SystemMessage(content=PLANNER_PROMPT),
        HumanMessage(content=state["input"]),
    ]

    response = _invoke_planner_llm(
        messages=messages,
        model=model,
        base_url=base_url,
        api_key=api_key,
        thread_id=thread_id,
    )
    plan_text = response.content.strip()

    # Parse numbered list
    plan_steps = []
    for line in plan_text.split("\n"):
        line = line.strip()
        if line and (line[0].isdigit() or line.startswith("-")):
            # Remove numbering/bullets
            step = line.lstrip("0123456789.-) ").strip()
            if step:
                plan_steps.append(step)

    logger.info("Created plan with %d steps: %s", len(plan_steps), plan_steps)

    return {
        "plan": plan_steps,
        "original_plan": list(plan_steps),
        "past_steps": [],
        "execution_trace": [],
        "current_step_idx": 0,
    }


# ── Execution ─────────────────────────────────────────────────────────────────

EXECUTOR_PROMPT = """\
You are an expert aviation assistant executing a specific step in a multi-step plan.

Context from past steps:
{past_steps_summary}

Current step to execute:
{current_step}

CRITICAL RULES:
1. Execute this ONE step using available tools.
2. Do not re-call tools if you already have data from past steps.
3. Maximum 4 tool calls for this step. After 4 calls, summarize what you have.
4. If a tool returns an error or empty data, note it and move on.
5. Be concise and factual in your response.
6. Tool selection must match intent:
    - METAR/TAF/ICAO airport weather -> aviation tools (`get_metar`, `get_taf`)
    - Hong Kong civic weather -> HK tools (`get_current_weather`, warnings/forecast)
    - Never use `get_current_weather` to answer a METAR/TAF request.
7. Do not fabricate values, times, or identifiers.
8. Return only the step result, not a final multi-step conclusion.
"""

@traceable(name="planning.execute_step", run_type="chain")
async def execute_step(
    state: PlanExecuteState,
    config: RunnableConfig,
    executor_agent,  # The specialist agent (e.g., aviation_weather)
) -> Dict[str, Any]:
    """Execute current step using specialist agent."""
    if not state["plan"]:
        return {"response": "No plan to execute"}

    current_step = state["plan"][0]
    past_steps = state.get("past_steps", [])

    # Build context from past steps
    past_summary = "\n".join(
        f"Step {i+1}: {step}\nResult: {result[:200]}..."
        for i, (step, result) in enumerate(past_steps)
    )

    # Create prompt for executor
    system_prompt = EXECUTOR_PROMPT.format(
        past_steps_summary=past_summary or "None (this is the first step)",
        current_step=current_step,
    )

    # Invoke executor agent
    executor_limit = int(config.get("executor_recursion_limit", 12))
    exec_config = {
        "callbacks": config.get("callbacks"),
        "recursion_limit": executor_limit,
    }

    try:
        result = await executor_agent.ainvoke(
            {"messages": [SystemMessage(content=system_prompt), HumanMessage(content=current_step)]},
            config=exec_config,
        )
    except Exception as e:
        if "GRAPH_RECURSION_LIMIT" in str(e) or "Recursion limit" in str(e):
            logger.warning("Step recursion limit reached for '%s': %s", current_step, e)
            step_result = (
                "Step execution stopped early due to repeated tool-call recursion. "
                "Proceeding with available context."
            )
            return {
                "past_steps": [*past_steps, (current_step, step_result)],
                "execution_trace": [
                    *state.get("execution_trace", []),
                    {
                        "step": str(state.get("current_step_idx", 0) + 1),
                        "task": current_step,
                        "result": step_result,
                    },
                ],
                "plan": state["plan"][1:],
                "current_step_idx": state.get("current_step_idx", 0) + 1,
            }
        raise

    # Extract response
    ai_msgs = [m for m in result["messages"] if isinstance(m, AIMessage)]
    step_result = ai_msgs[-1].content if ai_msgs else "No result"

    logger.info("Executed step %d: %s → %s", len(past_steps) + 1, current_step, step_result[:100])

    return {
        "past_steps": [*past_steps, (current_step, step_result)],
        "execution_trace": [
            *state.get("execution_trace", []),
            {
                "step": str(state.get("current_step_idx", 0) + 1),
                "task": current_step,
                "result": step_result,
            },
        ],
        "plan": state["plan"][1:],  # Remove completed step
        "current_step_idx": state.get("current_step_idx", 0) + 1,
    }


# ── Synthesis ─────────────────────────────────────────────────────────────────

SYNTHESIZER_PROMPT = """\
You are an expert aviation assistant. Synthesize a final response based on the \
results of all executed steps.

Original query: {original_query}

Executed steps and results:
{all_steps}

Provide a comprehensive, well-organized answer addressing the user's original query. \
Include relevant details from each step.

Hard rules:
- Do not invent facts not present in step results.
- If step results conflict or are incomplete, explicitly note uncertainty.
- Prefer concise operational guidance over verbose narrative.

Output structure:
- 1-2 sentence summary
- Key findings (bulleted)
- Recommended action or interpretation
- Data gaps/uncertainty (if any)
"""


@traceable(name="planning.synthesize_response", run_type="chain")
def synthesize_response(state: PlanExecuteState, config: RunnableConfig) -> Dict[str, Any]:
    """Synthesize final response from all step results."""
    model = config.get("model", "openai/gpt-4o-mini")
    base_url = config.get("base_url", "https://openrouter.ai/api/v1")
    api_key = config.get("api_key", "")
    thread_id = config.get("session_id", "")

    # Format all steps
    steps_summary = "\n\n".join(
        f"**Step {i+1}**: {step}\n**Result**: {result}"
        for i, (step, result) in enumerate(state["past_steps"])
    )

    messages = [
        SystemMessage(
            content=SYNTHESIZER_PROMPT.format(
                original_query=state["input"],
                all_steps=steps_summary,
            )
        ),
    ]

    response = _invoke_synthesizer_llm(
        messages=messages,
        model=model,
        base_url=base_url,
        api_key=api_key,
        thread_id=thread_id,
    )
    final_response = response.content.strip()

    logger.info("Synthesized final response: %s", final_response[:100])

    return {"response": final_response}


# ── Graph builder ─────────────────────────────────────────────────────────────

def should_continue(state: PlanExecuteState) -> Literal["execute", "synthesize"]:
    """Decide whether to execute next step or synthesize final response."""
    if state["plan"]:
        return "execute"
    return "synthesize"


def build_plan_execute_graph(executor_agent, llm_config: Dict[str, Any]):
    """
    Build Plan-and-Execute graph.

    Args:
        executor_agent: The specialist agent to use for step execution
        llm_config: LLM configuration (model, base_url, api_key)

    Returns:
        Compiled LangGraph
    """
    graph = StateGraph(PlanExecuteState)

    # Wrap nodes to pass config
    def plan_node(state: PlanExecuteState):
        return create_plan(state, llm_config)

    async def execute_node(state: PlanExecuteState):
        return await execute_step(state, llm_config, executor_agent)

    def synthesize_node(state: PlanExecuteState):
        return synthesize_response(state, llm_config)

    # Add nodes
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("synthesize", synthesize_node)

    # Add edges
    graph.add_edge(START, "plan")
    graph.add_conditional_edges(
        "plan",
        should_continue,
        {"execute": "execute", "synthesize": "synthesize"},
    )
    graph.add_conditional_edges(
        "execute",
        should_continue,
        {"execute": "execute", "synthesize": "synthesize"},
    )
    graph.add_edge("synthesize", END)

    return graph.compile()


# ── Helper: Should we use planning? ──────────────────────────────────────────

PLANNING_DETECTOR_PROMPT = """\
Determine if this query requires multi-step planning or can be answered in one step.

Use planning if:
- Query asks to "compare" multiple things
- Query has multiple sub-questions
- Query requires sequential steps (first do X, then do Y)

Use single-step if:
- Query is simple and focused
- Query asks for one specific thing
- Query can be answered with one tool call

Decision policy:
- If uncertain, choose planning.

Reply with ONLY one token: planning OR single-step.
"""


def should_use_planning(query: str, llm_config: Dict[str, Any]) -> bool:
    """
    Determine if query needs planning or can be single-step.

    Args:
        query: User query
        llm_config: LLM configuration

    Returns:
        True if planning needed, False for single-step
    """
    model = llm_config.get("model", "openai/gpt-4o-mini")
    base_url = llm_config.get("base_url", "https://openrouter.ai/api/v1")
    api_key = llm_config.get("api_key", "")
    thread_id = llm_config.get("session_id", "")

    messages = [
        SystemMessage(content=PLANNING_DETECTOR_PROMPT),
        HumanMessage(content=query),
    ]

    response = _invoke_detector_llm(
        messages=messages,
        model=model,
        base_url=base_url,
        api_key=api_key,
        thread_id=thread_id,
    )
    decision = response.content.strip().lower()

    return "planning" in decision
