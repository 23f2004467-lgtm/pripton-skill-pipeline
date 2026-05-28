# Shared fixtures for tests. Added as part of Step 1; populated in later steps.
import pytest


@pytest.fixture(autouse=True)
def _dummy_groq_key(monkeypatch):
    """Provide a dummy GROQ_API_KEY so the default client can be constructed.

    The Groq SDK validates the key eagerly at construction (unlike Anthropic's
    deferred check), so tests that build the default client without making a
    real call still need a key present. Tests that hit the network are mocked.
    """
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_dummy")


@pytest.fixture
def sample_section():
    """A sample Section for testing."""
    from skillpipeline.models import Section
    return Section(
        id="section-0",
        heading="Introduction to React",
        body="React is a JavaScript library for building user interfaces.",
        order=0,
    )


@pytest.fixture
def sample_topic():
    """A sample Topic for testing."""
    from skillpipeline.models import Topic
    return Topic(
        id="react-basics",
        name="React Basics",
        description="Fundamental concepts of React",
        category="frontend",
        difficulty="beginner",
    )


@pytest.fixture
def sample_topics():
    """Multiple sample Topics for testing."""
    from skillpipeline.models import Topic
    return [
        Topic(
            id="javascript",
            name="JavaScript",
            description="The programming language of the web",
            category="backend",
            difficulty="beginner",
        ),
        Topic(
            id="react",
            name="React",
            description="A JavaScript library for building UIs",
            category="frontend",
            difficulty="intermediate",
        ),
        Topic(
            id="react-hooks",
            name="React Hooks",
            description="Features for state and lifecycle in functional components",
            category="frontend",
            difficulty="intermediate",
        ),
    ]
