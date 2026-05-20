from src.api.webhooks import (
    REDACTED,
    WebhookDeliveryService,
    WebhookEndpoint,
)


class TestWebhookDeliveryService:
    def setup_method(self):
        self.endpoint = WebhookEndpoint(
            id="endpoint-1",
            workspace_id="workspace-1",
            url="https://hooks.example.test/agent",
            secret="super-secret-value",
        )
        self.service = WebhookDeliveryService([self.endpoint])

    def test_valid_delivery_redacts_secrets_before_logs_and_callbacks(self):
        record = self.service.deliver(
            "workspace-1",
            "endpoint-1",
            "event-1",
            {
                "type": "agent.failed",
                "headers": {
                    "Authorization": "Bearer token-value",
                    "X-Request-Id": "req-1",
                },
                "payload": {
                    "api_token": "token-value",
                    "message": "failed",
                    "internal_trace_id": "trace-1",
                },
            },
            endpoint_version=1,
        )

        assert record.delivered
        assert record.status == "delivered"
        assert record.reason == "accepted"
        assert record.log_fields["payload"]["headers"]["Authorization"] == (
            REDACTED
        )
        assert record.callback_payload["payload"]["payload"]["api_token"] == (
            REDACTED
        )
        assert "internal_trace_id" not in (
            record.log_fields["payload"]["payload"]
        )
        assert "super-secret-value" not in repr(record.log_fields)
        assert "token-value" not in repr(record.callback_payload)

    def test_rejected_delivery_is_sanitized_and_not_persisted_as_delivered(
        self,
    ):
        record = self.service.deliver(
            "workspace-1",
            "missing-endpoint",
            "event-1",
            {
                "webhook_secret": "secret-value",
                "private_debug": "runtime-only",
            },
        )

        assert not record.delivered
        assert record.status == "rejected"
        assert record.reason == "endpoint_not_found"
        assert record.log_fields["payload"]["webhook_secret"] == REDACTED
        assert "private_debug" not in record.callback_payload["payload"]

    def test_retry_records_are_idempotent_and_sanitized(self):
        self.service.disable_endpoint("endpoint-1")
        first = self.service.deliver(
            "workspace-1",
            "endpoint-1",
            "event-1",
            {"token": "first-token"},
        )

        retry = self.service.retry(first, {"token": "second-token"})
        duplicate_retry = self.service.retry(first, {"token": "third-token"})

        assert retry is duplicate_retry
        assert retry.attempt == 2
        assert retry.reason == "endpoint_disabled"
        assert retry.log_fields["payload"]["token"] == REDACTED
        assert "second-token" not in repr(retry.callback_payload)
        assert "third-token" not in repr(duplicate_retry.log_fields)
        assert len(self.service.records()) == 2

    def test_disabled_endpoint_rejects_delivery(self):
        self.service.disable_endpoint("endpoint-1")

        record = self.service.deliver(
            "workspace-1",
            "endpoint-1",
            "event-disabled",
            {"message": "blocked"},
        )

        assert record.reason == "endpoint_disabled"
        assert not record.delivered

    def test_rotated_endpoint_rejects_stale_version_delivery(self):
        rotated = self.service.rotate_endpoint(
            "endpoint-1",
            "rotated-secret",
        )

        record = self.service.deliver(
            "workspace-1",
            "endpoint-1",
            "event-rotated",
            {"message": "blocked", "signature": "sig"},
            endpoint_version=rotated.version - 1,
        )

        assert record.reason == "endpoint_rotated"
        assert not record.delivered
        assert record.log_fields["payload"]["signature"] == REDACTED

    def test_workspace_isolation_blocks_cross_workspace_delivery(self):
        record = self.service.deliver(
            "workspace-2",
            "endpoint-1",
            "event-cross-workspace",
            {
                "message": "wrong workspace",
                "headers": {"Cookie": "session=abc"},
            },
        )

        assert not record.delivered
        assert record.reason == "workspace_mismatch"
        assert record.callback_payload["workspace_id"] == "workspace-2"
        assert record.callback_payload["endpoint_id"] == "endpoint-1"
        assert record.callback_payload["payload"]["headers"]["Cookie"] == (
            REDACTED
        )
