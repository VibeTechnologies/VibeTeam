Pure logic/unit-ish: mention parsing and task extraction helpers (low cost, high confidence). Example targets in run_slack_framework_agent.py for is_mention_for_agent() and extract_task_from_mention(). Similar extraction behavior appears in run_slack_agent.py and run_discord_agent.py.
Connector interaction smoke tests (mocked): validate that polling loops post replies and skip bot messages by stubbing connector classes. Focus on behavior around processed_ts / processed_ids and thread replies in run_slack_agent.py and run_discord_agent.py.
Routing/role handoff integration (mocked Router + fake connectors): for the multi-session bots to ensure routing calls and role fan-out work. See run_slack_bot.py and run_discord_bot.py.
DB migration integration (ephemeral DB): verify --check behavior and that tables/indexes are created. This is isolated and valuable. See migrate_db.py.
Sentry triage logic unit tests (pure functions): pattern matching for valid/invalid issues, severity classification, and processed issue bookkeeping. This is deterministic and worth it. See triage_sentry.py.
Infra docs builder unit tests: filter/exclude logic, relevance scoring, and “always include” list handling. All pure file processing. See build_infra_docs.py.
Email pipeline logic tests: _is_docs_portal_escalation(), _extract_ticket_info(), and escalation triggers based on body content are good to cover. See process_emails.py.
E2E “happy path” (manual or nightly): the Slack evaluator already serves as a real end-to-end flow with external dependencies. It’s inherently flaky but valuable for scheduled runs. See eval_slack_e2e.py.
E2E feature request flow (manual): this script is already a true integration path (LLM + GitHub). Good as a manual smoke test. See test_e2e_feature_request.py.
Tests that are probably not worth it

Full daemon loops with real Slack/Discord: high flake rate and slow. Mocked connector tests are the better tradeoff. Applies to run_slack_agent.py, run_discord_agent.py, run_slack_bot.py, run_discord_bot.py.
Signal handling and logging output: low value and brittle to assert. Applies across the run_* scripts.
DeepEval scoring correctness: that’s third-party behavior; unit tests won’t add confidence. Use the script as an integration check instead. See eval_slack_e2e.py.
Real Gmail/Sentry/GitHub network tests in CI: too flaky and expensive; keep those as local/manual or opt-in integration runs. Applies to process_emails.py and triage_sentry.py.