# LinkedIn Post: Agent Evaluation Framework Question

---

**Building a multi-agent orchestration system. Need advice on evaluation.**

I'm building **VibeTeam** — a system that routes tasks to AI agents running on different frameworks:
- **AutoGen** (Microsoft)
- **CrewAI**
- **OpenHands** (formerly OpenDevin)

Same task, same tools, different frameworks. Example: "Summarize Sentry issues this week."

**The problem:** How do I objectively evaluate which framework produces better responses?

Current approach: **LLM-as-judge** using GPT-5 to score responses 0-5 on accuracy, completeness, and usefulness.

But I'm wondering if I should use a proper eval framework instead:
- **DeepEval** — seems comprehensive, has hallucination detection
- **Ragas** — good for RAG, not sure about agents
- **LangSmith** — tight LangChain integration
- **Braintrust** — heard good things
- **Custom prompts** — what I'm doing now

**Questions for the community:**

1. For comparing multi-agent outputs on the same task, which eval framework works best?
2. Is LLM-as-judge sufficient, or do you combine it with deterministic metrics?
3. Any gotchas when evaluating agent responses (vs. simple LLM outputs)?

Stack: Python, Azure OpenAI, Kubernetes, httpx

Happy to share the benchmark code if useful.

---

*Tags: #AI #Agents #LLM #Evaluation #AutoGen #CrewAI #OpenHands #MLOps*
