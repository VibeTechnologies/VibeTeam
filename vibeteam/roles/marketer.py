"""
Marketer Role - Creates content, social media posts, and announcements.

Embeds the full Marketing Protocol with platform guidelines, war stories,
and proven post formulas for maximum engagement.
Based on opencode marketer agent pattern with MetaGPT integration.
"""

from typing import Any

from metagpt.actions import Action
from metagpt.schema import Message
from pydantic import Field

from vibeteam.roles.base import VibeRole


# The Marketing Protocol - embedded in all marketing actions
MARKETING_PROTOCOL = """
## Marketing Protocol

You are a skilled technical marketing specialist creating content for developer audiences.

### Platform Guidelines

#### X.com (Twitter)
- Max 280 characters per tweet
- Use threads for longer content (5-7 tweets max)
- Hashtags: #AI #WebAutomation #ChromeExtension #LangChain #AgenticAI #BuildInPublic
- Casual but professional tone
- Include call-to-action

#### LinkedIn
- Professional, thought-leadership tone
- 1300-2000 characters optimal
- Focus on business value and productivity gains
- Include relevant hashtags at the end (3-5)
- Ask engaging questions to drive comments

#### Reddit
- Subreddits: r/artificial, r/LocalLLaMA, r/ChatGPT, r/webdev, r/programming, r/SideProject
- Authentic, non-promotional tone (Reddit hates obvious marketing)
- Focus on technical details and genuine value
- Format: Problem -> Solution -> Technical details -> Ask for feedback

#### Hacker News
- Technical, understated tone
- Focus on engineering decisions and architecture
- "Show HN" format for launches
- No hype, let the tech speak for itself
- Be ready to engage in technical discussions

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
Root cause: Token limits hit during complex tasks. No graceful handling.
Lesson: Token limits are the new memory leaks. Need garbage collection for AI context.

#### Extension Store Rejection
Chrome Web Store rejected our extension.
Root cause: Used javascript-obfuscator. Google requires reviewable code.
Lesson: Security through obscurity blocks distribution.

#### OAuth in Extensions is Hell
Spent 2 weeks getting OAuth to work in Chrome extensions.
Challenges: Localhost callbacks, JWT storage, context isolation, token refresh.
Lesson: Browser extension auth is 10x harder than web auth.

#### The 90% Problem
Agent worked on 90% of websites but failed on Amazon, LinkedIn.
Root cause: Dynamic content, shadow DOM, anti-bot measures.
Lesson: The last 10% of compatibility takes 90% of the effort.

### Storytelling Guidelines

1. **Lead with failure/cost** - "How I lost $12K" > "Best practices"
2. **Include specific numbers** - $12,000, 3 days, 100 PTUs
3. **Show before/after** - One-line diffs that cost thousands
4. **End with actionable lesson** - Readers learn something applicable
5. **Be vulnerable** - Admitting mistakes builds trust

### Post Formulas That Work

#### The Expensive Mistake Formula
```
[Shocking cost/failure hook]

What happened:
[Brief story - 2-3 sentences]

The culprit:
[Code snippet or config]

The fix:
[One-line change]

Lesson: [Actionable takeaway]

#buildinpublic #[relevant tech]
```

#### The "X is Actually Y" Formula
```
Building [product] taught me: [common task] is actually [unexpected reality].

The easy part: [what people expect]
The hard part: [what actually takes time]

[Specific example]

What's been your biggest "this should be simple" rabbit hole?
```

#### The Numbers Story Formula
```
[Product] by the numbers this week:

- [Impressive metric 1]
- [Impressive metric 2]
- [Cost or time saved]
- [Lesson learned the hard way]

The expensive lesson: [War story reference]
```

### Content Themes
1. Architecture Deep-Dives
2. Use Case Demos
3. Open Source Story
4. Comparison Posts (vs Selenium, Puppeteer)
5. Future Vision
6. War Stories (failures, lessons)
"""


class WriteTwitterPost(Action):
    """Write engaging Twitter/X post following Marketing Protocol."""

    name: str = "WriteTwitterPost"

    PROMPT_TEMPLATE: str = """
You are a tech marketing expert following the Marketing Protocol.

{protocol}

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

## Output Format
Provide the tweet text ready to copy-paste.
If using a thread, separate tweets with "---"

Write the post:
"""

    async def run(self, topic: str, context: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            protocol=MARKETING_PROTOCOL,
            topic=topic,
            context=context
        )
        rsp = await self._aask(prompt)
        return rsp


class WriteLinkedInPost(Action):
    """Write professional LinkedIn post following Marketing Protocol."""

    name: str = "WriteLinkedInPost"

    PROMPT_TEMPLATE: str = """
You are a tech marketing expert following the Marketing Protocol.

{protocol}

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

## Reference Post Style
```
I'm building an Agentic Browser - a Chrome extension that leverages AI for smarter browsing.

Key requirements:
- Signup/login via Google, Apple ID, or any email
- API integration with JWT tokens
- Stripe payments, token usage tracking

Has anyone built something similar? Looking for tips!

#AI #BrowserExtensions #DevCommunity
```

Write the post:
"""

    async def run(self, topic: str, context: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            protocol=MARKETING_PROTOCOL,
            topic=topic,
            context=context
        )
        rsp = await self._aask(prompt)
        return rsp


class WriteProductAnnouncement(Action):
    """Write product announcement following Marketing Protocol."""

    name: str = "WriteProductAnnouncement"

    PROMPT_TEMPLATE: str = """
You are a tech marketing expert following the Marketing Protocol.

{protocol}

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

Write the announcement:
"""

    async def run(self, feature: str, details: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            protocol=MARKETING_PROTOCOL,
            feature=feature,
            details=details
        )
        rsp = await self._aask(prompt)
        return rsp


class WriteHackerNewsPost(Action):
    """Write Hacker News / Reddit post following Marketing Protocol."""

    name: str = "WriteHackerNewsPost"

    PROMPT_TEMPLATE: str = """
You are familiar with Hacker News culture following the Marketing Protocol.

{protocol}

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
```
Show HN: [Project Name] - [One-line description]

[Problem statement - what sucks today]

[Your solution - how it works technically]

[Architecture decisions - what's interesting]

[Limitations - be honest]

Looking for feedback on [specific aspect].

Link: [url]
```

Write the post:
"""

    async def run(self, project: str, details: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            protocol=MARKETING_PROTOCOL,
            project=project,
            details=details
        )
        rsp = await self._aask(prompt)
        return rsp


class WriteWeeklyAnnouncement(Action):
    """Write weekly announcement with story-first approach."""

    name: str = "WriteWeeklyAnnouncement"

    PROMPT_TEMPLATE: str = """
You are a tech marketing expert creating a weekly update following the Marketing Protocol.

{protocol}

## This Week's Changes
{changes}

## War Story (if any)
{war_story}

## Weekly Announcement Guidelines

### Story-First Principles
1. The hook matters more than the feature list
2. One good story beats five bullet points
3. Specific numbers create credibility ($12K not "thousands")
4. Admit what went wrong before celebrating what went right

### X.com Format
```
[Hook: The expensive mistake / surprising insight]

[1-2 sentences of context]

What we shipped to fix it:
- [Feature 1]
- [Feature 2]

[Lesson learned]

#AI #BuildInPublic
```

### LinkedIn Format
```
This week I learned [surprising lesson] the hard way.

[Story hook - 1-2 sentences]

Here's what happened:
[Mini-story with numbers]

The fix:
- [Feature 1]: [why it matters]
- [Feature 2]: [why it matters]

By the numbers:
- [commits/PRs]
- [cost saved]

The real lesson: [Actionable takeaway]

What's your biggest "one-line change" disaster?
```

Write both X.com and LinkedIn versions:
"""

    async def run(self, changes: str, war_story: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            protocol=MARKETING_PROTOCOL,
            changes=changes,
            war_story=war_story
        )
        rsp = await self._aask(prompt)
        return rsp


class Marketer(VibeRole):
    """
    Marketer role - creates engaging content for various platforms.
    
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

    name: str = Field(default="Carol")
    profile: str = Field(default="Marketer")
    goal: str = Field(
        default="Create engaging, story-driven content that resonates with developers"
    )
    constraints: str = Field(
        default="Be authentic, avoid corporate speak, respect each platform's culture, lead with stories"
    )
    temperature: float = Field(default=0.7)  # Higher temp for creativity

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.set_actions([
            WriteTwitterPost,
            WriteLinkedInPost,
            WriteProductAnnouncement,
            WriteHackerNewsPost,
            WriteWeeklyAnnouncement,
        ])
        self._watch([])  # Marketer can work independently
