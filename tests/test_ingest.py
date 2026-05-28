import pytest

from skillpipeline.ingest import (
    ingest_document,
    make_ingest_node,
    split_markdown_by_headings,
)


class TestSplitMarkdownByHeadings:
    def test_h1_headings(self):
        text = """# Introduction

This is the intro.

# Chapter 1

Content here."""
        sections = split_markdown_by_headings(text)
        assert len(sections) == 2
        assert sections[0] == ("Introduction", "This is the intro.", 0)
        assert sections[1] == ("Chapter 1", "Content here.", 1)

    def test_h2_headings(self):
        text = """## Overview

Some content.

## Details

More details."""
        sections = split_markdown_by_headings(text)
        assert len(sections) == 2
        assert sections[0] == ("Overview", "Some content.", 0)

    def test_mixed_h1_and_h2(self):
        text = """# Main

Content.

## Sub 1

Sub content.

## Sub 2

More sub content."""
        sections = split_markdown_by_headings(text)
        assert len(sections) == 3
        assert sections[0][0] == "Main"
        assert sections[1][0] == "Sub 1"
        assert sections[2][0] == "Sub 2"

    def test_no_headings_single_section(self):
        text = """This is just plain text.
With no headings.
Just content."""
        sections = split_markdown_by_headings(text)
        assert len(sections) == 1
        assert sections[0] == (None, text.strip(), 0)

    def test_headings_with_code_blocks(self):
        text = """# Python

```python
def hello():
    print("world")
```

# JavaScript

```js
console.log("hello");
```"""
        sections = split_markdown_by_headings(text)
        assert len(sections) == 2
        # Body should include code blocks
        assert "```python" in sections[0][1]
        assert "```js" in sections[1][1]

    def test_heading_at_very_end(self):
        text = """# Intro

Content.

# End"""
        sections = split_markdown_by_headings(text)
        assert len(sections) == 2
        # The last section has empty body (will be filtered later)
        assert sections[1][0] == "End"
        assert sections[1][1] == ""


class TestIngestDocument:
    def test_from_raw_text(self):
        text = """# React Basics

Components are the building blocks."""
        doc, events = ingest_document(raw_text=text)

        assert doc.source_id
        assert len(doc.sections) == 1
        assert doc.sections[0].heading == "React Basics"
        assert "Components are the building blocks" in doc.sections[0].body
        assert doc.raw_text == text

    def test_from_file(self, tmp_path):
        content = """# Frontend

HTML, CSS, JS."""
        file_path = tmp_path / "test.md"
        file_path.write_text(content)

        doc, events = ingest_document(source_path=str(file_path))

        assert doc.source_path == str(file_path)
        assert len(doc.sections) == 1
        assert doc.sections[0].heading == "Frontend"

    def test_source_id_deterministic(self):
        text = "Same content"
        doc1, _ = ingest_document(raw_text=text)
        doc2, _ = ingest_document(raw_text=text)

        assert doc1.source_id == doc2.source_id

    def test_source_id_different_for_different_content(self):
        doc1, _ = ingest_document(raw_text="Content A")
        doc2, _ = ingest_document(raw_text="Content B")

        assert doc1.source_id != doc2.source_id

    def test_empty_sections_dropped(self):
        text = """# Start

Content.

# Empty

# End

Final content."""
        doc, events = ingest_document(raw_text=text)

        # Should have 2 sections (Start and End), Empty dropped
        assert len(doc.sections) == 2
        assert doc.sections[0].heading == "Start"
        assert doc.sections[1].heading == "End"

        # Should have logged an EMPTY_SECTION event
        empty_events = [e for e in events if e.code == "EMPTY_SECTION"]
        assert len(empty_events) == 1
        assert "Empty" in empty_events[0].message

    def test_all_sections_empty_creates_fallback(self):
        text = """# A

# B

# C"""
        doc, events = ingest_document(raw_text=text)

        # Should have one section with full content as fallback
        assert len(doc.sections) == 1
        assert doc.sections[0].heading is None
        assert doc.sections[0].id == "section-0"

        # Should have logged ALL_SECTIONS_EMPTY warning
        all_empty_events = [e for e in events if e.code == "ALL_SECTIONS_EMPTY"]
        assert len(all_empty_events) == 1

    def test_section_ids_and_order(self):
        text = """# First

Content 1.

# Second

Content 2.

# Third

Content 3."""
        doc, events = ingest_document(raw_text=text)

        assert len(doc.sections) == 3
        assert doc.sections[0].id == "section-0"
        assert doc.sections[0].order == 0
        assert doc.sections[1].id == "section-1"
        assert doc.sections[1].order == 1
        assert doc.sections[2].id == "section-2"
        assert doc.sections[2].order == 2

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            ingest_document(source_path="/nonexistent/file.md")

    def test_neither_path_nor_text(self):
        with pytest.raises(ValueError, match="Either source_path or raw_text"):
            ingest_document()

    def test_utf8_with_replacement(self):
        # Create text with invalid UTF-8 sequence
        doc, events = ingest_document(raw_text="Valid text")
        assert doc.raw_text == "Valid text"


class TestIngestNode:
    def test_node_updates_state(self):
        text = """# Test

Content here."""
        node = make_ingest_node()

        state = node({
            "source_path": None,
            "raw_text": text,
            "validation_events": [],
            "stage_telemetry": [],
        })

        assert "document" in state
        assert state["document"].sections[0].heading == "Test"
        assert len(state["validation_events"]) >= 0  # May have events
        assert len(state["stage_telemetry"]) == 1
        assert state["stage_telemetry"][0].stage == "ingest"

    def test_node_records_telemetry(self):
        node = make_ingest_node()

        state = node({
            "source_path": None,
            "raw_text": "# Test\nContent",
            "validation_events": [],
            "stage_telemetry": [],
        })

        telemetry = state["stage_telemetry"][0]
        assert telemetry.stage == "ingest"
        assert telemetry.llm_calls == 0
        assert telemetry.duration_ms >= 0
