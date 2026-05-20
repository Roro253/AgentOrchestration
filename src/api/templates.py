"""Agent template cloning service."""

import time
from typing import Dict, Mapping

from src.api.auth import TemplateAuthorizationService


class TemplateService:
    def __init__(self):
        self._templates: Dict[str, Dict[str, object]] = {
            "support-agent": {
                "id": "support-agent",
                "agent_type": "worker.support",
                "config": {"queue": "support"},
            }
        }
        self._clones: Dict[str, Dict[str, object]] = {}
        self.template_reads = 0
        self.clone_writes = 0

    def clone_template(
        self,
        template_id: str,
        workspace_id: str,
        clone_name: str,
        headers: Mapping[str, str],
        cookies: Mapping[str, str],
        authorization: TemplateAuthorizationService,
    ) -> Dict[str, object]:
        principal = authorization.require_template_clone(
            headers,
            cookies,
            workspace_id,
        )

        template = self._load_template(template_id)
        clone_id = f"{workspace_id}:{template_id}:{len(self._clones) + 1}"
        clone = {
            "id": clone_id,
            "name": clone_name,
            "template_id": template_id,
            "workspace_id": workspace_id,
            "agent_type": template["agent_type"],
            "config": dict(template["config"]),
            "created_by": principal.subject,
            "created_at": time.time(),
        }
        self._clones[clone_id] = clone
        self.clone_writes += 1
        return clone.copy()

    def _load_template(self, template_id: str) -> Dict[str, object]:
        self.template_reads += 1
        if template_id not in self._templates:
            raise KeyError(template_id)
        return self._templates[template_id]


template_service = TemplateService()
