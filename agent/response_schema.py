"""
Structured response schema for agent outputs.

Provides consistent formatting, metadata, and progressive disclosure
across all specialist agents.
"""
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime
from pydantic import BaseModel, Field


class DataSource(BaseModel):
    """Information about a data source used in the response."""

    name: str = Field(description="Source name (e.g., 'METAR', 'HKO', 'ADS-B')")
    type: Literal["live", "historical", "computed", "cached"] = Field(
        description="Type of data source"
    )
    timestamp: Optional[datetime] = Field(
        None, description="When data was retrieved/computed"
    )
    reliability: Literal["high", "medium", "low"] = Field(
        default="medium", description="Data reliability assessment"
    )
    details: Optional[str] = Field(None, description="Additional source details")


class ConfidenceAssessment(BaseModel):
    """Confidence and quality assessment for the response."""

    overall: float = Field(ge=0.0, le=1.0, description="Overall confidence (0-1)")
    data_quality: float = Field(ge=0.0, le=1.0, description="Quality of source data")
    completeness: float = Field(ge=0.0, le=1.0, description="Response completeness")
    recency: float = Field(ge=0.0, le=1.0, description="Data freshness score")
    notes: Optional[str] = Field(
        None, description="Confidence notes (e.g., 'Partial data', 'Live feed')"
    )


class ReasoningStep(BaseModel):
    """Detailed reasoning step with context."""

    step: int = Field(description="Step number")
    action: Literal["analyze", "retrieve", "compute", "synthesize", "validate"] = Field(
        description="Action type for this step"
    )
    description: str = Field(description="What is being done")
    rationale: Optional[str] = Field(None, description="Why this step was chosen")
    tools_used: List[str] = Field(default_factory=list, description="Tools invoked")
    duration_ms: Optional[int] = Field(None, description="Step duration")
    result_preview: Optional[str] = Field(None, description="Brief result summary")
    alternatives_considered: Optional[List[str]] = Field(
        None, description="Alternative approaches considered"
    )


class ResponseSection(BaseModel):
    """A section of the structured response."""

    title: str = Field(description="Section title")
    content: str = Field(description="Section content (markdown supported)")
    priority: Literal["critical", "important", "supplemental"] = Field(
        default="important", description="Section priority for UI rendering"
    )
    expandable: bool = Field(
        default=False, description="Can be collapsed in UI"
    )


class StructuredResponse(BaseModel):
    """Complete structured response from agent."""

    # Core response
    summary: str = Field(description="1-2 sentence executive summary")
    sections: List[ResponseSection] = Field(
        description="Organized response sections"
    )

    # Metadata
    specialist: str = Field(description="Which specialist generated this")
    query_type: Optional[str] = Field(
        None, description="Classification (e.g., 'weather_briefing', 'flight_tracking')"
    )
    confidence: ConfidenceAssessment = Field(
        description="Confidence and quality metrics"
    )
    sources: List[DataSource] = Field(
        default_factory=list, description="Data sources used"
    )

    # Reasoning transparency
    reasoning_steps: List[ReasoningStep] = Field(
        default_factory=list, description="Detailed reasoning trace"
    )
    tools_called: int = Field(default=0, description="Number of tools invoked")
    total_duration_ms: Optional[int] = Field(None, description="Total processing time")

    # Recommendations & actions
    recommendations: Optional[List[str]] = Field(
        None, description="Actionable recommendations"
    )
    follow_up_questions: Optional[List[str]] = Field(
        None, description="Suggested follow-up queries"
    )

    # Raw fallback
    raw_markdown: Optional[str] = Field(
        None, description="Fallback if structured parsing fails"
    )


class PlanStep(BaseModel):
    """A step in a multi-step plan."""

    step: int
    task: str
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    assigned_to: Optional[str] = Field(None, description="Which specialist handles this")
    result_preview: Optional[str] = None
    duration_ms: Optional[int] = None


class PlanExecution(BaseModel):
    """Plan-and-execute mode tracking."""

    query: str = Field(description="Original complex query")
    plan_steps: List[PlanStep] = Field(description="Execution plan")
    current_step: int = Field(default=0, description="Currently executing step")
    completed_steps: int = Field(default=0)
    final_response: Optional[StructuredResponse] = None


def create_simple_response(
    summary: str,
    content: str,
    specialist: str,
    confidence: float = 0.8,
    sources: Optional[List[DataSource]] = None,
) -> StructuredResponse:
    """Helper to create a simple structured response."""
    return StructuredResponse(
        summary=summary,
        sections=[
            ResponseSection(
                title="Response",
                content=content,
                priority="important",
                expandable=False,
            )
        ],
        specialist=specialist,
        confidence=ConfidenceAssessment(
            overall=confidence,
            data_quality=confidence,
            completeness=0.9,
            recency=0.95,
        ),
        sources=sources or [],
    )


def format_for_display(response: StructuredResponse) -> str:
    """
    Convert structured response to display markdown.

    Includes visual formatting for sections, metadata banners, etc.
    """
    lines = []

    # Summary banner
    lines.append(f"**{response.summary}**\n")

    # Confidence indicator (if < 0.8, show warning)
    if response.confidence.overall < 0.8:
        conf_pct = int(response.confidence.overall * 100)
        lines.append(f"> ⚠️ Confidence: {conf_pct}% — {response.confidence.notes or 'Limited data available'}\n")

    # Main sections
    for section in response.sections:
        priority_marker = {
            "critical": "🔴",
            "important": "🔵",
            "supplemental": "⚪",
        }.get(section.priority, "")

        lines.append(f"## {priority_marker} {section.title}\n")
        lines.append(f"{section.content}\n")

    # Data sources (if any)
    if response.sources:
        lines.append("---\n")
        lines.append("### 📊 Data Sources\n")
        for src in response.sources:
            reliability_icon = {"high": "✅", "medium": "⚠️", "low": "❌"}.get(
                src.reliability, "❓"
            )
            age = f" ({src.timestamp.strftime('%H:%M UTC')})" if src.timestamp else ""
            lines.append(f"- {reliability_icon} **{src.name}** ({src.type}){age}\n")

    # Recommendations
    if response.recommendations:
        lines.append("\n### 💡 Recommendations\n")
        for rec in response.recommendations:
            lines.append(f"- {rec}\n")

    # Follow-up questions
    if response.follow_up_questions:
        lines.append("\n### ❓ Follow-up Questions\n")
        for q in response.follow_up_questions:
            lines.append(f"- {q}\n")

    return "\n".join(lines)
