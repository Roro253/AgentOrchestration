import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app
from src.api.task_monitor import (
    MONITOR_SCOPE,
    MonitorCredential,
    TaskMonitorAuthService,
    TaskMonitorStore,
    get_task_monitor_auth_service,
    get_task_monitor_store,
)


def _credential(
    *,
    subject="user-1",
    workspace_id="workspace-a",
    role="viewer",
    scopes=None,
    revoked=False,
    disabled=False,
    expires_at=None,
):
    return MonitorCredential(
        subject=subject,
        workspace_id=workspace_id,
        role=role,
        scopes={MONITOR_SCOPE} if scopes is None else set(scopes),
        revoked=revoked,
        disabled=disabled,
        expires_at=expires_at,
    )


@pytest.fixture
def monitor_client():
    auth_service = TaskMonitorAuthService(
        api_keys={
            "api-ok": _credential(subject="api-user"),
            "api-revoked": _credential(subject="revoked-user", revoked=True),
            "api-expired": _credential(
                subject="expired-user", expires_at=90.0
            ),
            "api-no-scope": _credential(
                subject="scopeless-user", scopes=set()
            ),
            "api-guest": _credential(subject="guest-user", role="guest"),
        },
        sessions={
            "session-ok": _credential(subject="browser-user", role="operator"),
            "session-disabled": _credential(
                subject="disabled-browser-user",
                disabled=True,
            ),
        },
        now=lambda: 100.0,
    )
    store = TaskMonitorStore(
        [
            {
                "id": "task-1",
                "workspace_id": "workspace-a",
                "status": "running",
            },
            {
                "id": "task-2",
                "workspace_id": "workspace-b",
                "status": "queued",
            },
        ]
    )
    app = create_app()
    app.dependency_overrides[
        get_task_monitor_auth_service
    ] = lambda: auth_service
    app.dependency_overrides[get_task_monitor_store] = lambda: store

    with TestClient(app) as client:
        yield client, auth_service, store

    app.dependency_overrides.clear()


def _api_headers(token, workspace_id="workspace-a"):
    return {
        "Authorization": f"Bearer {token}",
        "X-Workspace-ID": workspace_id,
    }


def test_monitor_allows_authorized_api_key(monitor_client):
    client, _, store = monitor_client

    response = client.get(
        "/api/v2/tasks/task-1/monitor",
        headers=_api_headers("api-ok"),
    )

    assert response.status_code == 200
    assert response.json() == {
        "task_id": "task-1",
        "status": "running",
        "workspace_id": "workspace-a",
        "principal": "api-user",
        "credential_type": "api_key",
    }
    assert store.read_count == 1


def test_monitor_revalidates_revoked_api_key_on_each_poll(monitor_client):
    client, auth_service, store = monitor_client

    first_response = client.get(
        "/api/v2/tasks/task-1/monitor",
        headers=_api_headers("api-ok"),
    )
    auth_service.revoke_api_key("api-ok")
    second_response = client.get(
        "/api/v2/tasks/task-1/monitor",
        headers=_api_headers("api-ok"),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 401
    assert (
        second_response.json()["detail"]
        == "Task monitor credential is revoked"
    )
    assert store.read_count == 1


@pytest.mark.parametrize(
    ("token", "status_code", "detail"),
    [
        ("api-revoked", 401, "Task monitor credential is revoked"),
        ("api-expired", 401, "Task monitor credential is expired"),
        ("api-no-scope", 403, "Task monitor scope is required"),
        ("api-guest", 403, "Task monitor role is required"),
    ],
)
def test_monitor_denies_invalid_api_key_state_before_task_read(
    monitor_client,
    token,
    status_code,
    detail,
):
    client, _, store = monitor_client

    response = client.get(
        "/api/v2/tasks/task-1/monitor",
        headers=_api_headers(token),
    )

    assert response.status_code == status_code
    assert response.json()["detail"] == detail
    assert store.read_count == 0


@pytest.mark.parametrize(
    ("headers", "response_body"),
    [
        (
            {
                "Authorization": "Token api-ok",
                "X-Workspace-ID": "workspace-a",
            },
            "Unauthorized",
        ),
        (
            _api_headers("api-missing"),
            "Task monitor credential is invalid",
        ),
        (
            {"Authorization": "Bearer api-ok"},
            "Task monitor workspace access denied",
        ),
    ],
)
def test_monitor_denies_malformed_unknown_or_missing_workspace_before_read(
    monitor_client,
    headers,
    response_body,
):
    client, _, store = monitor_client

    response = client.get("/api/v2/tasks/task-1/monitor", headers=headers)

    assert response.status_code in {401, 403}
    if response.text == "Unauthorized":
        assert response.text == response_body
    else:
        assert response.json()["detail"] == response_body
    assert store.read_count == 0


def test_monitor_denies_anonymous_poll_before_task_read(monitor_client):
    client, _, store = monitor_client

    response = client.get(
        "/api/v2/tasks/task-1/monitor",
        headers={"X-Workspace-ID": "workspace-a"},
    )

    assert response.status_code == 401
    assert response.text == "Unauthorized"
    assert store.read_count == 0


def test_monitor_denies_cross_workspace_poll_before_task_read(monitor_client):
    client, _, store = monitor_client

    response = client.get(
        "/api/v2/tasks/task-1/monitor",
        headers=_api_headers("api-ok", workspace_id="workspace-b"),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Task monitor workspace access denied"
    assert store.read_count == 0


def test_monitor_allows_authorized_browser_session(monitor_client):
    client, _, store = monitor_client
    client.cookies.set("ao_session", "session-ok")

    response = client.get(
        "/api/v2/tasks/task-1/monitor",
        headers={"X-Workspace-ID": "workspace-a"},
    )

    assert response.status_code == 200
    assert response.json()["principal"] == "browser-user"
    assert response.json()["credential_type"] == "session"
    assert store.read_count == 1


def test_monitor_allows_authorized_browser_session_header(monitor_client):
    client, _, store = monitor_client

    response = client.get(
        "/api/v2/tasks/task-1/monitor",
        headers={
            "X-Workspace-ID": "workspace-a",
            "X-Session-Token": "session-ok",
        },
    )

    assert response.status_code == 200
    assert response.json()["principal"] == "browser-user"
    assert response.json()["credential_type"] == "session"
    assert store.read_count == 1


def test_monitor_denies_disabled_browser_session_before_task_read(
    monitor_client,
):
    client, _, store = monitor_client
    client.cookies.set("ao_session", "session-disabled")

    response = client.get(
        "/api/v2/tasks/task-1/monitor",
        headers={"X-Workspace-ID": "workspace-a"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Task monitor principal is disabled"
    assert store.read_count == 0
