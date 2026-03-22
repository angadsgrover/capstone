"""
Tool composition and self-healing framework for robust agent execution.

Features:
1. **Tool Composition**: Combine multiple tools into composite workflows
2. **Self-Healing**: Auto-retry with LLM-fixed parameters on tool failures
3. **Graceful Degradation**: Fall back to alternative approaches

Example Tool Composition:
    composite_tool = ToolComposer.create(
        name="get_full_weather_briefing",
        description="Get complete weather briefing (METAR + TAF + PIREPs)",
        steps=[
            ("lookup_airport_codes", {"location": "{location}"}),
            ("get_metar", {"icao": "{step_0.results[0].icao}"}),
            ("get_taf", {"icao": "{step_0.results[0].icao}"}),
            ("get_pireps", {"icao": "{step_0.results[0].icao}"}),
        ]
    )

Example Self-Healing:
    result = await execute_with_healing(
        tool=get_metar,
        params={"icao": "EGLL"},
        max_retries=3
    )
    # If fails: LLM analyzes error → fixes params → retries
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


# ── Tool Composition ──────────────────────────────────────────────────────────


class CompositeToolStep:
    """A single step in a composite tool workflow."""

    def __init__(
        self,
        tool_name: str,
        params: Dict[str, Any],
        retry_on_error: bool = True,
    ):
        self.tool_name = tool_name
        self.params = params
        self.retry_on_error = retry_on_error


class ToolComposer:
    """
    Create composite tools from existing tools.

    Usage:
        composer = ToolComposer(tools_dict)
        composite = composer.create(
            name="get_weather_brief",
            steps=[
                ("lookup_airport_codes", {"location": "{location}"}),
                ("get_metar", {"icao": "{step_0.results[0].icao}"}),
            ]
        )
    """

    def __init__(self, tools: Dict[str, StructuredTool]):
        """
        Args:
            tools: Dict of {tool_name: tool_instance}
        """
        self.tools = tools

    def create(
        self,
        name: str,
        description: str,
        steps: List[Tuple[str, Dict[str, Any]]],
        return_intermediate: bool = False,
    ) -> StructuredTool:
        """
        Create a composite tool from a sequence of tool calls.

        Args:
            name: Composite tool name
            description: Tool description for LLM
            steps: List of (tool_name, params) tuples
                   params can include placeholders: "{param_name}" or "{step_N.field}"
            return_intermediate: If True, return all step results; else only last

        Returns:
            StructuredTool instance
        """

        async def composite_fn(**kwargs) -> Any:
            """Execute composite tool workflow."""
            results = []

            for step_idx, (tool_name, param_template) in enumerate(steps):
                tool = self.tools.get(tool_name)
                if not tool:
                    error_msg = f"Tool not found: {tool_name}"
                    logger.error(error_msg)
                    results.append({"error": error_msg})
                    continue

                # Resolve parameters (substitute placeholders)
                resolved_params = self._resolve_params(
                    param_template, kwargs, results, step_idx
                )

                try:
                    # Execute tool
                    result = await tool.ainvoke(resolved_params)

                    results.append({"step": step_idx, "tool": tool_name, "result": result})
                    logger.debug("Step %d (%s) → %s", step_idx, tool_name, str(result)[:100])

                except Exception as e:
                    error_result = {"step": step_idx, "tool": tool_name, "error": str(e)}
                    results.append(error_result)
                    logger.error("Step %d (%s) failed: %s", step_idx, tool_name, e)

                    # Stop on error (unless retry_on_error enabled)
                    if not steps[step_idx] if isinstance(steps[step_idx], CompositeToolStep) else True:
                        break

            # Return results
            if return_intermediate:
                return results
            else:
                # Return last successful result
                for r in reversed(results):
                    if "result" in r:
                        return r["result"]
                return {"error": "All steps failed", "details": results}

        return StructuredTool.from_function(
            coroutine=composite_fn,
            name=name,
            description=description,
        )

    def _resolve_params(
        self,
        template: Dict[str, Any],
        initial_kwargs: Dict[str, Any],
        past_results: List[Dict[str, Any]],
        current_step: int,
    ) -> Dict[str, Any]:
        """
        Resolve parameter placeholders.

        Placeholders:
        - "{param_name}" → initial_kwargs["param_name"]
        - "{step_N.field}" → past_results[N]["result"]["field"]
        - "{step_N.result}" → past_results[N]["result"]
        """
        resolved = {}

        for key, value in template.items():
            if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
                placeholder = value[1:-1]  # Remove {}

                # Check if refers to previous step
                if placeholder.startswith("step_"):
                    try:
                        parts = placeholder.split(".", 1)
                        step_ref = parts[0]  # e.g., "step_0"
                        step_idx = int(step_ref.split("_")[1])

                        if step_idx >= len(past_results):
                            raise ValueError(f"Step {step_idx} not yet executed")

                        step_result = past_results[step_idx].get("result")

                        if len(parts) > 1:
                            # Navigate nested fields (e.g., "step_0.results[0].icao")
                            field_path = parts[1]
                            resolved[key] = self._navigate_field(step_result, field_path)
                        else:
                            # Use entire result
                            resolved[key] = step_result

                    except Exception as e:
                        logger.warning("Failed to resolve %s: %s", placeholder, e)
                        resolved[key] = None

                else:
                    # Refer to initial param
                    resolved[key] = initial_kwargs.get(placeholder)

            else:
                # Not a placeholder
                resolved[key] = value

        return resolved

    def _navigate_field(self, obj: Any, path: str) -> Any:
        """Navigate nested object path (e.g., "results[0].icao")."""
        import re

        current = obj
        parts = re.split(r"\.|\[|\]", path)
        parts = [p for p in parts if p]  # Remove empty strings

        for part in parts:
            if part.isdigit():
                # Array index
                current = current[int(part)]
            else:
                # Object field
                if isinstance(current, dict):
                    current = current.get(part)
                else:
                    current = getattr(current, part, None)

        return current


# ── Self-Healing Execution ────────────────────────────────────────────────────


HEALING_PROMPT = """\
A tool call failed with an error. Your job is to fix the parameters so it works.

Tool: {tool_name}
Description: {tool_description}
Parameters: {params}
Error: {error}

Analyze the error and suggest corrected parameters. Reply with a JSON object of \
the corrected parameters ONLY. Do not include any explanation.

Example:
Original params: {{"icao": "heathrow"}}
Error: "Invalid ICAO code format"
Fixed params: {{"icao": "EGLL"}}
"""


async def execute_with_healing(
    tool: StructuredTool,
    params: Dict[str, Any],
    max_retries: int = 3,
    llm_config: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Execute tool with self-healing retry logic.

    If tool fails, asks LLM to fix parameters and retries.

    Args:
        tool: Tool to execute
        params: Initial parameters
        max_retries: Maximum retry attempts (default: 3)
        llm_config: LLM configuration for healing

    Returns:
        Tool result

    Raises:
        Exception: If all retries exhausted
    """
    if llm_config is None:
        llm_config = {
            "model": "openai/gpt-4o-mini",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "",
        }

    last_error = None
    current_params = params.copy()

    for attempt in range(max_retries):
        try:
            # Execute tool
            result = await tool.ainvoke(current_params)

            logger.info("Tool %s succeeded on attempt %d", tool.name, attempt + 1)
            return result

        except Exception as e:
            last_error = e
            logger.warning(
                "Tool %s failed (attempt %d/%d): %s",
                tool.name,
                attempt + 1,
                max_retries,
                e,
            )

            # Don't retry on last attempt
            if attempt >= max_retries - 1:
                break

            # Ask LLM to fix parameters
            try:
                fixed_params = await heal_parameters(
                    tool_name=tool.name,
                    tool_description=tool.description or "",
                    params=current_params,
                    error=str(e),
                    llm_config=llm_config,
                )

                if fixed_params:
                    logger.info("Healed params: %s → %s", current_params, fixed_params)
                    current_params = fixed_params
                else:
                    break  # Healing failed

            except Exception as heal_error:
                logger.warning("Parameter healing failed: %s", heal_error)
                break

    # All retries exhausted
    raise Exception(
        f"Tool {tool.name} failed after {max_retries} attempts. Last error: {last_error}"
    )


async def heal_parameters(
    tool_name: str,
    tool_description: str,
    params: Dict[str, Any],
    error: str,
    llm_config: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Use LLM to heal/fix tool parameters based on error.

    Args:
        tool_name: Tool name
        tool_description: Tool description
        params: Original parameters
        error: Error message
        llm_config: LLM configuration

    Returns:
        Fixed parameters, or None if healing failed
    """
    import json

    llm = ChatOpenAI(
        model=llm_config.get("model", "openai/gpt-4o-mini"),
        base_url=llm_config.get("base_url", "https://openrouter.ai/api/v1"),
        api_key=llm_config.get("api_key", ""),
        temperature=0,
        max_tokens=500,
    )

    prompt = HEALING_PROMPT.format(
        tool_name=tool_name,
        tool_description=tool_description,
        params=json.dumps(params, indent=2),
        error=error,
    )

    messages = [SystemMessage(content=prompt)]

    try:
        response = llm.invoke(messages)
        content = response.content.strip()

        # Extract JSON (handle markdown code blocks)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        # Parse fixed params
        fixed_params = json.loads(content)
        return fixed_params

    except Exception as e:
        logger.warning("Failed to heal parameters: %s", e)
        return None


# ── Retry with Exponential Backoff ───────────────────────────────────────────


async def execute_with_retry(
    tool: StructuredTool,
    params: Dict[str, Any],
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    heal: bool = True,
    llm_config: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Execute tool with exponential backoff retry.

    Combines:
    - Exponential backoff (delays between retries)
    - Self-healing (LLM fixes params on error)

    Args:
        tool: Tool to execute
        params: Parameters
        max_retries: Max retry attempts
        backoff_factor: Delay multiplier (default: 2.0 → 1s, 2s, 4s, ...)
        heal: Enable self-healing (default: True)
        llm_config: LLM config for healing

    Returns:
        Tool result
    """
    if heal:
        return await execute_with_healing(tool, params, max_retries, llm_config)

    # Simple retry without healing
    last_error = None
    delay = 1.0

    for attempt in range(max_retries):
        try:
            return await tool.ainvoke(params)

        except Exception as e:
            last_error = e
            logger.warning("Tool %s failed (attempt %d/%d): %s", tool.name, attempt + 1, max_retries, e)

            if attempt < max_retries - 1:
                logger.info("Retrying in %.1fs...", delay)
                await asyncio.sleep(delay)
                delay *= backoff_factor

    raise Exception(f"Tool {tool.name} failed after {max_retries} attempts: {last_error}")


# ── Self-Healing Tool Wrapper ────────────────────────────────────────────────


def wrap_tool_with_healing(
    tool: StructuredTool,
    max_retries: int = 2,
    llm_config: Optional[Dict[str, Any]] = None,
) -> StructuredTool:
    """
    Wrap a tool with self-healing retry logic.

    When the wrapped tool fails, it will:
    1. Ask LLM to analyze the error
    2. Fix the parameters
    3. Retry with corrected parameters

    Args:
        tool: Original tool to wrap
        max_retries: Maximum retry attempts (default: 2)
        llm_config: LLM configuration for healing

    Returns:
        StructuredTool with self-healing capability
    """
    async def healing_wrapper(**kwargs):
        """Execute with self-healing retry."""
        try:
            # First attempt
            return await tool.ainvoke(kwargs)

        except Exception as first_error:
            logger.warning("Tool %s failed: %s. Attempting self-healing...", tool.name, first_error)

            current_params = kwargs.copy()
            last_error = first_error

            for attempt in range(max_retries):
                try:
                    # Ask LLM to fix parameters
                    fixed_params = await heal_parameters(
                        tool_name=tool.name,
                        tool_description=tool.description or "",
                        params=current_params,
                        error=str(last_error),
                        llm_config=llm_config or {},
                    )

                    if not fixed_params:
                        logger.warning("Self-healing returned no fixes")
                        break

                    logger.info("Healed params for %s: %s → %s", tool.name, current_params, fixed_params)
                    current_params = fixed_params

                    # Retry with fixed params
                    return await tool.ainvoke(current_params)

                except Exception as retry_error:
                    logger.warning("Retry %d failed: %s", attempt + 1, retry_error)
                    last_error = retry_error

            # All retries failed, return error message
            return f"Error: {last_error} (after {max_retries} self-healing attempts)"

    # Create wrapped tool
    return StructuredTool.from_function(
        coroutine=healing_wrapper,
        name=tool.name,
        description=tool.description or "",
        args_schema=tool.args_schema,
    )


def wrap_tools_with_healing(
    tools: List[StructuredTool],
    max_retries: int = 2,
    llm_config: Optional[Dict[str, Any]] = None,
) -> List[StructuredTool]:
    """
    Wrap multiple tools with self-healing capability.

    Args:
        tools: List of tools to wrap
        max_retries: Max retry attempts per tool
        llm_config: LLM configuration

    Returns:
        List of wrapped tools
    """
    return [wrap_tool_with_healing(t, max_retries, llm_config) for t in tools]
