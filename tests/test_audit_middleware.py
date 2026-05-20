import asyncio
import logging

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest

from src.api.middleware import (
    AUDIT_ACTOR_HEADER,
    AUDIT_STATUS_HEADER,
    AuditMiddleware,
    AuthMiddleware,
    get_current_audit_actor,
)


def add_auth_audit_middleware(app: FastAPI) -> None:
    app.add_middleware(AuditMiddleware)
    app.add_middleware(AuthMiddleware)


def test_authenticated_request_attaches_sanitized_audit_actor(caplog):
    app = FastAPI()
    add_auth_audit_middleware(app)

    @app.get("/api/v2/agents")
    async def read_agents(request: Request):
        return {
            "actor": request.state.audit_actor,
            "authenticated": request.state.audit_authenticated,
        }

    client = TestClient(app)
    with caplog.at_level(logging.INFO, logger="src.api.middleware"):
        response = client.get(
            "/api/v2/agents?token=must-not-log",
            headers={
                "Authorization": "Bearer raw-secret-token",
                "X-Audit-Actor": "user-123",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "actor": "user-123",
        "authenticated": True,
    }
    assert response.headers[AUDIT_ACTOR_HEADER] == "user-123"
    assert response.headers[AUDIT_STATUS_HEADER] == "authenticated"
    assert "raw-secret-token" not in caplog.text
    assert "must-not-log" not in caplog.text
    assert get_current_audit_actor() is None


def test_token_actor_fallback_is_stable_and_non_secret():
    app = FastAPI()
    add_auth_audit_middleware(app)

    @app.get("/api/v2/audit-context")
    async def read_context(request: Request):
        return {
            "actor": request.state.audit_actor,
            "context_actor": get_current_audit_actor(),
        }

    client = TestClient(app)
    headers = {"Authorization": "Bearer raw-secret-token"}

    first = client.get("/api/v2/audit-context", headers=headers)
    second = client.get("/api/v2/audit-context", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    actor = first.json()["actor"]
    assert actor == second.json()["actor"]
    assert first.json()["context_actor"] == actor
    assert actor.startswith("token:")
    assert "raw-secret-token" not in actor
    assert first.headers[AUDIT_ACTOR_HEADER] == actor
    assert get_current_audit_actor() is None


def test_token_route_remains_public_without_audit_actor():
    app = FastAPI()
    add_auth_audit_middleware(app)

    @app.post("/api/v2/auth/token")
    async def issue_token(request: Request):
        return {
            "has_actor": hasattr(request.state, "audit_actor"),
            "context_actor": get_current_audit_actor(),
        }

    client = TestClient(app)
    response = client.post(
        "/api/v2/auth/token",
        headers={"X-Audit-Actor": "user-123"},
    )

    assert response.status_code == 200
    assert response.headers[AUDIT_STATUS_HEADER] == "public"
    assert AUDIT_ACTOR_HEADER not in response.headers
    assert response.json() == {
        "has_actor": False,
        "context_actor": None,
    }
    assert get_current_audit_actor() is None


def test_rejected_request_does_not_attach_audit_actor():
    app = FastAPI()
    add_auth_audit_middleware(app)
    called = {"handler": False}

    @app.get("/api/v2/agents")
    async def read_agents(request: Request):
        called["handler"] = True
        return {"actor": request.state.audit_actor}

    client = TestClient(app)
    response = client.get("/api/v2/agents")

    assert response.status_code == 401
    assert response.headers[AUDIT_STATUS_HEADER] == "rejected"
    assert AUDIT_ACTOR_HEADER not in response.headers
    assert not called["handler"]


def test_invalid_actor_fails_closed_before_handler():
    app = FastAPI()
    add_auth_audit_middleware(app)
    called = {"handler": False}

    @app.post("/api/v2/agents")
    async def create_agent(request: Request):
        called["handler"] = True
        return {"actor": request.state.audit_actor}

    client = TestClient(app)
    response = client.post(
        "/api/v2/agents",
        headers={
            "Authorization": "Bearer raw-secret-token",
            "X-Audit-Actor": "bad actor with spaces",
        },
    )

    assert response.status_code == 400
    assert response.headers[AUDIT_STATUS_HEADER] == "rejected"
    assert AUDIT_ACTOR_HEADER not in response.headers
    assert "raw-secret-token" not in response.text
    assert not called["handler"]


def test_exception_path_clears_request_local_audit_state(caplog):
    async def run_exception_path():
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v2/fail",
            "headers": [
                (b"authorization", b"Bearer exception-secret-token"),
                (b"x-audit-actor", b"user-123"),
            ],
            "query_string": b"secret=must-not-log",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 5000),
        }
        request = StarletteRequest(scope)
        request.state.authenticated_actor = "user-123"
        middleware = AuditMiddleware(app=lambda scope, receive, send: None)

        async def call_next(request):
            assert request.state.audit_actor == "user-123"
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await middleware.dispatch(request, call_next)

        assert getattr(request.state, "audit_actor", None) is None
        assert getattr(request.state, "audit_authenticated", None) is None

    with caplog.at_level(logging.INFO, logger="src.api.middleware"):
        asyncio.run(run_exception_path())

    assert "exception-secret-token" not in caplog.text
    assert "must-not-log" not in caplog.text
    assert any(
        getattr(record, "audit_actor", None) == "user-123"
        for record in caplog.records
    )


def test_audit_middleware_fails_closed_without_auth_state():
    app = FastAPI()
    app.add_middleware(AuditMiddleware)
    called = {"handler": False}

    @app.get("/api/v2/agents")
    async def read_agents():
        called["handler"] = True
        return {"status": "should-not-run"}

    client = TestClient(app)
    response = client.get(
        "/api/v2/agents",
        headers={"Authorization": "Bearer raw-secret-token"},
    )

    assert response.status_code == 401
    assert response.headers[AUDIT_STATUS_HEADER] == "rejected"
    assert AUDIT_ACTOR_HEADER not in response.headers
    assert not called["handler"]
    assert get_current_audit_actor() is None
