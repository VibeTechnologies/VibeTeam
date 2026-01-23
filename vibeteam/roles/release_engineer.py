"""
Release Engineer Role - Manages deployments, versioning, releases.
"""

from typing import Any

from metagpt.actions import Action
from metagpt.schema import Message
from pydantic import Field

from vibeteam.roles.base import VibeRole


class PlanRelease(Action):
    """Plan a release based on completed work."""

    name: str = "PlanRelease"

    PROMPT_TEMPLATE: str = """
You are a Release Engineer. Plan this release.

## Completed Work
{work}

## Release Planning
1. **Version**: Semantic version (major.minor.patch)
2. **Release Type**: Feature / Bugfix / Hotfix
3. **Changelog**: User-facing changes
4. **Breaking Changes**: Any incompatibilities
5. **Migration Guide**: If breaking changes exist
6. **Rollout Strategy**: Percentage, regions
7. **Rollback Plan**: How to revert if needed

Create release plan:
"""

    async def run(self, work: str) -> str:
        prompt = self.PROMPT_TEMPLATE.format(work=work)
        rsp = await self._aask(prompt)
        return rsp


class WriteChangelog(Action):
    """Write changelog from commits/PRs."""

    name: str = "WriteChangelog"

    PROMPT_TEMPLATE: str = """
You are a Release Engineer. Write a changelog.

## Commits/PRs
{changes}

## Previous Version
{previous_version}

## Changelog Format (Keep a Changelog)
### [version] - date
#### Added
- New features

#### Changed
- Changes to existing features

#### Deprecated
- Features to be removed

#### Removed
- Removed features

#### Fixed
- Bug fixes

#### Security
- Security fixes

Write changelog:
"""

    async def run(self, changes: str, previous_version: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(changes=changes, previous_version=previous_version)
        rsp = await self._aask(prompt)
        return rsp


class ValidateRelease(Action):
    """Validate release readiness."""

    name: str = "ValidateRelease"

    PROMPT_TEMPLATE: str = """
You are a Release Engineer. Validate release readiness.

## Release Checklist
{checklist}

## Test Results
{test_results}

## Validation Criteria
1. **Tests**: All passing, coverage adequate
2. **Dependencies**: Updated, no vulnerabilities
3. **Documentation**: Updated for changes
4. **Changelog**: Complete and accurate
5. **Approvals**: Required sign-offs
6. **Monitoring**: Alerts configured
7. **Rollback**: Plan tested

Provide validation report:
"""

    async def run(self, checklist: str, test_results: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(checklist=checklist, test_results=test_results)
        rsp = await self._aask(prompt)
        return rsp


class CreateReleaseNotes(Action):
    """Create user-facing release notes."""

    name: str = "CreateReleaseNotes"

    PROMPT_TEMPLATE: str = """
You are a Release Engineer. Write release notes.

## Technical Changelog
{changelog}

## Target Audience
{audience}

## Release Notes Format
1. **Headline**: Exciting summary
2. **Highlights**: Top 3 features/fixes
3. **What's New**: Detailed feature descriptions
4. **Improvements**: Performance, UX enhancements
5. **Bug Fixes**: Notable fixes
6. **Known Issues**: Current limitations
7. **Upgrade Guide**: How to update

Write release notes:
"""

    async def run(self, changelog: str, audience: str = "developers") -> str:
        prompt = self.PROMPT_TEMPLATE.format(changelog=changelog, audience=audience)
        rsp = await self._aask(prompt)
        return rsp


class ReleaseEngineer(VibeRole):
    """
    Release Engineer role - manages the release lifecycle.
    
    Responsibilities:
    - Plan releases
    - Write changelogs
    - Validate release readiness
    - Create release notes
    - Manage versioning
    """

    name: str = Field(default="Frank")
    profile: str = Field(default="Release Engineer")
    goal: str = Field(default="Ship reliable releases on schedule with clear communication")
    constraints: str = Field(
        default="Never skip validation, document all changes, maintain semantic versioning"
    )
    temperature: float = Field(default=0.3)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.set_actions([
            PlanRelease,
            WriteChangelog,
            ValidateRelease,
            CreateReleaseNotes,
        ])
        self._watch([])
