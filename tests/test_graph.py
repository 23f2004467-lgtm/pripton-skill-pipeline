"""Tests for graph module - sub-step 12a (linear graph)."""

import pytest

from skillpipeline.graph import create_graph
from skillpipeline.llm import FakeLLMClient


class TestGraphCompiles:
    """Test that the graph compiles successfully (sub-step 12a)."""

    def test_graph_compiles_with_default_client(self):
        """Graph should compile with default AnthropicLLMClient."""
        graph = create_graph()
        assert graph is not None
        # Compilation happens when we access the graph
        compiled = graph.compile()
        assert compiled is not None

    def test_graph_compiles_with_fake_client(self):
        """Graph should compile with FakeLLMClient for testing."""
        fake_client = FakeLLMClient()
        graph = create_graph(fake_client)
        assert graph is not None
        compiled = graph.compile()
        assert compiled is not None
