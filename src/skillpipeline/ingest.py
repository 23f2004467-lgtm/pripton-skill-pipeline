"""Stage 1 — Ingest. Load markdown, compute idempotency key, split into sections."""

import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Optional

from skillpipeline.models import Document, Section, StageTelemetry, ValidationEvent


def split_markdown_by_headings(raw_text: str) -> list[tuple[Optional[str], str, int]]:
    """Split markdown text by H1 and H2 headings.

    Returns:
        List of (heading, body, order) tuples.
        - heading: The heading text without # marks, or None if no heading
        - body: The content under this heading
        - order: Position in the document

    Strategy: Split on ^#{1,2} lines. Each section captures the heading
    line plus all body content up to the next H1/H2.

    If the document contains no H1/H2 headings, returns a single section
    with heading=None and the full text as body.
    """
    # Pattern to match H1 or H2 at start of line (with optional leading whitespace)
    # Captures: (full match, heading level, heading text, position in text)
    heading_pattern = re.compile(r"^(#{1,2})\s+(.+)$", re.MULTILINE)

    # Find all heading positions
    matches = list(heading_pattern.finditer(raw_text))

    if not matches:
        # No headings found - entire document is one section
        return [(None, raw_text.strip(), 0)]

    sections: list[tuple[Optional[str], str, int]] = []
    for i, match in enumerate(matches):
        heading_text = match.group(2)
        start_pos = match.start()

        # End position is the start of the next heading, or end of document
        if i + 1 < len(matches):
            end_pos = matches[i + 1].start()
        else:
            end_pos = len(raw_text)

        body = raw_text[start_pos:end_pos].strip()
        # Remove the heading line itself from the body
        first_newline = body.find("\n")
        if first_newline != -1:
            body = body[first_newline + 1:].strip()
        else:
            # Heading with no body content
            body = ""

        sections.append((heading_text, body, i))

    return sections


def ingest_document(
    source_path: Optional[str] = None,
    raw_text: Optional[str] = None,
) -> tuple[Document, list[ValidationEvent]]:
    """Load a markdown document and split it into sections.

    Args:
        source_path: Optional path to a file to read. Takes precedence over raw_text.
        raw_text: Raw markdown text as a string.

    Returns:
        (Document, validation_events) tuple.

    Raises:
        FileNotFoundError: If source_path doesn't exist.
        IOError: If source_path cannot be read.
    """
    validation_events: list[ValidationEvent] = []

    # Read raw bytes
    if source_path:
        path = Path(source_path)
        if not path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")
        raw_bytes = path.read_bytes()
    elif raw_text is not None:
        raw_bytes = raw_text.encode("utf-8")
    else:
        raise ValueError("Either source_path or raw_text must be provided")

    # Compute source_id (idempotency key)
    source_id = hashlib.sha256(raw_bytes).hexdigest()

    # Decode to UTF-8 with error replacement
    text = raw_bytes.decode("utf-8", errors="replace")

    # Split into sections
    raw_sections = split_markdown_by_headings(text)

    # Build Section objects, dropping empty ones
    sections: list[Section] = []
    for heading, body, order in raw_sections:
        body_stripped = body.strip()
        if not body_stripped:
            # Empty section - log and skip
            validation_events.append(
                ValidationEvent(
                    stage="ingest",
                    severity="info",
                    code="EMPTY_SECTION",
                    message=f"Section {order} ('{heading or 'Untitled'}') has no body content, skipping",
                )
            )
            continue

        sections.append(
            Section(
                id=f"section-{order}",
                heading=heading,
                body=body_stripped,
                order=order,
            )
        )

    # Handle the edge case where ALL sections were empty
    if not sections:
        validation_events.append(
            ValidationEvent(
                stage="ingest",
                severity="warning",
                code="ALL_SECTIONS_EMPTY",
                message="All sections were empty; creating single section with full content",
            )
        )
        sections.append(
            Section(
                id="section-0",
                heading=None,
                body=text.strip(),
                order=0,
            )
        )

    document = Document(
        source_id=source_id,
        source_path=source_path,
        raw_text=text,
        sections=sections,
    )

    return document, validation_events


def make_ingest_node() -> Callable[[dict[str, object]], dict[str, object]]:
    """Create the LangGraph node function for the ingest stage.

    The node function takes the graph state and updates it with the
    ingested document and validation events.
    """

    def ingest_node(state: dict[str, object]) -> dict[str, object]:
        """LangGraph node function for ingest stage."""
        source_path = state.get("source_path")
        raw_text = state.get("raw_text")

        # Type narrowing for mypy
        sp = source_path if isinstance(source_path, (str, type(None))) else None
        rt = raw_text if isinstance(raw_text, (str, type(None))) else None

        # Record telemetry
        import time

        started_at = time.time()
        started_at_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_at))

        document, validation_events = ingest_document(
            source_path=sp,
            raw_text=rt,
        )

        ended_at = time.time()
        duration_ms = int((ended_at - started_at) * 1000)
        ended_at_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ended_at))

        telemetry = StageTelemetry(
            stage="ingest",
            started_at=started_at_iso,
            ended_at=ended_at_iso,
            duration_ms=duration_ms,
            llm_calls=0,
        )

        return {
            "document": document,
            "validation_events": validation_events,
            "stage_telemetry": [telemetry],
        }

    return ingest_node
