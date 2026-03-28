"""
Result formatter for converting agent outputs to structured responses.

Provides tools to parse LLM outputs and extract metadata, confidence,
and reasoning traces.
"""
import re
import json
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from response_schema import (
    StructuredResponse,
    ResponseSection,
    ConfidenceAssessment,
    DataSource,
    ReasoningStep,
    create_simple_response,
)


class ResultFormatter:
    """Formats agent responses with structure and metadata."""

    def __init__(self, specialist: str):
        self.specialist = specialist

    def parse_llm_output(
        self,
        raw_output: str,
        tools_used: List[Dict[str, Any]],
        total_duration_ms: Optional[int] = None,
    ) -> StructuredResponse:
        """
        Parse LLM output into structured response.

        Attempts to extract:
        - Summary (first paragraph or first sentence)
        - Sections (## headers)
        - Confidence indicators
        - Data sources mentioned
        """
        # Extract summary (first paragraph up to double newline or first H2)
        summary = self._extract_summary(raw_output)

        # Parse sections by markdown headers
        sections = self._extract_sections(raw_output)

        # Analyze tools to determine data sources
        sources = self._extract_data_sources(tools_used)

        # Estimate confidence based on heuristics
        confidence = self._estimate_confidence(raw_output, tools_used, sources)

        # Extract reasoning from tools
        reasoning_steps = self._build_reasoning_steps(tools_used)

        # Extract recommendations if present
        recommendations = self._extract_recommendations(raw_output)

        # Extract follow-up questions
        follow_ups = self._extract_follow_up_questions(raw_output)

        return StructuredResponse(
            summary=summary,
            sections=sections if sections else [
                ResponseSection(
                    title="Response",
                    content=raw_output,
                    priority="important",
                    expandable=False
                )
            ],
            specialist=self.specialist,
            confidence=confidence,
            sources=sources,
            reasoning_steps=reasoning_steps,
            tools_called=len(tools_used),
            total_duration_ms=total_duration_ms,
            recommendations=recommendations,
            follow_up_questions=follow_ups,
            raw_markdown=raw_output,
        )

    def _extract_summary(self, text: str) -> str:
        """Extract first paragraph or sentence as summary."""
        # Remove markdown headers
        clean = re.sub(r'^#+\s+.*$', '', text, flags=re.MULTILINE)
        # Get first paragraph
        paragraphs = [p.strip() for p in clean.split('\n\n') if p.strip()]
        if paragraphs:
            first_para = paragraphs[0]
            # If first paragraph is long, take first 2 sentences
            sentences = re.split(r'[.!?]\s+', first_para)
            if len(sentences) > 1 and len(first_para) > 200:
                return ' '.join(sentences[:2]) + '.'
            return first_para[:250]
        return text[:200].strip() + "..."

    def _extract_sections(self, text: str) -> List[ResponseSection]:
        """Parse markdown headers into sections."""
        sections = []
        # Split by ## headers (H2 level)
        parts = re.split(r'^##\s+(.+?)$', text, flags=re.MULTILINE)

        if len(parts) <= 1:
            # No H2 headers, return single section
            return []

        # First part is preamble (before first header)
        preamble = parts[0].strip()
        if preamble:
            sections.append(ResponseSection(
                title="Overview",
                content=preamble,
                priority="important",
                expandable=False
            ))

        # Process header/content pairs
        for i in range(1, len(parts), 2):
            if i + 1 < len(parts):
                title = parts[i].strip()
                content = parts[i + 1].strip()

                # Determine priority based on title keywords
                priority = "important"
                if any(kw in title.lower() for kw in ["warning", "critical", "alert", "caution"]):
                    priority = "critical"
                elif any(kw in title.lower() for kw in ["note", "additional", "detail", "reference"]):
                    priority = "supplemental"

                # Make supplemental sections expandable
                expandable = priority == "supplemental"

                sections.append(ResponseSection(
                    title=title,
                    content=content,
                    priority=priority,
                    expandable=expandable
                ))

        return sections

    def _extract_data_sources(self, tools_used: List[Dict[str, Any]]) -> List[DataSource]:
        """Extract data sources from tools called."""
        sources = []
        source_map = {
            "get_metar": ("METAR", "live", "high"),
            "get_taf": ("TAF", "live", "high"),
            "get_current_weather": ("HKO Current", "live", "high"),
            "get_weather_forecast": ("HKO Forecast", "live", "high"),
            "get_weather_warnings": ("HKO Warnings", "live", "high"),
            "get_callsign": ("ADS-B Live", "live", "medium"),
            "get_arrivals_by_airport": ("ADS-B Arrivals", "live", "medium"),
            "rag_search": ("Historical Data", "historical", "medium"),
            "knowledge_graph_search": ("Knowledge Graph", "cached", "high"),
        }

        seen = set()
        for tool in tools_used:
            tool_name = tool.get("name", "")
            if tool_name in source_map and tool_name not in seen:
                name, type_, reliability = source_map[tool_name]
                sources.append(DataSource(
                    name=name,
                    type=type_,
                    timestamp=datetime.now(timezone.utc),
                    reliability=reliability,
                    details=None
                ))
                seen.add(tool_name)

        return sources

    def _estimate_confidence(
        self,
        text: str,
        tools_used: List[Dict[str, Any]],
        sources: List[DataSource],
    ) -> ConfidenceAssessment:
        """
        Estimate confidence based on heuristics:
        - Number of tools successfully called
        - Presence of error indicators
        - Data source reliability
        - Response completeness indicators
        """
        # Base confidence
        overall = 0.85

        # Penalize for errors/warnings in output
        if any(kw in text.lower() for kw in ["error", "failed", "unavailable", "unable to", "could not"]):
            overall -= 0.20
            notes = "Some data unavailable"
        elif any(kw in text.lower() for kw in ["partial", "limited", "incomplete"]):
            overall -= 0.10
            notes = "Partial data"
        else:
            notes = None

        # Bonus for multiple tools (more comprehensive)
        if len(tools_used) >= 3:
            overall += 0.05
        elif len(tools_used) == 0:
            overall -= 0.15

        # Data quality from sources
        if sources:
            avg_reliability = sum(
                {"high": 1.0, "medium": 0.7, "low": 0.4}.get(s.reliability, 0.7)
                for s in sources
            ) / len(sources)
            data_quality = avg_reliability
        else:
            data_quality = 0.5

        # Recency (assume live unless historical keyword found)
        if any(s.type == "historical" for s in sources):
            recency = 0.7
        else:
            recency = 0.95

        # Completeness (heuristic based on length and structure)
        completeness = min(0.95, 0.6 + (len(text) / 1000))

        overall = max(0.0, min(1.0, overall))

        return ConfidenceAssessment(
            overall=overall,
            data_quality=data_quality,
            completeness=completeness,
            recency=recency,
            notes=notes,
        )

    def _build_reasoning_steps(self, tools_used: List[Dict[str, Any]]) -> List[ReasoningStep]:
        """Build reasoning steps from tool calls."""
        steps = []
        for i, tool in enumerate(tools_used, 1):
            tool_name = tool.get("name", "unknown")
            tool_input = tool.get("input", {})
            duration = tool.get("duration_ms")
            output = tool.get("output", "")

            # Classify action type
            if "search" in tool_name.lower():
                action = "retrieve"
            elif any(kw in tool_name.lower() for kw in ["get", "fetch", "lookup"]):
                action = "retrieve"
            elif "compute" in tool_name.lower():
                action = "compute"
            else:
                action = "analyze"

            # Create description from tool name and input
            input_preview = ", ".join(f"{k}={v}" for k, v in list(tool_input.items())[:2])
            description = f"Calling {tool_name}" + (f" ({input_preview})" if input_preview else "")

            # Result preview (first 100 chars of output)
            result_preview = str(output)[:100] if output else None

            steps.append(ReasoningStep(
                step=i,
                action=action,
                description=description,
                tools_used=[tool_name],
                duration_ms=duration,
                result_preview=result_preview,
            ))

        return steps

    def _extract_recommendations(self, text: str) -> Optional[List[str]]:
        """Extract recommendations if present."""
        # Look for "Recommendation" section or bullet points with keywords
        rec_pattern = r'(?:^|\n)##?\s*(?:Recommendation|Action|Should|Consider).*?$\n((?:[-*]\s+.+\n?)+)'
        matches = re.findall(rec_pattern, text, re.MULTILINE | re.IGNORECASE)

        if matches:
            recommendations = []
            for match in matches:
                bullets = re.findall(r'[-*]\s+(.+)', match)
                recommendations.extend(bullets)
            return recommendations if recommendations else None

        return None

    def _extract_follow_up_questions(self, text: str) -> Optional[List[str]]:
        """Extract suggested follow-up questions."""
        # Look for questions in the text (ending with ?)
        questions = re.findall(r'[-*]\s+(.+\?)', text)
        if questions and len(questions) <= 5:
            return questions[:3]  # Limit to 3
        return None


# Convenience factory
def create_formatter(specialist: str) -> ResultFormatter:
    """Create a result formatter for a specialist."""
    return ResultFormatter(specialist=specialist)
