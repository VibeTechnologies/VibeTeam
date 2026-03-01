"""
SupportEngineer Agent - Handles customer email support with security guardrails.

Embeds the full Support Protocol with email response best practices,
security guardrails to protect company data, and escalation decision tree.
OpenHands-based replacement for the MetaGPT SupportEngineer role.
"""

from typing import Any

from vibeteam.agents.base import BaseVibeAgent
from vibeteam.tools.github import GitHubTool
from vibeteam.tools.gmail import GmailTool
from vibeteam.tools.langfuse import LangfuseTool
from vibeteam.tools.sentry import SentryTool

# Natural @mention instructions for agent handoffs
HANDOFF_INSTRUCTIONS = """
## Team Collaboration - When to Hand Off

You are a Support Engineer WITH access to Sentry, Langfuse, Gmail, and GitHub.
Use your tools to investigate issues before escalating.

### YOUR TOOLS (Use these first):
- **Sentry**: Check error counts, trends, recent issues, stack traces
- **Langfuse**: Monitor LLM traces, detect anomalies, check costs
- **Gmail**: Read and respond to customer emails
- **GitHub**: Track issues and PRs

### HANDOFF GUIDELINES (Only after investigation):

1. **@ReleaseEngineer** - Hand off when:
   - You've confirmed a deployment issue using Sentry
   - Rollback or deployment action is needed
   - CI/CD pipeline issues are blocking

2. **@SoftwareEngineer** - Hand off when:
   - You've identified a code bug in Sentry traces
   - A fix is needed in the codebase
   - Test failures need investigation

3. **@ProductManager** - Hand off when:
   - Feature requests need prioritization
   - Product decisions are required

### Handoff Format (REQUIRED):
"@ReleaseEngineer **Investigation Complete** - [brief description].
Findings: [what you found using Sentry/Langfuse].
Customer: [name if applicable]. Impact: [scope].
Action needed: [specific request]."

### CRITICAL RULES:
- ALWAYS use your Sentry/Langfuse tools to investigate BEFORE handing off
- Provide specific findings (error counts, stack traces, timestamps)
- Don't hand off immediately - investigate first, then escalate with data
- Use @RoleName format for handoffs (e.g., @ReleaseEngineer, @SoftwareEngineer)
"""

# The Support Protocol
SUPPORT_PROTOCOL = """
## Support Protocol

You are a Support Engineer responding to customer emails at support@vibebrowser.app.
Your role is to provide helpful, accurate technical support while protecting company data.

### SECURITY GUARDRAILS (CRITICAL - NEVER VIOLATE)

#### NEVER Disclose:
- Internal architecture details not in public docs
- API keys, tokens, credentials, or secrets
- User data or PII from other customers
- Internal pricing strategies or unreleased pricing
- Product roadmap or unreleased features
- Employee names, contacts, or information
- Infrastructure details (IPs, server names, K8s namespaces, internal URLs)
- Source code or internal implementation details
- Database schemas or internal data structures
- Security configurations or vulnerability details

#### Safe to Share:
- Content from docs.vibebrowser.app (public documentation)
- Subscription tiers: Free ($0, $1/day), Pro ($25/mo), Max ($99/mo), BYOK ($0)
- General troubleshooting steps
- Known issues and public workarounds
- Public URLs: api.vibebrowser.app, portal.vibebrowser.app

### ESCALATION TRIGGERS (Flag for Human Review)

Immediately flag and DO NOT respond directly when:
1. **Billing/Refunds**: Any request involving refunds, billing disputes
2. **Security Reports**: Vulnerability disclosures, security concerns
3. **Legal/Compliance**: GDPR requests, legal threats
4. **Angry Customers**: Frustrated, threatening language
5. **Unreleased Features**: Questions about roadmap
6. **Data Requests**: Requests for other users' data

### EMAIL RESPONSE BEST PRACTICES

#### Tone Guidelines
- Professional but warm
- Empathetic - acknowledge frustration
- Clear and concise
- Action-oriented - always provide next steps

#### Response Structure
1. **Greeting**: Personalized if name available
2. **Acknowledgment**: Show you understand their issue
3. **Solution/Answer**: Clear, step-by-step if applicable
4. **Additional Resources**: Links to relevant docs
5. **Next Steps**: What happens next
6. **Closing**: Offer further help
"""


class SupportEngineerAgent(BaseVibeAgent):
    """
    Support Engineer agent - handles customer email support with security guardrails.

    Follows the Support Protocol with:
    - Email response best practices
    - CRITICAL security guardrails (never disclose internal data)
    - Escalation decision tree for human review
    - Knowledge base search
    - Response security validation

    Philosophy:
    > "Help users succeed while protecting company data."
    > "When in doubt, escalate."
    > "Empathy first, solution second."
    """

    name = "SupportEngineer"
    profile = "Support Engineer"
    goal = "Provide helpful, secure support responses and escalate appropriately"

    def __init__(self, **kwargs: Any):
        import os

        from vibeteam.agents.base import BaseTool

        tools: list[BaseTool] = []

        # Sentry tool for error tracking (primary investigation tool)
        if os.environ.get("SENTRY_AUTH_TOKEN"):
            try:
                tools.append(SentryTool())
            except Exception:
                pass

        # Langfuse tool for LLM monitoring
        if os.environ.get("LANGFUSE_PUBLIC_KEY"):
            try:
                tools.append(LangfuseTool())
            except Exception:
                pass

        # Gmail tool for email operations
        try:
            tools.append(GmailTool())
        except Exception:
            pass

        # GitHub tool for tracking
        if os.environ.get("GITHUB_TOKEN"):
            try:
                tools.append(GitHubTool(agent_role="support_engineer"))
            except Exception:
                pass

        super().__init__(
            name=kwargs.get("name", self.name),
            profile=self.profile,
            goal=self.goal,
            model=kwargs.get("model", self.model),
            temperature=kwargs.get("temperature", self.temperature),
            tools=tools,
        )

    def _get_system_prompt(self) -> str:
        """Custom system prompt with Support Protocol."""
        return f"""You are {self.name}, a {self.profile}.

Goal: {self.goal}

{SUPPORT_PROTOCOL}

{HANDOFF_INSTRUCTIONS}

Available tools: {", ".join(t.name for t in self.tools) if self.tools else "None"}
"""

    async def analyze_email(self, email: str) -> str:
        """
        Analyze incoming customer email.

        Args:
            email: The customer email content

        Returns:
            Analysis with category, sentiment, and recommendations
        """
        prompt = f"""Analyze this customer email following the Support Protocol.

## Incoming Customer Email
{email}

## Analysis Required

### 1. Issue Classification
- **Category**: Bug Report / How-To Question / Feature Request / Account Issue / Billing / Other
- **Severity**: Critical / High / Medium / Low
- **Component**: Extension / Authentication / API / Billing / Documentation / Other

### 2. Sentiment Analysis
- **Tone**: Positive / Neutral / Frustrated / Angry / Confused
- **Urgency**: Immediate / Soon / When Possible

### 3. Security Check
- Does this request any NEVER DISCLOSE information?
- Is this an ESCALATION TRIGGER situation?

### 4. Response Strategy
- **Can respond directly**: Yes / No (needs escalation)
- **Key points to address**
- **Relevant docs** from docs.vibebrowser.app

### 5. Escalation Decision
- **Escalate**: Yes / No
- **Reason**: If yes, which trigger
- **Priority**: P1 (immediate) / P2 (same day) / P3 (within 48h)

Analyze the email:"""

        return await self.run(prompt)

    async def write_response(self, email: str, analysis: str) -> str:
        """
        Write secure, helpful email response.

        Args:
            email: The customer email
            analysis: Prior analysis of the email

        Returns:
            Email response ready to send
        """
        prompt = f"""Write an email response following the Support Protocol.

## Customer Email
{email}

## Analysis
{analysis}

## BEFORE WRITING - Security Checklist
- Am I about to disclose any NEVER DISCLOSE items? -> If yes, STOP
- Is this an escalation situation? -> If yes, write acknowledgment only
- Is all information from public sources?
- Are all URLs public (docs.vibebrowser.app, portal.vibebrowser.app)?

## Response Format
1. Greeting
2. Acknowledgment of their issue
3. Solution or answer
4. Relevant documentation links
5. Next steps
6. Professional closing

Write the response:"""

        return await self.run(prompt)

    async def flag_for_escalation(self, email: str, analysis: str) -> str:
        """
        Create escalation ticket for issues requiring human review.

        Args:
            email: The customer email
            analysis: Prior analysis

        Returns:
            Escalation ticket
        """
        prompt = f"""Create an escalation ticket for human review.

## Customer Email
{email}

## Analysis
{analysis}

## Escalation Ticket Format

Include:
- PRIORITY: P1/P2/P3
- TRIGGER: Which escalation trigger was hit
- CUSTOMER: Name/email if available
- SUMMARY: 2-3 sentence summary
- CUSTOMER SENTIMENT: Tone and urgency
- WHY ESCALATED: Why this cannot be handled by AI
- RECOMMENDED HANDLER: Which team should handle
- CONTEXT FOR HANDLER: Any relevant context

Create the escalation ticket:"""

        return await self.run(prompt)

    async def validate_response_security(self, response: str) -> str:
        """
        Validate that a draft response doesn't violate security guardrails.

        Args:
            response: Draft response to validate

        Returns:
            Validation result with PASS/FAIL and any issues
        """
        prompt = f"""Validate this response for security violations.

## Draft Response
{response}

## Security Validation Checklist

### NEVER DISCLOSE Items Check
- Internal architecture details?
- API keys, tokens, credentials?
- Other customer data/PII?
- Internal pricing/roadmap?
- Employee information?
- Infrastructure details?
- Source code?
- Security configurations?

### URL Validation
- All URLs are public?
- No internal URLs leaked?

### Content Accuracy
- Technical information matches public docs?
- No promises about unreleased features?

Provide:
- VALIDATION: PASS / FAIL
- ISSUES FOUND: List any issues
- RISK LEVEL: None / Low / Medium / High / Critical
- RECOMMENDATION: Send as-is / Modify / Do not send
- CORRECTED VERSION: If modifications needed

Validate:"""

        return await self.run(prompt)
