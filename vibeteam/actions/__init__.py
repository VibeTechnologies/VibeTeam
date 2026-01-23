"""
VibeTeam Actions - Reusable actions for roles.

Each action embeds the full protocol for its domain, enabling
autonomous execution with minimal supervision.
"""

from vibeteam.roles.marketer import (
    WriteHackerNewsPost,
    WriteLinkedInPost,
    WriteProductAnnouncement,
    WriteTwitterPost,
    WriteWeeklyAnnouncement,
)
from vibeteam.roles.product_manager import PrioritizeBacklog, WritePRD, WriteUserStories
from vibeteam.roles.release_engineer import (
    CreateReleaseNotes,
    PlanRelease,
    ValidateRelease,
    WriteChangelog,
)
from vibeteam.roles.reliability_engineer import (
    AnalyzeIncident,
    CheckReleaseReadiness,
    CheckSystemHealth,
    CreateRunbook,
    VerifyDeployment,
    WritePostmortem,
)
from vibeteam.roles.software_engineer import (
    CreatePR,
    FixBug,
    ReviewCode,
    WriteCode,
    WriteTests,
)
from vibeteam.roles.support_engineer import (
    AnalyzeCustomerEmail,
    AnalyzeUserIssue,
    CreateFAQEntry,
    FlagForEscalation,
    SearchKnowledgeBase,
    ValidateResponseSecurity,
    WriteDocumentation,
    WriteEmailResponse,
    WriteUserResponse,
)

__all__ = [
    # Product Manager
    "WritePRD",
    "WriteUserStories",
    "PrioritizeBacklog",
    # Software Engineer (Torvalds Protocol)
    "WriteCode",
    "WriteTests",
    "ReviewCode",
    "FixBug",
    "CreatePR",
    # Marketer (Marketing Protocol)
    "WriteTwitterPost",
    "WriteLinkedInPost",
    "WriteProductAnnouncement",
    "WriteHackerNewsPost",
    "WriteWeeklyAnnouncement",
    # Support Engineer (Support Protocol with Security Guardrails)
    "AnalyzeCustomerEmail",
    "WriteEmailResponse",
    "FlagForEscalation",
    "SearchKnowledgeBase",
    "ValidateResponseSecurity",
    "AnalyzeUserIssue",
    "WriteUserResponse",
    "WriteDocumentation",
    "CreateFAQEntry",
    # Reliability Engineer (Prod-Eng Protocol)
    "CheckSystemHealth",
    "VerifyDeployment",
    "AnalyzeIncident",
    "WritePostmortem",
    "CreateRunbook",
    "CheckReleaseReadiness",
    # Release Engineer
    "PlanRelease",
    "WriteChangelog",
    "ValidateRelease",
    "CreateReleaseNotes",
]
