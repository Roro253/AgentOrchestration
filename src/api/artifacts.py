"""Artifact download lookup service."""

from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional, Tuple


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    project_id: str
    workspace_id: str
    content: bytes
    filename: str = "artifact.bin"
    allowed_roles: Tuple[str, ...] = field(
        default_factory=lambda: ("viewer", "operator", "admin")
    )


class ArtifactDownloadService:
    """Workspace-scoped artifact store used by the download API."""

    def __init__(self, records: Optional[Iterable[ArtifactRecord]] = None):
        self._records: Dict[Tuple[str, str, str], ArtifactRecord] = {}
        self._workspace_index = set()
        self.protected_lookup_count = 0
        for record in records or ():
            self.add(record)

    def add(self, record: ArtifactRecord) -> None:
        key = (record.workspace_id, record.project_id, record.artifact_id)
        self._records[key] = record
        self._workspace_index.add(key)

    def download(
        self,
        artifact_id: str,
        project_id: str,
        workspace_id: str,
        role: str,
    ) -> ArtifactRecord:
        key = (workspace_id, project_id, artifact_id)
        if key not in self._workspace_index:
            raise ArtifactNotFound

        self.protected_lookup_count += 1
        record = self._records[key]
        if role not in record.allowed_roles:
            raise ArtifactForbidden
        return record


class ArtifactNotFound(Exception):
    pass


class ArtifactForbidden(Exception):
    pass


artifact_service = ArtifactDownloadService()


def get_artifact_service() -> ArtifactDownloadService:
    return artifact_service
