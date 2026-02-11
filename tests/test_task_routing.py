"""
Tests for gateway task template routing logic.

Verifies that the correct task template (deployment, notification, investigation)
is selected based on message content and target role.
"""

from __future__ import annotations

from vibeteam.gateway.routes.slack import classify_task_template


class TestDeploymentDetection:
    """Test that deployment requests are correctly routed to deployment template."""

    def test_deploy_to_staging(self):
        result = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer we need to deploy the latest changes to staging.",
        )
        assert result == "deployment"

    def test_deploy_pr_merged(self):
        result = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer PR #123 has been merged. Please deploy to production.",
        )
        assert result == "deployment"

    def test_release_new_version(self):
        result = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer please release v2.3.0 to staging.",
        )
        assert result == "deployment"

    def test_ship_it(self):
        result = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer ship it to production.",
        )
        assert result == "deployment"

    def test_push_to_staging(self):
        result = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer push to staging environment.",
        )
        assert result == "deployment"

    def test_promote_to_prod(self):
        result = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer promote the staging build to production.",
        )
        assert result == "deployment"

    def test_deploy_and_notify(self):
        """Deploy + notify should still be deployment (deploy takes priority)."""
        result = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer deploy to staging and notify the team when done.",
        )
        assert result == "deployment"


class TestDeploymentNotTriggeredForOtherRoles:
    """Deployment template should only trigger for release_engineer role."""

    def test_swe_deploy_message(self):
        """SoftwareEngineer shouldn't get deployment template even with deploy keywords."""
        result = classify_task_template(
            "software_engineer",
            "@SoftwareEngineer we need to deploy the latest changes.",
        )
        assert result == "investigation"

    def test_support_deploy_message(self):
        result = classify_task_template(
            "support_engineer",
            "@SupportEngineer customer is asking about the deployment.",
        )
        assert result == "investigation"

    def test_pm_release_message(self):
        result = classify_task_template(
            "product_manager",
            "@ProductManager when is the next release?",
        )
        assert result == "investigation"


class TestDeploymentExcludedByInvestigationKeywords:
    """Deploy + investigation keywords should fall back to investigation."""

    def test_deploy_failed(self):
        """'deploy' + 'fail' -> investigation, not deployment."""
        result = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer the deploy failed, please investigate.",
        )
        assert result == "investigation"

    def test_deploy_error(self):
        result = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer there's an error after the last deploy.",
        )
        assert result == "investigation"

    def test_deploy_broken(self):
        result = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer deployment is broken, everything is down.",
        )
        assert result == "investigation"

    def test_deploy_investigate(self):
        result = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer investigate why the last deploy caused issues.",
        )
        assert result == "investigation"

    def test_deploy_check_why(self):
        result = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer check why the last deployment broke the API.",
        )
        assert result == "investigation"


class TestNotificationDetection:
    """Test that notification requests are correctly detected."""

    def test_notify_team(self):
        result = classify_task_template(
            "support_engineer",
            "@SupportEngineer notify the customer that the fix is deployed.",
        )
        assert result == "notification"

    def test_announce(self):
        result = classify_task_template(
            "marketing_manager",
            "@MarketingManager announce the new release to customers.",
        )
        assert result == "notification"

    def test_tell_the_team(self):
        result = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer tell the team the maintenance window is over.",
        )
        assert result == "notification"

    def test_confirm_to_customer(self):
        result = classify_task_template(
            "support_engineer",
            "@SupportEngineer confirm to the customer that issue is resolved.",
        )
        assert result == "notification"


class TestNotificationExcludedByInvestigation:
    """Notification + investigation keywords -> investigation."""

    def test_notify_but_error(self):
        result = classify_task_template(
            "support_engineer",
            "@SupportEngineer notify the customer about the error we found.",
        )
        assert result == "investigation"

    def test_announce_but_investigate(self):
        result = classify_task_template(
            "marketing_manager",
            "@MarketingManager investigate and then announce the fix.",
        )
        assert result == "investigation"


class TestInvestigationFallback:
    """Messages without deployment or notification keywords → investigation."""

    def test_support_400_errors(self):
        result = classify_task_template(
            "support_engineer",
            "@SupportEngineer customers are seeing 400 errors on the API.",
        )
        assert result == "investigation"

    def test_github_issue(self):
        result = classify_task_template(
            "software_engineer",
            "@SoftwareEngineer issue #449 reports browser extension crashes.",
        )
        assert result == "investigation"

    def test_sentry_alert(self):
        result = classify_task_template(
            "support_engineer",
            "@SupportEngineer Sentry is showing new errors in production.",
        )
        assert result == "investigation"

    def test_generic_help(self):
        result = classify_task_template(
            "software_engineer",
            "@SoftwareEngineer can you help with this?",
        )
        assert result == "investigation"


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_message(self):
        result = classify_task_template("release_engineer", "")
        assert result == "investigation"

    def test_deploy_keyword_in_different_case(self):
        result = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer DEPLOY TO STAGING NOW!",
        )
        assert result == "deployment"

    def test_release_engineer_with_mixed_keywords(self):
        """Deploy + notify + no investigation = deployment (deploy takes priority for RE)."""
        result = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer deploy to staging and notify the team.",
        )
        assert result == "deployment"

    def test_non_release_engineer_notify_with_deploy_word(self):
        """SupportEngineer with 'deploy' + 'notify' = notification (not deployment)."""
        result = classify_task_template(
            "support_engineer",
            "@SupportEngineer notify customer the deploy is complete.",
        )
        assert result == "notification"

    def test_release_in_role_mention_not_false_positive(self):
        """'release' inside '@ReleaseEngineer' should NOT trigger deployment."""
        result = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer tell the team the maintenance window is over.",
        )
        assert result == "notification"

    def test_release_as_standalone_word_triggers_deployment(self):
        """'release' as standalone word SHOULD trigger deployment."""
        result = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer please release the new version to staging.",
        )
        assert result == "deployment"


class TestHandoffPassthrough:
    """Handoff messages are forwarded as-is — the gateway doesn't add special templates.

    Per design.md, the gateway is a message router. Handoff intelligence belongs
    in the agent's system prompt (AGENTS.md / agent_service), not the gateway.
    """

    def test_handoff_message_gets_investigation_template(self):
        """Handoff messages go through the normal investigation template."""
        result = classify_task_template(
            "software_engineer",
            "[Handoff from SupportEngineer]\n\nOriginal request: ...\n\nPrevious response: ...",
        )
        assert result == "investigation"

    def test_handoff_with_deploy_keywords_for_release_engineer(self):
        """Handoff to ReleaseEngineer with deploy keywords gets deployment template."""
        result = classify_task_template(
            "release_engineer",
            "[Handoff from SupportEngineer]\n\nOriginal request: deploy to staging...",
        )
        assert result == "deployment"
