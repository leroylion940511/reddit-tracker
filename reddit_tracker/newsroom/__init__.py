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
from .planning import (
    AssignmentEditorAgent,
    CandidateWindow,
    EditorialPlanningError,
    ReaderProfileAgent,
    ScoutAgent,
    plan_edition,
    previous_calendar_day_window,
)

__all__ = [
    "AgentArtifact",
    "AgentStage",
    "AssignmentEditorAgent",
    "CandidateWindow",
    "Confidence",
    "EditorialPlanningError",
    "EditionPlan",
    "ReaderBrief",
    "ReaderProfileAgent",
    "ScoutAgent",
    "SourceRef",
    "StoryKind",
    "StoryPitch",
    "plan_edition",
    "previous_calendar_day_window",
]
