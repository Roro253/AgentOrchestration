"""Agent Registry — Manages agent lifecycle and metadata."""

import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.common.metrics import metrics


logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"
    TERMINATED = "terminated"


class HandlerRoutingError(ValueError):
    """Raised when no handler is safe to route work to."""


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        self._resolution_cache: Dict[Tuple[str, Tuple[str, ...]], str] = {}
        self._routing_audit: List[Dict[str, Any]] = []

    def register(
        self,
        name: str,
        agent_type: str,
        config: Optional[Dict] = None,
    ) -> str:
        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        config = config or {}
        self._agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "status": AgentStatus.PENDING.value,
            "config": config,
            "health": config.get("health", "healthy"),
            "health_reason": "",
            "accepting_tasks": config.get("accepting_tasks", True),
            "capabilities": sorted(config.get("capabilities", [])),
            "created_at": timestamp,
            "updated_at": timestamp,
            "version": config.get("version", "1.0.0"),
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }
        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)
        self._invalidate_cache(agent_type, agent_id)
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(agent_id)

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
        self._invalidate_cache(self._agents[agent_id]["type"], agent_id)
        return True

    def update_health(
        self,
        agent_id: str,
        healthy: bool,
        reason: str = "",
        accepting_tasks: Optional[bool] = None,
    ) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents[agent_id]
        agent["health"] = "healthy" if healthy else "unhealthy"
        agent["health_reason"] = reason
        if accepting_tasks is not None:
            agent["accepting_tasks"] = accepting_tasks
        agent["updated_at"] = time.time()
        self._invalidate_cache(agent["type"], agent_id)
        return True

    def resolve(
        self,
        agent_type: Optional[str] = None,
        required_capabilities: Optional[Iterable[str]] = None,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        capabilities = tuple(sorted(required_capabilities or []))
        cache_key = (agent_type or agent_id or "", capabilities)
        cached_id = self._resolution_cache.get(cache_key)
        if cached_id:
            cached = self._agents.get(cached_id)
            if cached and self._is_routable(cached, capabilities):
                self._audit_route("accepted_cached", cached)
                return cached
            self._resolution_cache.pop(cache_key, None)

        chosen = None
        candidates = sorted(
            self._resolve_candidates(agent_type, agent_id),
            key=lambda agent: agent["updated_at"],
            reverse=True,
        )
        for candidate in candidates:
            reason = self._routing_block_reason(candidate, capabilities)
            if reason:
                self._audit_route("rejected", candidate, reason)
            elif chosen is None:
                chosen = candidate
            else:
                self._audit_route(
                    "rejected",
                    candidate,
                    "duplicate_routable_handler",
                )

        if chosen:
            self._resolution_cache[cache_key] = chosen["id"]
            self._audit_route("accepted", chosen)
            return chosen

        reason = "no healthy handler available"
        logger.warning("routing denied: %s", reason)
        raise HandlerRoutingError(reason)

    def routing_audit(self) -> List[Dict[str, Any]]:
        return list(self._routing_audit)

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        self._invalidate_cache(agent["type"], agent_id)
        return True

    def count(self) -> int:
        return len(self._agents)

    def _resolve_candidates(
        self,
        agent_type: Optional[str],
        agent_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        if agent_id:
            agent = self._agents.get(agent_id)
            return [agent] if agent else []
        if not agent_type:
            return []
        group = agent_type.split(".")[0]
        agent_ids = self._index.get(group, [])
        return [
            self._agents[aid]
            for aid in agent_ids
            if self._agents[aid]["type"] == agent_type
        ]

    def _is_routable(
        self,
        agent: Dict[str, Any],
        capabilities: Tuple[str, ...],
    ) -> bool:
        return self._routing_block_reason(agent, capabilities) is None

    def _routing_block_reason(
        self,
        agent: Dict[str, Any],
        capabilities: Tuple[str, ...],
    ) -> Optional[str]:
        if agent["status"] != AgentStatus.RUNNING.value:
            return "not_running"
        if agent["health"] != "healthy":
            return "unhealthy"
        if not agent.get("accepting_tasks", True):
            return "not_accepting_tasks"
        provided = set(agent.get("capabilities", []))
        if not set(capabilities).issubset(provided):
            return "missing_capability"
        return None

    def _invalidate_cache(self, agent_type: str, agent_id: str) -> None:
        stale_keys = [
            key
            for key, cached_id in self._resolution_cache.items()
            if key[0] == agent_type or cached_id == agent_id
        ]
        for key in stale_keys:
            self._resolution_cache.pop(key, None)

    def _audit_route(
        self,
        decision: str,
        agent: Dict[str, Any],
        reason: Optional[str] = None,
    ) -> None:
        record = {
            "decision": decision,
            "agent_id": agent["id"],
            "agent_type": agent["type"],
            "status": agent["status"],
            "health": agent["health"],
            "reason": reason,
            "timestamp": time.time(),
        }
        self._routing_audit.append(record)
        metrics.increment(f"agent_registry.routing.{decision}")
        if reason:
            metrics.increment(f"agent_registry.routing.rejected.{reason}")
        logger.info(
            "routing %s for agent_type=%s agent_id=%s reason=%s",
            decision,
            agent["type"],
            agent["id"],
            reason or "ok",
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
