"""Agent Registry — Manages agent lifecycle and metadata."""

import json
import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from src.common.metrics import metrics

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"
    TERMINATED = "terminated"


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        self._authorization_cache: Dict[str, Dict[str, Any]] = {}
        self._audit_events: List[Dict[str, Any]] = []

    def register(
        self,
        name: str,
        agent_type: str,
        config: Optional[Dict] = None,
    ) -> str:
        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        config = dict(config or {})
        permissions = self._normalize_permissions(
            config.get("permissions", []),
        )
        config["permissions"] = list(permissions)
        self._agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "status": AgentStatus.PENDING.value,
            "config": config,
            "created_at": timestamp,
            "updated_at": timestamp,
            "version": "1.0.0",
            "permission_version": 1,
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }
        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)
        self._record_authorization_decision(
            "registered",
            agent_id=agent_id,
            agent_type=agent_type,
            permission_count=len(permissions),
        )
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(agent_id)

    def resolve_authorized(
        self,
        agent_type: str,
        permission: str,
        status: Optional[AgentStatus] = None,
        agent_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Resolve an agent only if the current permission policy allows it."""
        permission = self._normalize_permission(permission)
        cache_key = self._authorization_cache_key(
            agent_type,
            permission,
            status,
            agent_id,
        )
        cached = self._authorization_cache.get(cache_key)
        if cached:
            agent = self._agents.get(cached["agent_id"])
            if self._cached_resolution_is_current(
                agent,
                cached,
                permission,
                status,
            ):
                self._record_authorization_decision(
                    "cache_hit",
                    agent_id=agent["id"],
                    agent_type=agent_type,
                    permission=permission,
                )
                return agent

            self._authorization_cache.pop(cache_key, None)
            self._record_authorization_decision(
                "cache_invalidated",
                agent_id=cached.get("agent_id"),
                agent_type=agent_type,
                permission=permission,
            )

        candidates = self._resolution_candidates(agent_type, status, agent_id)
        for agent in candidates:
            if agent["type"] != agent_type:
                continue
            if self._agent_has_permission(agent, permission):
                self._authorization_cache[cache_key] = {
                    "agent_id": agent["id"],
                    "permission_version": agent["permission_version"],
                }
                self._record_authorization_decision(
                    "authorized",
                    agent_id=agent["id"],
                    agent_type=agent_type,
                    permission=permission,
                )
                return agent

        self._record_authorization_decision(
            "denied",
            agent_id=agent_id,
            agent_type=agent_type,
            permission=permission,
        )
        return None

    def update_permissions(
        self,
        agent_id: str,
        permissions: List[str],
    ) -> bool:
        if agent_id not in self._agents:
            return False

        agent = self._agents[agent_id]
        agent["config"]["permissions"] = list(
            self._normalize_permissions(permissions),
        )
        agent["permission_version"] += 1
        agent["updated_at"] = time.time()
        invalidated = self._invalidate_authorization_cache(agent_id)
        self._record_authorization_decision(
            "permissions_changed",
            agent_id=agent_id,
            agent_type=agent["type"],
            permission_count=len(agent["config"]["permissions"]),
            invalidated_cache_entries=invalidated,
        )
        return True

    def list(
        self,
        status: Optional[AgentStatus] = None,
        group: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        agents = self._agents.values()
        if status:
            agents = [a for a in agents if a["status"] == status.value]
        if group:
            agent_ids = self._index.get(group, [])
            agents = [a for a in agents if a["id"] in agent_ids]
        return list(agents)

    def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        if agent_id not in self._agents:
            return False
        self._agents[agent_id]["status"] = status.value
        self._agents[agent_id]["updated_at"] = time.time()
        self._invalidate_authorization_cache(agent_id)
        return True

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        self._invalidate_authorization_cache(agent_id)
        return True

    def count(self) -> int:
        return len(self._agents)

    def audit_events(self) -> List[Dict[str, Any]]:
        return list(self._audit_events)

    def _agent_has_permission(
        self,
        agent: Dict[str, Any],
        permission: str,
    ) -> bool:
        return permission in agent["config"].get("permissions", [])

    def _cached_resolution_is_current(
        self,
        agent: Optional[Dict[str, Any]],
        cached: Dict[str, Any],
        permission: str,
        status: Optional[AgentStatus],
    ) -> bool:
        if not agent:
            return False
        if cached["permission_version"] != agent["permission_version"]:
            return False
        if status and agent["status"] != status.value:
            return False
        return self._agent_has_permission(agent, permission)

    def _resolution_candidates(
        self,
        agent_type: str,
        status: Optional[AgentStatus],
        agent_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        if agent_id is not None:
            agent = self._agents.get(agent_id)
            if not agent:
                return []
            if agent["type"] != agent_type:
                return []
            if status and agent["status"] != status.value:
                return []
            return [agent]
        return self.list(status=status, group=agent_type.split(".")[0])

    def _authorization_cache_key(
        self,
        agent_type: str,
        permission: str,
        status: Optional[AgentStatus],
        agent_id: Optional[str],
    ) -> str:
        status_value = status.value if status else "*"
        return json.dumps(
            {
                "agent_id": agent_id or "*",
                "type": agent_type,
                "permission": permission,
                "status": status_value,
            },
            sort_keys=True,
        )

    def _invalidate_authorization_cache(self, agent_id: str) -> int:
        stale_keys = [
            key
            for key, value in self._authorization_cache.items()
            if value["agent_id"] == agent_id
        ]
        for key in stale_keys:
            self._authorization_cache.pop(key, None)
        return len(stale_keys)

    def _normalize_permissions(
        self,
        permissions: List[str],
    ) -> List[str]:
        return sorted(
            {
                self._normalize_permission(permission)
                for permission in permissions
            },
        )

    def _normalize_permission(self, permission: str) -> str:
        if not isinstance(permission, str) or not permission.strip():
            raise ValueError("permissions must be non-empty strings")
        return permission.strip().lower()

    def _record_authorization_decision(
        self,
        decision: str,
        **details: Any,
    ) -> None:
        audit_event = {
            "timestamp": time.time(),
            "decision": decision,
            "agent_id": details.get("agent_id"),
            "agent_type": details.get("agent_type"),
            "permission": details.get("permission"),
            "permission_count": details.get("permission_count"),
            "invalidated_cache_entries": details.get(
                "invalidated_cache_entries",
            ),
        }
        self._audit_events.append(
            {k: v for k, v in audit_event.items() if v is not None},
        )
        metrics.increment(f"agent_registry.authorization.{decision}")
        logger.info(
            "agent registry authorization decision",
            extra={
                "decision": decision,
                "agent_id": details.get("agent_id"),
                "agent_type": details.get("agent_type"),
            },
        )

# 2019-01-29T11:24:49 update

# 2019-04-09T13:38:38 update

# 2019-04-11T11:24:12 update

# 2019-06-26T17:03:48 update

# 2019-07-03T14:55:48 update

# 2019-07-18T18:18:47 update

# 2019-11-05T11:27:19 update

# 2019-11-20T11:35:05 update

# 2019-11-23T15:28:54 update

# 2020-03-13T09:23:07 update

# 2020-03-30T19:31:18 update

# 2020-04-22T15:03:30 update

# 2020-07-21T10:00:48 update

# 2020-09-10T09:02:08 update

# 2020-09-10T13:39:12 update

# 2020-09-22T16:27:52 update

# 2020-10-15T10:33:14 update

# 2021-05-13T11:15:56 update

# 2021-07-07T14:57:13 update

# 2021-07-13T15:15:19 update

# 2021-07-27T10:18:16 update

# 2022-03-11T15:24:11 update

# 2022-09-22T13:24:20 update

# 2022-11-01T12:20:40 update

# 2023-01-30T12:32:27 update

# 2023-03-10T09:43:50 update

# 2023-05-10T14:28:01 update

# 2023-05-11T20:04:46 update

# 2023-05-30T17:00:59 update

# 2023-07-13T17:54:32 update

# 2023-07-20T19:04:20 update

# 2023-07-31T17:00:02 update

# 2023-09-05T19:42:07 update

# 2024-01-02T10:29:47 update

# 2024-09-17T12:45:29 update

# 2024-09-17T11:51:01 update

# 2024-11-06T18:20:15 update

# 2025-01-12T15:13:14 update

# 2025-01-14T20:24:39 update

# 2025-03-26T20:21:27 update

# 2025-04-10T18:27:06 update

# 2025-06-19T20:34:58 update

# 2025-06-21T20:23:53 update

# 2025-06-24T20:30:30 update

# 2025-07-03T13:28:03 update

# 2025-07-24T17:42:21 update

# 2025-08-19T17:42:23 update

# 2025-08-21T11:06:52 update

# 2025-10-24T09:10:08 update

# 2025-12-18T19:34:38 update

# 2026-02-06T11:22:22 update

# 2026-02-13T15:42:04 update

# 2026-04-10T08:16:30 update

# 2026-04-29T18:16:11 update
