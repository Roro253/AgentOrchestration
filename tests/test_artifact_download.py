from fastapi.testclient import TestClient

from src.api.artifacts import (
    ArtifactDownloadService,
    ArtifactRecord,
    get_artifact_service,
)
from src.api.server import create_app


def _client_with(service):
    app = create_app()
    app.dependency_overrides[get_artifact_service] = lambda: service
    return TestClient(app)


def _headers(workspace="workspace-a", role="viewer"):
    return {
        "Authorization": "Bearer test-token",
        "X-Workspace-ID": workspace,
        "X-Role": role,
    }


def test_artifact_download_returns_content_for_authorized_workspace_and_role():
    service = ArtifactDownloadService(
        [
            ArtifactRecord(
                artifact_id="artifact-1",
                project_id="project-1",
                workspace_id="workspace-a",
                filename="report.txt",
                content=b"downloadable report",
            )
        ]
    )
    client = _client_with(service)

    response = client.get(
        "/api/v2/projects/project-1/artifacts/artifact-1/download",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.content == b"downloadable report"
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="report.txt"'
    )
    assert service.protected_lookup_count == 1


def test_artifact_download_returns_404_for_cross_workspace_lookup():
    service = ArtifactDownloadService(
        [
            ArtifactRecord(
                artifact_id="artifact-1",
                project_id="project-1",
                workspace_id="workspace-a",
                content=b"secret report",
            )
        ]
    )
    client = _client_with(service)

    response = client.get(
        "/api/v2/projects/project-1/artifacts/artifact-1/download",
        headers=_headers(workspace="workspace-b"),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Artifact not found"
    assert service.protected_lookup_count == 0


def test_artifact_download_returns_404_for_cross_project_lookup():
    service = ArtifactDownloadService(
        [
            ArtifactRecord(
                artifact_id="artifact-1",
                project_id="project-1",
                workspace_id="workspace-a",
                content=b"project 1 secret report",
            )
        ]
    )
    client = _client_with(service)

    response = client.get(
        "/api/v2/projects/project-2/artifacts/artifact-1/download",
        headers=_headers(),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Artifact not found"
    assert service.protected_lookup_count == 0


def test_artifact_download_rejects_missing_auth_before_lookup():
    service = ArtifactDownloadService(
        [
            ArtifactRecord(
                artifact_id="artifact-1",
                project_id="project-1",
                workspace_id="workspace-a",
                content=b"secret report",
            )
        ]
    )
    client = _client_with(service)

    response = client.get(
        "/api/v2/projects/project-1/artifacts/artifact-1/download",
        headers={"X-Workspace-ID": "workspace-a", "X-Role": "viewer"},
    )

    assert response.status_code == 401
    assert response.text == "Unauthorized"
    assert service.protected_lookup_count == 0


def test_artifact_download_rejects_malformed_scope_before_lookup():
    service = ArtifactDownloadService(
        [
            ArtifactRecord(
                artifact_id="artifact-1",
                project_id="project-1",
                workspace_id="workspace-a",
                content=b"secret report",
            )
        ]
    )
    client = _client_with(service)

    response = client.get(
        "/api/v2/projects/project-1/artifacts/artifact-1/download",
        headers={"Authorization": "Bearer test-token", "X-Role": "viewer"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid artifact download scope"
    assert service.protected_lookup_count == 0


def test_artifact_download_rejects_role_without_returning_success():
    service = ArtifactDownloadService(
        [
            ArtifactRecord(
                artifact_id="artifact-1",
                project_id="project-1",
                workspace_id="workspace-a",
                allowed_roles=("admin",),
                content=b"admin report",
            )
        ]
    )
    client = _client_with(service)

    response = client.get(
        "/api/v2/projects/project-1/artifacts/artifact-1/download",
        headers=_headers(role="viewer"),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Artifact access denied"
    assert service.protected_lookup_count == 1
