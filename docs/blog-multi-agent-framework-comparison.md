# Building an Autonomous AI Team: Comparing MetaGPT, AutoGen, CrewAI, and OpenHands

*How I evaluated four leading multi-agent frameworks to build a fully operational AI team that supports my SaaS product*

---

## The Dream: An AI Team I Can Delegate To

As a solo founder running a SaaS product, I found myself drowning in operational work. Support tickets piling up. Sentry errors going unnoticed. Feature requests lost in email threads. Release notes written at 2 AM. 

What if I could build an **autonomous AI team** that actually works like a real team? Not just individual AI assistants, but agents that:

- **Communicate with each other** to solve problems collaboratively
- **Delegate tasks** when they recognize another team member is better suited
- **Discuss in a group chat** where I can participate as the CEO
- **Have specialized knowledge** — each agent with their own tools, context, and expertise

I wanted to join a Slack channel, see my AI team discussing a customer issue, chime in with "let's prioritize the enterprise customer," and watch them execute.

This is the story of how I evaluated four major multi-agent frameworks to build exactly that.

---

## My Requirements

Before diving into frameworks, I defined what "operational AI team" means for my product:

### The Team Roster

| Role | Responsibilities | Key Integrations |
|------|------------------|------------------|
| **Product Manager** | Feature requests, roadmap, customer feedback analysis | GitHub Issues, Langfuse |
| **Software Engineer** | Code implementation, bug fixes, PR reviews | GitHub PRs, code repositories |
| **Release Engineer** | Sentry monitoring, deployments, release notes | Sentry, GitHub Releases |
| **Support Engineer** | Email triage, customer responses, escalations | Gmail, GitHub Issues |
| **Reliability Engineer** | Health checks, incident response, monitoring | Health endpoints, Sentry |
| **Marketer** | Announcements, social media, content | Twitter, LinkedIn |

### The Must-Have Capabilities

1. **Inter-Agent Communication**: When Support receives a bug report, they should be able to discuss with the Software Engineer directly, not through me.

2. **Task Delegation**: The Product Manager should be able to say "Engineer, please implement this feature" and have it actually happen.

3. **Slack Group Chat**: I want to see the team's discussions in Slack. I want to participate. When they're debating a technical decision, I should be able to jump in and provide direction.

4. **Role Differentiation**: Each agent needs different tools, knowledge bases, and context. The Release Engineer needs Sentry access; the Support Engineer needs Gmail.

5. **Scheduled Autonomous Work**: The Release Engineer should check Sentry every 5 minutes. The Support Engineer should monitor Gmail continuously. This isn't request-response — it's proactive work.

6. **GitHub as the Work Surface**: PRs, issues, and code reviews should happen in GitHub where my human collaborators also work.

---

## The Contenders

I evaluated four frameworks that represent different approaches to multi-agent systems:

| Framework | Backed By | Philosophy |
|-----------|-----------|------------|
| **MetaGPT** | DeepWisdom | "Code = SOP(Team)" — structured workflows |
| **AutoGen** | Microsoft | Conversational agents with group chat |
| **CrewAI** | CrewAI Inc | Role-playing agents with delegation |
| **OpenHands** | All Hands AI | Code-first agents with sandbox execution |

Let's break down each one.

---

## MetaGPT: The SOP-Driven Team

### The Concept

MetaGPT models software development as a **Standard Operating Procedure (SOP)**. It was published at ICLR 2024 and takes inspiration from how real software companies operate: requirements flow to architects, architects produce designs, engineers implement, QA tests.

### How Agents Communicate

MetaGPT uses a **publish-subscribe pattern** through a shared Environment:

```python
class ProductManager(Role):
    def __init__(self):
        self.set_actions([WritePRD])
        self._watch([UserRequirement])  # Subscribe to user requirements
        
class Engineer(Role):
    def __init__(self):
        self.set_actions([WriteCode])
        self._watch([WritePRD])  # Subscribe to PRD outputs

# When PM publishes a PRD, Engineer automatically receives it
```

The flow is elegant:
```
User Requirement → PM (publishes PRD) → Architect (publishes Design) → Engineer (publishes Code)
```

### What I Liked

- **Structured Pipelines**: If your work follows predictable patterns, MetaGPT excels. Software development PRD → Design → Code is well-modeled.
- **Environment as Shared Memory**: All agents can access the conversation history and outputs.
- **Role Customization**: Each Role has its own actions, LLM config, and watched message types.

### What Didn't Fit My Needs

- **No Real-Time Chat**: Communication is asynchronous and turn-based. There's no back-and-forth discussion — agents respond in rounds.
- **No Slack Integration**: I'd need to build a custom tool for Slack.
- **SOP-Oriented**: Great for pipelines, but I needed flexible, ad-hoc collaboration. What happens when Support needs to interrupt the Engineer about an urgent bug?

### The Verdict

MetaGPT is excellent for **structured, repeatable workflows** like "turn requirements into code." But my team needs to handle unpredictable situations — a customer escalation during a release, a Sentry alert while discussing features. The pub/sub model felt too rigid.

**Best for**: Teams with well-defined, sequential workflows.

---

## AutoGen: The Conversational Team

### The Concept

Microsoft's AutoGen is built around the idea that **agents should converse**. It provides GroupChat as a first-class primitive, with sophisticated speaker selection to determine who talks next.

### How Agents Communicate

AutoGen's GroupChat is the closest thing to what I wanted — agents sharing a conversation where everyone sees everything:

```python
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import HandoffTermination, TextMentionTermination

# Define agents with handoff capabilities
pm_agent = AssistantAgent(
    name="ProductManager",
    description="Handles feature requests and roadmap decisions",
    handoffs=["SoftwareEngineer", "user"],  # Can delegate to SWE or escalate to human
    system_message="You are the Product Manager..."
)

swe_agent = AssistantAgent(
    name="SoftwareEngineer", 
    description="Implements features and fixes bugs",
    handoffs=["ReleaseEngineer", "ProductManager"],
    tools=[github_tool, code_tool]
)

# Create a group chat with LLM-based speaker selection
team = SelectorGroupChat(
    [pm_agent, swe_agent, release_agent, support_agent],
    model_client=model_client,
    termination_condition=HandoffTermination(target="user") | TextMentionTermination("RESOLVED"),
    selector_prompt="""Select the next speaker based on the conversation context:
    - ProductManager: feature discussions, prioritization
    - SoftwareEngineer: implementation details, code questions
    - ReleaseEngineer: deployment, Sentry errors
    - SupportEngineer: customer issues, email responses
    """
)
```

### Speaker Selection Strategies

AutoGen offers multiple ways to decide who speaks next:

| Strategy | How It Works |
|----------|--------------|
| `round_robin` | Agents take turns in order |
| `random` | Random selection |
| `auto` | LLM decides based on agent descriptions |
| Custom function | Your logic determines the speaker |
| **Swarm handoffs** | Agents explicitly hand off to each other |

The Swarm pattern is particularly powerful for delegation:

```python
# Agent explicitly hands off to another agent
travel_agent = AssistantAgent(
    "TravelAgent",
    handoffs=["FlightsRefunder", "user"],
    system_message="Help with travel. Hand off to FlightsRefunder for refund requests."
)
```

### What I Liked

- **Native Group Chat**: This is exactly what I wanted. All agents share context.
- **Human-in-the-Loop**: `HandoffTermination(target="user")` pauses for human input.
- **Swarm Handoffs**: Agents can explicitly delegate, not just rely on the orchestrator.
- **Active Development**: Microsoft is heavily investing in AutoGen.

### What Didn't Fit My Needs

- **No Built-in Integrations**: No Slack, GitHub, Gmail, or Sentry connectors out of the box. I'd need to build custom tools.
- **Tool Ecosystem**: Less mature than CrewAI's 40+ built-in tools.

### The Verdict

AutoGen's GroupChat is **the best match for my Slack conversation requirement**. The Swarm handoff pattern handles delegation elegantly. But I'd need to build all the integrations myself.

**Best for**: Teams that need conversational collaboration with human participation.

---

## CrewAI: The Role-Playing Team

### The Concept

CrewAI leans heavily into the **role-playing** metaphor. Each agent has a role, goal, and backstory that shapes their behavior. It's also completely independent of LangChain — built from scratch for performance.

### How Agents Communicate

CrewAI uses two process types:

**Sequential**: Tasks execute in order, with outputs passed as context:

```python
from crewai import Agent, Crew, Task, Process

research_task = Task(
    description="Research the customer's issue",
    agent=support_agent,
    expected_output="Summary of the problem and potential solutions"
)

fix_task = Task(
    description="Implement the fix based on research",
    agent=swe_agent,
    context=[research_task]  # Receives output from research
)

crew = Crew(
    agents=[support_agent, swe_agent],
    tasks=[research_task, fix_task],
    process=Process.sequential
)
```

**Hierarchical**: A manager agent coordinates and delegates:

```python
manager = Agent(
    role="Engineering Manager",
    goal="Coordinate the team to resolve issues efficiently",
    allow_delegation=True
)

crew = Crew(
    agents=[manager, pm_agent, swe_agent, release_agent],
    tasks=[coordination_task],
    process=Process.hierarchical,
    manager_llm="gpt-4o"
)
```

### What I Liked

- **Rich Role Definition**: The role/goal/backstory pattern creates distinctive agent personalities.
- **Enterprise Integrations**: CrewAI AMP (their paid product) includes Slack, Gmail, HubSpot, Salesforce triggers.
- **Delegation Built-in**: `allow_delegation=True` lets agents hand off work.
- **40+ Built-in Tools**: File handling, web scraping, search, databases.
- **Flows**: Event-driven workflows with state management for complex orchestration.

```python
# CrewAI Flow for complex automation
from crewai.flow.flow import Flow, listen, start, router

class SupportFlow(Flow):
    @start()
    def receive_email(self):
        return gmail_tool.get_unread()
    
    @router(receive_email)
    def route_email(self):
        if "urgent" in self.state.email.subject.lower():
            return "escalate"
        return "standard"
    
    @listen("escalate")
    def handle_urgent(self):
        return escalation_crew.kickoff()
```

### What Didn't Fit My Needs

- **No Native Group Chat**: Communication is task-based, not conversational. Agents don't "discuss" — they execute tasks in sequence or through delegation.
- **Paid Integrations**: Slack and Gmail triggers require CrewAI AMP (enterprise pricing).
- **Manager Required for Hierarchy**: The hierarchical process needs a dedicated manager agent.

### The Verdict

CrewAI excels at **role-based task execution** with excellent enterprise integrations (if you pay). But it lacks the conversational group chat I wanted. Agents complete tasks; they don't discuss.

**Best for**: Teams needing structured task execution with enterprise integrations.

---

## OpenHands: The Code-First Team

### The Concept

OpenHands is built for **software engineering**. It achieves 77.6% on SWE-Bench, making it the strongest at actually writing and fixing code. The focus is on giving agents the ability to safely execute code in sandboxed environments.

### How Agents Communicate

Here's the honest truth: **OpenHands doesn't have native multi-agent communication**. 

The current architecture uses an orchestrator that routes tasks to individual agents:

```python
class VibeTeam:
    """Routes tasks to appropriate agents based on keywords."""
    
    async def run(self, task: str, agent_type: AgentType | None = None):
        # Route based on keywords or explicit selection
        selected_type = agent_type or self.route_task(task)
        agent = self._agents.get(selected_type)
        return await agent.run(task)
    
    def route_task(self, task: str) -> AgentType:
        # Keyword matching: "implement" → SWE, "release" → Release
        task_lower = task.lower()
        for agent_type, keywords in ROUTING_KEYWORDS.items():
            if any(kw in task_lower for kw in keywords):
                return agent_type
        return AgentType.SWE  # Default
```

Agents work independently. There's no shared conversation, no delegation, no group chat.

### What I Liked

- **Best Code Performance**: 77.6% on SWE-Bench means when the agent writes code, it works.
- **Sandboxed Execution**: Docker-based code execution prevents disasters.
- **Skills System**: Specialized prompts that activate based on keywords.
- **My Connectors Already Exist**: GitHub, Slack, Gmail, Sentry connectors are already built in my codebase.

### What Didn't Fit My Needs

- **No Inter-Agent Communication**: Agents are isolated. The Product Manager can't talk to the Engineer.
- **No Delegation**: The orchestrator decides everything; agents can't hand off to each other.
- **No Group Chat**: Sequential task execution only.

### The Verdict

OpenHands is **unmatched for code tasks**. If I need an agent to fix a bug, OpenHands will succeed where others fail. But it's not a team — it's a collection of specialists that can't collaborate.

**Best for**: Code-focused tasks requiring high accuracy.

---

## The Comparison Matrix

| Requirement | MetaGPT | AutoGen | CrewAI | OpenHands |
|-------------|---------|---------|--------|-----------|
| **Inter-Agent Communication** | Pub/Sub (async) | GroupChat (real-time) | Task context | None |
| **Task Delegation** | Action routing | Swarm handoffs | `allow_delegation` | Orchestrator only |
| **Group Chat** | Rounds-based | **Native support** | None | None |
| **Slack Integration** | Custom | Custom | **Enterprise (paid)** | Custom (exists) |
| **GitHub Integration** | Custom | Custom | Built-in | Custom (exists) |
| **Gmail Integration** | Built-in IMAP | Custom | **Enterprise (paid)** | Custom (exists) |
| **Human-in-the-Loop** | Supported | **Excellent** | Supported | Limited |
| **Code Execution Quality** | Good | Good | Good | **Best (77.6%)** |
| **Tool Ecosystem** | Medium | Growing | **40+ tools** | Custom |
| **Learning Curve** | Medium | Medium | Low | Medium |

---

## My Recommendation: The Hybrid Approach

After this evaluation, I realized no single framework does everything I need. The solution is a **hybrid architecture**:

```
┌─────────────────────────────────────────────────────────────────┐
│                         Slack Channel                           │
│                    #vibeteam-discussions                        │
└─────────────────────────────┬───────────────────────────────────┘
                              │ bidirectional
┌─────────────────────────────▼───────────────────────────────────┐
│                       Slack Bridge                              │
│    (streams AutoGen GroupChat ↔ Slack, handles @CEO mentions)  │
└─────────────────────────────┬───────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│                    AutoGen SelectorGroupChat                    │
│         (PM, SWE, Release, Support, SRE, Marketer)             │
│           Speaker selection + Swarm handoffs                    │
└───────┬─────────────┬─────────────┬─────────────┬───────────────┘
        │             │             │             │
   ┌────▼────┐   ┌────▼────┐   ┌────▼────┐   ┌────▼────┐
   │ GitHub  │   │ Sentry  │   │  Gmail  │   │ Health  │
   │  Tool   │   │  Tool   │   │  Tool   │   │  Tool   │
   └─────────┘   └─────────┘   └─────────┘   └─────────┘
        │             │             │             │
        └─────────────┴──────┬──────┴─────────────┘
                             │
              (For complex code tasks, delegate to)
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                    OpenHands Agent                              │
│          (SWE-Bench proven code execution)                      │
└─────────────────────────────────────────────────────────────────┘
```

### The Stack

| Layer | Technology | Why |
|-------|------------|-----|
| **Communication** | AutoGen GroupChat | Best native group chat with speaker selection |
| **Slack Bridge** | Custom | Stream conversations to Slack, handle CEO input |
| **Coordination** | AutoGen Swarm | Agents hand off to each other explicitly |
| **Code Execution** | OpenHands | When you need code that actually works |
| **Integrations** | Existing connectors | GitHub, Sentry, Gmail already built |

### Example Flow

1. **Support Engineer** receives a Gmail notification about a bug
2. In the GroupChat, Support says: "Customer reports login failing. Handing off to SWE."
3. **Software Engineer** investigates, finds the issue, says: "I'll fix this. Release, can you check Sentry for related errors?"
4. **Release Engineer** checks Sentry: "I see 47 occurrences in the last hour. This is P1."
5. **I (CEO)** see this in Slack, type: "@vibeteam prioritize this over the feature work"
6. **PM** acknowledges: "Understood. Pausing feature sprint. SWE, focus on the fix."
7. **SWE** creates a PR, tags Release for review
8. **Release** approves, deploys, confirms Sentry errors stopped

This is the team I wanted. Collaborative, autonomous, but with me in the loop.

---

## Getting Started

If you're building something similar, here's my advice:

### If You Need Conversational Collaboration
Start with **AutoGen**. The GroupChat + Swarm pattern handles most team dynamics elegantly.

```python
pip install autogen-agentchat autogen-ext
```

### If You Need Enterprise Integrations Now
Consider **CrewAI** with their AMP product. The Slack/Gmail/Salesforce triggers work out of the box.

```python
pip install crewai crewai-tools
```

### If Code Quality Matters Most
Use **OpenHands** for any code-writing tasks. The SWE-Bench results don't lie.

### If You Have Structured Workflows
**MetaGPT** excels when your process is predictable: requirement → design → implement → test.

---

## Conclusion

Building an autonomous AI team isn't about picking one framework — it's about understanding what each does well and composing them thoughtfully.

For my use case, AutoGen provides the conversational fabric, OpenHands provides code execution excellence, and my existing connectors provide the integration layer. The Slack bridge makes me a participant, not just an observer.

The dream of delegating to an AI team is closer than ever. The frameworks exist. The patterns are emerging. The question isn't whether it's possible — it's how you'll architect your team.

---

## Part 2: The Real Question — Agent Configuration vs. Communication

After publishing the first part of this analysis, I received a pointed question that changed my thinking:

> "But even if OpenHands is used, we have to preconfigure somehow an agent with different knowledge bases, different tool sets, etc."

This hit me. I had spent so much time comparing *communication protocols* that I missed the more fundamental question: **How do you configure agents with different roles?**

Let me break this down properly.

---

## The Two Dimensions of Multi-Agent Systems

Every multi-agent framework must solve two distinct problems:

| Dimension | Question | Examples |
|-----------|----------|----------|
| **Configuration** | How do agents differ from each other? | System prompts, tools, knowledge, permissions |
| **Communication** | How do agents talk to each other? | Pub/Sub, GroupChat, handoffs, shared memory |

The first comparison focused on communication. Now let's look at configuration.

---

## Agent Configuration: How Frameworks Differ

### 1. System Prompts (Knowledge & Personality)

Every agent needs a unique identity. Here's how each framework handles it:

**MetaGPT: Role + Actions**
```python
class ProductManager(Role):
    name: str = "Alice"
    profile: str = "Product Manager"
    goal: str = "efficiently create a successful product"
    constraints: str = "utilize the same language as the user requirements"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_actions([WritePRD, AnalyzeRequirement])
        self._watch([UserRequirement])  # React to these message types
```

**AutoGen: system_message + description**
```python
pm_agent = AssistantAgent(
    name="ProductManager",
    description="Handles feature requests and prioritization",  # Used for speaker selection
    system_message="""You are Curie, the Product Manager for VibeBrowser.

Your responsibilities:
1. Analyze customer feature requests
2. Write PRDs with clear acceptance criteria
3. Prioritize the backlog based on user value
4. Coordinate with engineering on feasibility

You have access to GitHub Issues and Langfuse for customer insights.""",
    model_client=model_client,
)
```

**CrewAI: Role + Goal + Backstory**
```python
pm_agent = Agent(
    role="Product Manager",
    goal="Define clear product requirements that deliver maximum user value",
    backstory="""You are Curie, a seasoned PM who worked at top SaaS companies. 
You believe in data-driven decisions and always advocate for the user.
You're known for writing crisp PRDs that engineers love.""",
    verbose=True,
    allow_delegation=True,
)
```

**OpenHands (our implementation): Embedded Protocols**
```python
class ProductManagerAgent(BaseVibeAgent):
    name = "Curie"
    profile = "Product Manager"
    goal = "Define clear product requirements and roadmap that deliver user value"
    
    # Specialized prompt with domain knowledge
    FEATURE_REQUEST_PROMPT = """
You are a Product Manager for VibeBrowser, an AI-powered browser automation extension.

## VibeBrowser Context
VibeBrowser is a Chrome extension that:
- Uses AI to understand natural language commands
- Automates browser tasks (clicking, typing, navigation)
- Integrates with external tools via MCP (Model Context Protocol)
...
"""
```

**Key Insight**: All frameworks support role differentiation through prompts. The difference is *structure* — MetaGPT uses classes, AutoGen uses strings, CrewAI adds backstory, OpenHands embeds domain protocols.

---

### 2. Tool Sets (Capabilities)

This is where agents truly differentiate. A PM needs GitHub Issues; an SRE needs Sentry.

**Current VibeTeam Configuration:**

| Agent | Tools | Why |
|-------|-------|-----|
| **ProductManager (Curie)** | `GitHubTool`, `LangfuseTool` | Creates issues, analyzes user feedback |
| **SoftwareEngineer (Turing)** | `GitHubTool` (PRs, code) | Implements features, reviews code |
| **ReleaseEngineer (Einstein)** | `GitHubTool`, `SentryTool`, `LangfuseTool`, `HealthCheckTool` | Monitors production, creates releases |
| **SupportEngineer (Darwin)** | `GitHubTool`, `GmailTool` | Handles customer emails, escalates issues |
| **ReliabilityEngineer (Newton)** | `HealthCheckTool`, `SentryTool` | Monitors uptime, responds to incidents |
| **Marketer (Ada)** | `GitHubTool` | Drafts announcements, release notes |

**How we implement this:**

```python
class ReleaseEngineerAgent(BaseVibeAgent):
    def __init__(self, **kwargs):
        tools: list[BaseTool] = []
        
        # Conditional tool loading based on available credentials
        if os.environ.get("GITHUB_TOKEN"):
            tools.append(GitHubTool())
            
        if os.environ.get("SENTRY_AUTH_TOKEN"):
            tools.append(SentryTool())
            
        if os.environ.get("LANGFUSE_PUBLIC_KEY"):
            tools.append(LangfuseTool())
        
        # Always available
        tools.append(HealthCheckTool())
        
        super().__init__(tools=tools, ...)
```

**Framework Comparison:**

| Framework | Tool Assignment | Dynamic Tools |
|-----------|----------------|---------------|
| **MetaGPT** | Actions per Role | Yes |
| **AutoGen** | `tools` parameter | Yes |
| **CrewAI** | `tools` list + `@tool` decorator | Yes, with 40+ built-in |
| **OpenHands** | Custom `BaseTool` classes | Yes |

---

### 3. Embedded Protocols (Behavioral Rules)

The most powerful configuration isn't just *what* agents can do — it's *how* they must behave.

**Example: The Torvalds Protocol** (embedded in our SoftwareEngineer):

```python
TORVALDS_PROTOCOL = """
## The Torvalds Protocol

You MUST follow this workflow for every task. No exceptions.

### 17-Phase Workflow
1. THINK - Understand the task, read related files
2. ISSUE - Create/find GitHub issue for tracking  
3. BRANCH - Create feature branch from master
4. IMPLEMENT - Write code and tests
5. COMMIT - Stage and commit with conventional format
6. PUSH - Push to remote
7. PR - Create pull request
8. REVIEW - Self-review the diff
9. REFLECT - Quality check
10. PR-CI - Wait for CI to pass
11. APPROVAL - Request user approval (NEVER merge without)
12. MERGE - Squash-merge after approval
13. MASTER-CI - Wait for master CI
14. DEPLOY - Verify deployments
15. HEALTH - Run health checks
16. CLOSE - Close issue
17. REPORT - Final status

### Critical Rules
- NEVER push directly to master
- NEVER merge with failing CI
- ALWAYS wait for user approval before merge
"""
```

**Example: Release Engineer Protocol** (noise classification):

```python
RELEASE_ENGINEER_PROTOCOL = """
### Issue Classification

**Valid Bug Patterns:**
- TypeError, ReferenceError, Cannot read property
- Unhandled Promise rejection
- High impact: >50 events or >10 users

**Noise Patterns (auto-resolve):**
- Failed to fetch, NetworkError, net::ERR_
- ResizeObserver loop, Script error
- AbortError, ECONNREFUSED
- Third-party extension errors

### Critical Rules
1. Every PR MUST reference a GitHub issue
2. Classify before acting - Don't create issues for noise
3. Quantify impact - Include event counts, user counts
"""
```

These protocols are **domain knowledge encoded as behavioral constraints**. They're what turn a generic LLM into a specialist.

---

## The Slack/GitHub Insight: You Don't Need a Special Protocol

Here's the realization that simplified everything:

> **If agents communicate through real external channels (Slack, GitHub), you don't need a special inter-agent protocol.**

Think about it:
- Agents post to Slack like humans do
- Agents comment on GitHub Issues like humans do
- Agents mention each other with @agent-name
- The CEO can see and participate in all discussions

**The external platform IS the communication layer.**

This means:
1. **Any framework works** — because Slack/GitHub handles routing
2. **Humans see everything** — no hidden agent-to-agent messages
3. **Natural interaction** — agents behave like remote team members
4. **Audit trail built-in** — Slack history = team discussion log

---

## The Revised Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Slack Channel: #ai-team                      │
│  - PM posts: "Analyzed customer request, priority P1"          │
│  - SWE responds: "@release can you check Sentry for this?"     │
│  - CEO sees everything, can @mention any agent                  │
└─────────────────────────────┬───────────────────────────────────┘
                              │ Slack Events API
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Slack Bot (Event Router)                     │
│  - Receives @mentions                                           │
│  - Routes to appropriate agent based on mention                 │
│  - Posts agent responses back to channel                        │
└─────────────────────────────┬───────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐     ┌───────────────┐     ┌───────────────┐
│ PM Agent      │     │ SWE Agent     │     │ Release Agent │
│ ─────────────│     │ ─────────────│     │ ─────────────│
│ Prompt: PM    │     │ Prompt: SWE   │     │ Prompt: Rel.  │
│ Protocol      │     │ + Torvalds    │     │ + Monitoring  │
│ ─────────────│     │ ─────────────│     │ ─────────────│
│ Tools:        │     │ Tools:        │     │ Tools:        │
│ - GitHub      │     │ - GitHub      │     │ - GitHub      │
│ - Langfuse    │     │ - Code        │     │ - Sentry      │
│ - Slack       │     │ - Slack       │     │ - Health      │
└───────────────┘     └───────────────┘     │ - Slack       │
                                            └───────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    GitHub Issues & PRs                          │
│  - Agents comment on issues                                     │
│  - PR reviews happen in GitHub                                  │
│  - Full history visible to humans                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implementing the Slack-Based Architecture

We've already built the `SlackConnector` following our existing patterns:

```python
from vibeteam.connectors.slack import SlackConnector

# Initialize
slack = SlackConnector()

# Agent posts to team channel
slack.post_message(
    channel="#ai-team",
    text=slack.format_agent_message(
        "Curie",
        "Analyzed customer request: Notion integration. Priority: P1"
    )
)

# Agent mentions another agent
slack.mention_agent(
    channel="#ai-team",
    agent_key="swe",
    message="Can you estimate effort for the Notion integration?"
)

# Check if message is for a specific agent
messages = slack.get_channel_history("#ai-team", limit=10)
for msg in messages:
    if slack.is_mention_for_agent(msg, "pm"):
        # Route to PM agent
        pass
```

### The Slack Tool (for agents to use)

```python
class SlackTool(BaseTool):
    """Tool for agents to communicate via Slack."""
    
    name = "slack"
    description = "Post messages to Slack channels and mention other agents"
    
    def get_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["post", "mention", "read"],
                            "description": "Action to perform"
                        },
                        "channel": {
                            "type": "string",
                            "description": "Channel name (e.g., #ai-team)"
                        },
                        "message": {
                            "type": "string",
                            "description": "Message to post"
                        },
                        "mention_agent": {
                            "type": "string",
                            "description": "Agent to mention (pm, swe, release, etc.)"
                        }
                    },
                    "required": ["action"]
                }
            }
        }
    
    async def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action")
        channel = kwargs.get("channel", "#ai-team")
        
        if action == "post":
            msg = self.connector.post_message(channel, kwargs["message"])
            return ToolResult(success=True, output=f"Posted to {channel}")
            
        elif action == "mention":
            msg = self.connector.mention_agent(
                channel,
                kwargs["mention_agent"],
                kwargs["message"]
            )
            return ToolResult(success=True, output=f"Mentioned @{kwargs['mention_agent']}")
            
        elif action == "read":
            messages = self.connector.get_channel_history(channel, limit=10)
            formatted = "\n".join(f"[{m.user}] {m.text}" for m in messages)
            return ToolResult(success=True, output=formatted)
```

---

## Framework Choice Revisited

Given this insight, here's my updated recommendation:

| If You Need... | Use This | Why |
|----------------|----------|-----|
| **Simple agent configuration** | OpenHands/LiteLLM | Lightweight, you control everything |
| **Conversational debugging** | AutoGen GroupChat | Great for development/testing |
| **Enterprise integrations** | CrewAI AMP | Slack triggers built-in (paid) |
| **Structured pipelines** | MetaGPT | Pub/Sub for predictable flows |

**For production with human-in-the-loop**: Use any framework + Slack/GitHub as the communication layer.

The framework matters less than you think. What matters is:
1. **Well-configured agents** with distinct prompts, tools, and protocols
2. **External communication channels** that humans can see and participate in
3. **Clear routing logic** to direct messages to the right agent

---

## User Guide: Talking to Your AI Team in Slack

Once deployed, here's how you interact with VibeTeam agents:

### The Bot: @VibeTeam

All agents run through a single Slack app called `@VibeTeam`. Mention it to start a conversation.

### Agent Keys & Personas

| Key | Name | Role | Keywords |
|-----|------|------|----------|
| `@swe` | Turing | Software Engineer | implement, code, bug, fix, pr, review |
| `@pm` | Curie | Product Manager | feature, requirement, roadmap, prd |
| `@release` | Einstein | Release Engineer | deploy, release, sentry, production |
| `@support` | Darwin | Support Engineer | customer, email, ticket, help |
| `@sre` | Newton | Reliability Engineer | health, monitor, incident, uptime |
| `@marketer` | Ada | Marketer | announce, social, twitter, content |

### Three Ways to Route Messages

**1. Explicit agent mention:**
```
You:      @VibeTeam @swe can you review PR #123?
VibeTeam: 🤖 **Turing (SWE):** I've reviewed PR #123. LGTM with one suggestion...
```

**2. Keyword-based routing:**
```
You:      @VibeTeam there's a bug in the login flow
VibeTeam: 🤖 **Turing (SWE):** I'll investigate the login bug...
```
(Routes to SWE because "bug" is a keyword)

**3. Default to PM:**
```
You:      @VibeTeam what should we build next quarter?
VibeTeam: 🤖 **Curie (PM):** Based on customer feedback, I recommend...
```
(No specific keywords, defaults to PM for general questions)

### Agent-to-Agent Communication

Agents can mention each other to hand off tasks:

```
VibeTeam: 🤖 **Turing (SWE):** Implementation complete. @pm can you verify requirements?
VibeTeam: 🤖 **Curie (PM):** Requirements verified. @release ready for deployment.
VibeTeam: 🤖 **Einstein (Release):** Deploying to staging now...
```

### Direct Messages

You can also DM the bot directly for private conversations with agents.

---

## Key Takeaways

1. **Configuration > Communication**: How you configure agents (prompts, tools, protocols) matters more than which communication protocol you use.

2. **Embedded Protocols Win**: The Torvalds Protocol and Release Engineer Protocol encode years of engineering wisdom. These behavioral constraints are what make agents reliable.

3. **Slack/GitHub = Communication Layer**: If agents communicate through channels humans already use, you get transparency, auditability, and human-in-the-loop for free.

4. **Framework Lock-in is Minimal**: The core value is in your prompts, tools, and protocols — not the framework. You can swap AutoGen for OpenHands without losing your agent configurations.

5. **Start Simple**: Don't over-engineer. One agent per role, Slack for communication, GitHub for work. Add complexity only when needed.

---

*What's your experience with multi-agent frameworks? I'd love to hear about your architecture choices. Find me on Twitter [@vibefounder](https://twitter.com/vibefounder) or open an issue on [VibeTeam](https://github.com/VibeTechnologies/VibeTeam).*

---

## Appendix: Quick Reference

### Framework Installation

```bash
# MetaGPT
pip install metagpt

# AutoGen
pip install autogen-agentchat autogen-ext

# CrewAI
pip install crewai crewai-tools

# OpenHands
pip install openhands-ai
```

### Key Documentation

- **MetaGPT**: https://docs.deepwisdom.ai
- **AutoGen**: https://microsoft.github.io/autogen/
- **CrewAI**: https://docs.crewai.com
- **OpenHands**: https://docs.openhands.dev

### GitHub Repositories

- **MetaGPT**: https://github.com/FoundationAgents/MetaGPT (63.5k+ stars)
- **AutoGen**: https://github.com/microsoft/autogen (53.9k+ stars)
- **CrewAI**: https://github.com/crewAIInc/crewAI (43.2k+ stars)
- **OpenHands**: https://github.com/OpenHands/OpenHands (67.1k+ stars)
