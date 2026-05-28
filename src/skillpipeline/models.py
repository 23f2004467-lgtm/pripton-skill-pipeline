import operator
from typing import Annotated, Literal, Optional, TypedDict

from pydantic import BaseModel, Field, ValidationInfo, field_validator

# Literal types
Difficulty = Literal["beginner", "intermediate", "advanced"]
RelationshipType = Literal["prerequisite", "related", "subtopic"]
RunStatus = Literal["complete", "awaiting_review", "flagged", "running", "failed"]


class Section(BaseModel):
    """A chunk of the source document. Sections are extracted in parallel."""
    id: str
    heading: Optional[str] = None
    body: str
    order: int


class Document(BaseModel):
    """The ingested source document."""
    source_id: str
    source_path: Optional[str] = None
    raw_text: str
    sections: list[Section]


class Topic(BaseModel):
    """A single extracted topic. The atomic node in the skill graph."""
    id: str = Field(..., pattern=r"^[a-z0-9-]+$")
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(..., min_length=1, max_length=500)
    category: str = Field(..., min_length=1, max_length=80)
    difficulty: Difficulty
    source_section_id: Optional[str] = None


class Relationship(BaseModel):
    """A typed edge between two Topic ids."""
    from_id: str
    to_id: str
    type: RelationshipType
    rationale: Optional[str] = None

    @field_validator("to_id")
    @classmethod
    def no_self_loops(cls, v: str, info: ValidationInfo) -> str:
        if "from_id" in info.data and info.data["from_id"] == v:
            raise ValueError("Relationship cannot be self-referential")
        return v


class ValidationEvent(BaseModel):
    """Recorded during pipeline execution. Surfaced in the HTML report."""
    stage: str
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    retry_number: int = 0
    flagged: bool = False
    section_id: Optional[str] = None


class StageTelemetry(BaseModel):
    """Per-stage timing and cost."""
    stage: str
    started_at: str
    ended_at: str
    duration_ms: int
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


class RunMetadata(BaseModel):
    """Top-level metadata for a run; lives in the SkillMap and the report."""
    thread_id: str
    source_id: str
    started_at: str
    ended_at: Optional[str] = None
    status: RunStatus
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    stage_telemetry: list[StageTelemetry] = []
    validation_events: list[ValidationEvent] = []
    cache_hit: bool = False


class SkillMap(BaseModel):
    """The final output artifact."""
    source_id: str
    topics: list[Topic]
    relationships: list[Relationship]
    metadata: RunMetadata


# LangGraph state (TypedDict per Section 4.2)
class PipelineState(TypedDict):
    # Inputs
    source_path: Optional[str]
    raw_text: Optional[str]

    # Stage outputs
    document: Optional[Document]
    extracted_topics: Annotated[list[Topic], operator.add]
    merged_topics: Optional[list[Topic]]
    approved_topics: Optional[list[Topic]]
    relationships: Optional[list[Relationship]]
    skill_map: Optional[SkillMap]

    # Flow-control state
    extract_retries: dict[str, int]
    relate_retries: int
    extract_feedback: dict[str, str]
    relate_feedback: Optional[str]
    flagged_sections: list[str]
    flagged_relations: bool

    # Metadata accumulators
    validation_events: Annotated[list[ValidationEvent], operator.add]
    stage_telemetry: Annotated[list[StageTelemetry], operator.add]

    # Config
    always_review: bool
    thread_id: str
