"""
Marketer Agent - Creates content, social media posts, and announcements.

Embeds the full Marketing Protocol with platform guidelines, war stories,
and proven post formulas for maximum engagement.
OpenHands-based replacement for the MetaGPT Marketer role.
"""

from typing import Any

from vibeteam.agents.base import BaseVibeAgent

# The Marketing Protocol
MARKETING_PROTOCOL = """
## Marketing Protocol

You are a skilled technical marketing specialist creating content for developer audiences.

### Platform Guidelines

#### X.com (Twitter)
- Max 280 characters per tweet
- Use threads for longer content (5-7 tweets max)
- Hashtags: #AI #WebAutomation #ChromeExtension #AgenticAI #BuildInPublic
- Casual but professional tone
- Include call-to-action

#### LinkedIn
- Professional, thought-leadership tone
- 1300-2000 characters optimal
- Focus on business value and productivity gains
- Include relevant hashtags at the end (3-5)
- Ask engaging questions to drive comments

#### Reddit
- Subreddits: r/artificial, r/LocalLLaMA, r/ChatGPT, r/webdev, r/programming
- Authentic, non-promotional tone (Reddit hates obvious marketing)
- Focus on technical details and genuine value
- Format: Problem -> Solution -> Technical details -> Ask for feedback

#### Hacker News
- Technical, understated tone
- Focus on engineering decisions and architecture
- "Show HN" format for launches
- No hype, let the tech speak for itself

### War Stories Library

Reference these real incidents when creating engaging content:

#### The $12K PTU Mistake
Asked Claude to write Terraform for Azure OpenAI. It chose PTU pricing instead of pay-per-token.
Cost: $12,000 in 3 days for zero API calls.
Lesson: AI doesn't understand cloud billing. Always verify infrastructure costs.

#### Cloudflare Redirect Loop
Changed SSL mode to "flexible" for vibebrowser.app. Site became inaccessible.
Root cause: Azure Static Web Apps enforces HTTPS, "flexible" uses HTTP = infinite loop.
Lesson: SSL mode must be "full" or "strict" when origin enforces HTTPS.

#### Context Window Exhaustion
Agent would fail mid-task with cryptic errors.
Root cause: Token limits hit during complex tasks.
Lesson: Token limits are the new memory leaks. Need garbage collection for AI context.

### Storytelling Guidelines

1. **Lead with failure/cost** - "How I lost $12K" > "Best practices"
2. **Include specific numbers** - $12,000, 3 days, 100 PTUs
3. **Show before/after** - One-line diffs that cost thousands
4. **End with actionable lesson** - Readers learn something applicable
5. **Be vulnerable** - Admitting mistakes builds trust
"""


class MarketerAgent(BaseVibeAgent):
    """
    Marketer agent - creates engaging content for various platforms.

    Follows the Marketing Protocol with:
    - Platform-specific guidelines (Twitter, LinkedIn, HN, Reddit)
    - War Stories Library for engaging content
    - Proven post formulas
    - Story-first approach

    Philosophy:
    > "Stories are remembered 22x more than facts alone."
    > "Lead with the failure, end with the lesson."
    > "Specific numbers create credibility."
    """

    name = "MarketingManager"
    profile = "Marketing Manager"
    goal = "Create engaging, story-driven content that resonates with developers"
    temperature = 0.7  # Higher temp for creativity

    def __init__(self, **kwargs: Any):
        super().__init__(
            name=kwargs.get("name", self.name),
            profile=self.profile,
            goal=self.goal,
            temperature=kwargs.get("temperature", self.temperature),
            tools=[],  # Marketer doesn't need external tools
        )

    def _get_system_prompt(self) -> str:
        """Custom system prompt with Marketing Protocol."""
        return f"""You are {self.name}, a {self.profile}.

Goal: {self.goal}

{MARKETING_PROTOCOL}

You create engaging content for developer audiences using story-first approach.
"""

    async def write_twitter_post(self, topic: str, context: str = "") -> str:
        """
        Write engaging Twitter/X post.

        Args:
            topic: The topic to post about
            context: Additional context

        Returns:
            Tweet or thread ready to post
        """
        prompt = f"""Write a Twitter/X post following the Marketing Protocol.

## Topic
{topic}

## Context
{context}

## Twitter-Specific Rules
- Max 280 characters per tweet
- Use hooks that grab attention
- Include 2-3 relevant hashtags
- Conversational, authentic tone
- Can use thread format for longer content
- Lead with a story or failure if relevant

Provide the tweet text ready to copy-paste.
If using a thread, separate tweets with "---"

Write the post:"""

        return await self.run(prompt)

    async def write_linkedin_post(self, topic: str, context: str = "") -> str:
        """
        Write professional LinkedIn post.

        Args:
            topic: The topic to post about
            context: Additional context

        Returns:
            LinkedIn post ready to publish
        """
        prompt = f"""Write a LinkedIn post following the Marketing Protocol.

## Topic
{topic}

## Context
{context}

## LinkedIn-Specific Rules
- Professional but personable tone
- Start with a hook (story, failure, surprising insight)
- Use line breaks for readability
- 1300-2000 characters optimal
- Include call to action
- End with discussion question
- Add 3-5 relevant hashtags

Write the post:"""

        return await self.run(prompt)

    async def write_product_announcement(self, feature: str, details: str = "") -> str:
        """
        Write product announcement.

        Args:
            feature: The feature or release to announce
            details: Additional details

        Returns:
            Product announcement
        """
        prompt = f"""Write a product announcement following the Marketing Protocol.

## Release/Feature
{feature}

## Details
{details}

## Announcement Format
1. **Hook** - Start with impact or problem solved
2. **Summary** - 2-3 sentences on what and why
3. **Key Features** - Bullet points of main benefits
4. **Technical Highlights** - For developer audience
5. **Call to Action** - Clear next step

## Story-First Approach
If there's a war story that led to this feature, lead with it!
"We lost $12K to a billing misconfiguration. So we built..."

Write the announcement:"""

        return await self.run(prompt)

    async def write_hackernews_post(self, project: str, details: str = "") -> str:
        """
        Write Hacker News / Reddit post.

        Args:
            project: The project to post about
            details: Technical details

        Returns:
            HN/Reddit post
        """
        prompt = f"""Write a Hacker News post following the Marketing Protocol.

## Project
{project}

## Technical Details
{details}

## HN/Reddit Guidelines
- Technical, no marketing fluff
- Lead with the problem you solved
- Be honest about limitations
- Invite discussion and feedback
- Focus on technical decisions
- Mention if open source
- NO hype - let the tech speak

## HN Format
Show HN: [Project Name] - [One-line description]

[Problem statement - what sucks today]
[Your solution - how it works technically]
[Architecture decisions - what's interesting]
[Limitations - be honest]
Looking for feedback on [specific aspect].
Link: [url]

Write the post:"""

        return await self.run(prompt)

    async def write_weekly_announcement(self, changes: str, war_story: str = "") -> str:
        """
        Write weekly announcement with story-first approach.

        Args:
            changes: This week's changes
            war_story: Any war story from this week

        Returns:
            Both Twitter and LinkedIn versions
        """
        prompt = f"""Write a weekly update following the Marketing Protocol.

## This Week's Changes
{changes}

## War Story (if any)
{war_story}

## Story-First Principles
1. The hook matters more than the feature list
2. One good story beats five bullet points
3. Specific numbers create credibility
4. Admit what went wrong before celebrating what went right

Write BOTH:
1. X.com/Twitter version (with thread if needed)
2. LinkedIn version (longer, more professional)

Write both versions:"""

        return await self.run(prompt)
