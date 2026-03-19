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
from typing import Any, Dict, List, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

logger = logging.getLogger(__name__)

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
You are an expert planner for aviation queries. Break down the user's complex query \
into a step-by-step plan. Each step should be a single, atomic task.

Guidelines:
- Keep steps simple and actionable
- Number steps (1., 2., 3., ...)
- Each step should be executable by a single tool call or specialist
- Don't include synthesis step (that's automatic)

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

Now create a plan for the user's query. Reply with ONLY the numbered list.
"""


def create_plan(state: PlanExecuteState, config: RunnableConfig) -> Dict[str, Any]:
    """Generate step-by-step plan from user query."""
    llm = ChatOpenAI(
        model=config.get("model", "openai/gpt-4o-mini"),
        base_url=config.get("base_url", "https://openrouter.ai/api/v1"),
        api_key=config.get("api_key", ""),
        temperature=0,
        max_tokens=500,
    )

    messages = [
        SystemMessage(content=PLANNER_PROMPT),
        HumanMessage(content=state["input"]),
    ]

    response = llm.invoke(messages)
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

Execute this step using available tools. Be concise and factual.
"""


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
    result = await executor_agent.ainvoke(
        {"messages": [SystemMessage(content=system_prompt), HumanMessage(content=current_step)]},
        config=config,
    )

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
"""


def synthesize_response(state: PlanExecuteState, config: RunnableConfig) -> Dict[str, Any]:
    """Synthesize final response from all step results."""
    llm = ChatOpenAI(
        model=config.get("model", "openai/gpt-4o-mini"),
        base_url=config.get("base_url", "https://openrouter.ai/api/v1"),
        api_key=config.get("api_key", ""),
        temperature=0,
        max_tokens=2048,
    )

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

    response = llm.invoke(messages)
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

Reply with ONLY "planning" or "single-step".
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
    llm = ChatOpenAI(
        model=llm_config.get("model", "openai/gpt-4o-mini"),
        base_url=llm_config.get("base_url", "https://openrouter.ai/api/v1"),
        api_key=llm_config.get("api_key", ""),
        temperature=0,
        max_tokens=10,
    )

    messages = [
        SystemMessage(content=PLANNING_DETECTOR_PROMPT),
        HumanMessage(content=query),
    ]

    response = llm.invoke(messages)
    decision = response.content.strip().lower()

    return "planning" in decision
