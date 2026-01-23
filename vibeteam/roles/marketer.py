"""
Marketer Role - Creates content, social media posts, and announcements.

Based on opencode marketer agent pattern with MetaGPT integration.
"""

from typing import Any

from metagpt.actions import Action
from metagpt.schema import Message
from pydantic import Field

from vibeteam.roles.base import VibeRole


class WriteTwitterPost(Action):
    """Write engaging Twitter/X post."""

    name: str = "WriteTwitterPost"

    PROMPT_TEMPLATE: str = """
You are a tech marketing expert. Write an engaging Twitter/X post.

## Topic
{topic}

## Context
{context}

## Guidelines
- Max 280 characters
- Use hooks that grab attention
- Include relevant hashtags (2-3 max)
- Use conversational, authentic tone
- Avoid corporate speak
- Can use thread format if needed

Write the post:
"""

    async def run(self, topic: str, context: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(topic=topic, context=context)
        rsp = await self._aask(prompt)
        return rsp


class WriteLinkedInPost(Action):
    """Write professional LinkedIn post."""

    name: str = "WriteLinkedInPost"

    PROMPT_TEMPLATE: str = """
You are a tech marketing expert. Write a LinkedIn post.

## Topic
{topic}

## Context
{context}

## Guidelines
- Professional but personable tone
- Start with a hook
- Use line breaks for readability
- Include a call to action
- 1300 characters optimal
- Add relevant hashtags (3-5)

Write the post:
"""

    async def run(self, topic: str, context: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(topic=topic, context=context)
        rsp = await self._aask(prompt)
        return rsp


class WriteProductAnnouncement(Action):
    """Write product announcement or release notes."""

    name: str = "WriteProductAnnouncement"

    PROMPT_TEMPLATE: str = """
You are a tech marketing expert. Write a product announcement.

## Release/Feature
{feature}

## Details
{details}

## Announcement Format
1. **Headline**: Catchy, benefit-focused
2. **Summary**: 2-3 sentences on what and why
3. **Key Features**: Bullet points of main benefits
4. **How to Use**: Quick start guide
5. **Call to Action**: Clear next step

Write the announcement:
"""

    async def run(self, feature: str, details: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(feature=feature, details=details)
        rsp = await self._aask(prompt)
        return rsp


class WriteHackerNewsPost(Action):
    """Write Hacker News / Reddit post."""

    name: str = "WriteHackerNewsPost"

    PROMPT_TEMPLATE: str = """
You are familiar with Hacker News culture. Write a Show HN post.

## Project
{project}

## Technical Details
{details}

## HN Guidelines
- Technical, no marketing fluff
- Lead with the problem you solved
- Be honest about limitations
- Invite discussion and feedback
- Focus on technical decisions

Write the post:
"""

    async def run(self, project: str, details: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(project=project, details=details)
        rsp = await self._aask(prompt)
        return rsp


class Marketer(VibeRole):
    """
    Marketer role - creates engaging content for various platforms.
    
    Responsibilities:
    - Write Twitter/X posts
    - Write LinkedIn content
    - Create product announcements
    - Write HN/Reddit posts
    - Develop content strategy
    
    Story-first approach:
    "Stories are remembered 22x more than facts alone."
    """

    name: str = Field(default="Carol")
    profile: str = Field(default="Marketer")
    goal: str = Field(
        default="Create engaging content that resonates with developers and drives adoption"
    )
    constraints: str = Field(
        default="Be authentic, avoid corporate speak, respect each platform's culture"
    )
    temperature: float = Field(default=0.7)  # Higher temp for creativity

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.set_actions([
            WriteTwitterPost,
            WriteLinkedInPost,
            WriteProductAnnouncement,
            WriteHackerNewsPost,
        ])
        self._watch([])  # Marketer can work independently
