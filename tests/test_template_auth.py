import time

from fastapi.testclient import TestClient

from src.api.auth import Principal, session_store, template_authorization
from src.api.server import create_app
from src.api.templates import template_service


class TestTemplateCloneAuthorization:
    def setup_method(self):
        session_store._principals.clear()
        session_store._invalidated.clear()
        template_authorization._audit_records.clear()
        template_service._clones.clear()
        template_service.template_reads = 0
        template_service.clone_writes = 0
        self.client = TestClient(create_app())

    def register_principal(
        self,
        token,
        *,
        scopes=None,
        roles=None,
        expires_delta=300,
        revoked=False,
        disabled=False,
        client_type="token",
    ):
        session_store.register(
            token,
            Principal(
                subject="user-1",
                scopes=scopes or ["templates:clone"],
                workspace_roles=roles or {"workspace-1": "editor"},
                expires_at=time.time() + expires_delta,
                revoked=revoked,
                disabled=disabled,
                client_type=client_type,
            ),
        )

    def clone(self, token=None, headers=None):
        request_headers = headers or {}
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        return self.client.post(
            "/api/v2/templates/support-agent/clone",
            json={"workspace_id": "workspace-1", "name": "support-copy"},
            headers=request_headers,
        )

    def test_anonymous_template_clone_is_denied_before_template_read(self):
        response = self.clone()

        assert response.status_code == 401
        assert template_service.template_reads == 0
        assert template_service.clone_writes == 0

    def test_malformed_browser_session_is_denied_before_template_read(self):
        response = self.clone(headers={"X-Integration-Session": "bad-session"})

        assert response.status_code == 401
        assert response.json()["detail"] == "malformed"
        assert template_service.template_reads == 0
        assert template_service.clone_writes == 0

    def test_stale_token_is_denied_and_invalidated(self):
        self.register_principal("expired-token", expires_delta=-1)

        response = self.clone("expired-token")

        assert response.status_code == 401
        assert response.json()["detail"] == "stale"
        assert session_store.get("expired-token") is None
        assert template_service.template_reads == 0
        assert template_service.clone_writes == 0

    def test_revoked_token_is_denied_and_invalidated(self):
        self.register_principal("revoked-token", revoked=True)

        response = self.clone("revoked-token")

        assert response.status_code == 401
        assert response.json()["detail"] == "revoked"
        assert session_store.get("revoked-token") is None
        assert template_service.template_reads == 0
        assert template_service.clone_writes == 0

    def test_disabled_principal_is_denied_and_invalidated(self):
        self.register_principal("disabled-token", disabled=True)

        response = self.clone("disabled-token")

        assert response.status_code == 401
        assert response.json()["detail"] == "disabled"
        assert session_store.get("disabled-token") is None
        assert template_service.template_reads == 0
        assert template_service.clone_writes == 0

    def test_insufficient_scope_is_denied_before_template_read(self):
        self.register_principal("scope-token", scopes=["templates:read"])

        response = self.clone("scope-token")

        assert response.status_code == 403
        assert response.json()["detail"] == "insufficient_scope"
        assert template_service.template_reads == 0
        assert template_service.clone_writes == 0

    def test_insufficient_workspace_role_is_denied_before_template_read(self):
        self.register_principal("role-token", roles={"workspace-1": "viewer"})

        response = self.clone("role-token")

        assert response.status_code == 403
        assert response.json()["detail"] == "insufficient_role"
        assert template_service.template_reads == 0
        assert template_service.clone_writes == 0

    def test_wrong_workspace_role_is_denied_before_template_read(self):
        self.register_principal(
            "wrong-workspace-token",
            roles={"workspace-2": "admin"},
        )

        response = self.clone("wrong-workspace-token")
        records = template_authorization.audit_records()

        assert response.status_code == 403
        assert response.json()["detail"] == "insufficient_role"
        assert records[-1]["workspace_id"] == "workspace-1"
        assert template_service.template_reads == 0
        assert template_service.clone_writes == 0

    def test_authorized_token_client_can_clone_template(self):
        self.register_principal("good-token")

        response = self.clone("good-token")

        assert response.status_code == 200
        body = response.json()
        assert body["clone"]["workspace_id"] == "workspace-1"
        assert body["clone"]["created_by"] == "user-1"
        assert template_service.template_reads == 1
        assert template_service.clone_writes == 1

    def test_authorized_browser_session_can_clone_template(self):
        self.register_principal("sess_browser", client_type="browser")

        response = self.clone(
            headers={"X-Integration-Session": "sess_browser"},
        )

        assert response.status_code == 200
        assert response.json()["clone"]["name"] == "support-copy"
        assert template_service.template_reads == 1
        assert template_service.clone_writes == 1

    def test_denial_audit_records_do_not_include_secret_tokens(self):
        self.register_principal("secret-token", revoked=True)

        response = self.clone("secret-token")
        records = template_authorization.audit_records()

        assert response.status_code == 401
        assert records[-1]["event"] == "template_clone_denied"
        assert records[-1]["reason"] == "revoked"
        assert "secret-token" not in str(records)
