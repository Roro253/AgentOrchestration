from fastapi.testclient import TestClient

from src.api.approvals import (
    RUN_WAITING_FOR_HUMAN,
    ApprovalService,
    ApprovalStep,
    get_approval_service,
)
from src.api.server import create_app


def _client_with(service):
    app = create_app()
    app.dependency_overrides[get_approval_service] = lambda: service
    return TestClient(app)


def _headers(workspace="workspace-a", role="operator"):
    return {
        "Authorization": "Bearer test-token",
        "X-Workspace-ID": workspace,
        "X-Role": role,
    }


def test_approval_endpoint_approves_waiting_human_step():
    step = ApprovalStep(
        run_id="run-1",
        step_id="step-1",
        workspace_id="workspace-a",
        run_state=RUN_WAITING_FOR_HUMAN,
    )
    service = ApprovalService([step])
    client = _client_with(service)

    response = client.post(
        "/api/v2/runs/run-1/steps/step-1/approve",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "run_id": "run-1",
        "step_id": "step-1",
        "status": "approved",
    }
    assert step.approved is True
    assert service.protected_lookup_count == 1
    assert service.mutation_count == 1


def test_approval_endpoint_rejects_unauthorized_role_before_lookup():
    step = ApprovalStep(
        run_id="run-1",
        step_id="step-1",
        workspace_id="workspace-a",
    )
    service = ApprovalService([step])
    client = _client_with(service)

    response = client.post(
        "/api/v2/runs/run-1/steps/step-1/approve",
        headers=_headers(role="viewer"),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Approval access denied"
    assert step.approved is False
    assert service.protected_lookup_count == 0
    assert service.mutation_count == 0


def test_approval_endpoint_rejects_malformed_scope_before_lookup():
    step = ApprovalStep(
        run_id="run-1",
        step_id="step-1",
        workspace_id="workspace-a",
    )
    service = ApprovalService([step])
    client = _client_with(service)

    response = client.post(
        "/api/v2/runs/run-1/steps/step-1/approve",
        headers={"Authorization": "Bearer test-token", "X-Role": "operator"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid approval request"
    assert step.approved is False
    assert service.protected_lookup_count == 0
    assert service.mutation_count == 0


def test_approval_endpoint_checks_run_state_before_lookup_or_mutation():
    step = ApprovalStep(
        run_id="run-1",
        step_id="step-1",
        workspace_id="workspace-a",
        run_state="running",
    )
    service = ApprovalService([step])
    client = _client_with(service)

    response = client.post(
        "/api/v2/runs/run-1/steps/step-1/approve",
        headers=_headers(),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Run is not waiting for human approval"
    assert step.approved is False
    assert service.protected_lookup_count == 0
    assert service.mutation_count == 0
