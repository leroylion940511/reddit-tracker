"""v5 AI newsroom domain contracts and future orchestration services.

The package is intentionally independent from the v4 scheduler while the
newsroom pipeline is built and verified in isolation.
"""

from .contracts import (
    AgentArtifact,
    AgentStage,
    Confidence,
    EditionPlan,
    ReaderBrief,
    SourceRef,
    StoryKind,
    StoryPitch,
)

__all__ = [
    "AgentArtifact",
    "AgentStage",
    "Confidence",
    "EditionPlan",
    "ReaderBrief",
    "SourceRef",
    "StoryKind",
    "StoryPitch",
]
