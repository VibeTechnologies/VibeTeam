"""
VibeTeam Actions - Reusable actions for roles.
"""

from vibeteam.roles.marketer import (
    WriteHackerNewsPost,
    WriteLinkedInPost,
    WriteProductAnnouncement,
    WriteTwitterPost,
)
from vibeteam.roles.product_manager import PrioritizeBacklog, WritePRD, WriteUserStories
from vibeteam.roles.reliability_engineer import (
    AnalyzeIncident,
    CheckSystemHealth,
    CreateRunbook,
    WritePostmortem,
)
from vibeteam.roles.release_engineer import (
    CreateReleaseNotes,
    PlanRelease,
    ValidateRelease,
    WriteChangelog,
)
from vibeteam.roles.software_engineer import FixBug, ReviewCode, WriteCode, WriteTests
from vibeteam.roles.support_engineer import (
    AnalyzeUserIssue,
    CreateFAQEntry,
    WriteDocumentation,
    WriteUserResponse,
)

__all__ = [
    # Product Manager
    "WritePRD",
    "WriteUserStories",
    "PrioritizeBacklog",
    # Software Engineer
    "WriteCode",
    "WriteTests",
    "ReviewCode",
    "FixBug",
    # Marketer
    "WriteTwitterPost",
    "WriteLinkedInPost",
    "WriteProductAnnouncement",
    "WriteHackerNewsPost",
    # Support Engineer
    "AnalyzeUserIssue",
    "WriteUserResponse",
    "WriteDocumentation",
    "CreateFAQEntry",
    # Reliability Engineer
    "CheckSystemHealth",
    "AnalyzeIncident",
    "WritePostmortem",
    "CreateRunbook",
    # Release Engineer
    "PlanRelease",
    "WriteChangelog",
    "ValidateRelease",
    "CreateReleaseNotes",
]
