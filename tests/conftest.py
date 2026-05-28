# Shared fixtures for tests. Added as part of Step 1; populated in later steps.
import pytest


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
    from skillpipeline.models import Topic, Difficulty
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
