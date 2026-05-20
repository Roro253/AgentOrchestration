"""Agent Registry — Manages agent lifecycle and metadata."""

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.common.metrics import metrics


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"
    TERMINATED = "terminated"


UNAVAILABLE_STATUSES = {
    AgentStatus.PAUSED.value,
    AgentStatus.STOPPED.value,
    AgentStatus.FAILED.value,
    AgentStatus.TERMINATED.value,
}


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        self._list_cache: Dict[
            Tuple[Optional[str], Optional[str], bool],
            List[Dict[str, Any]],
        ] = {}
        self._audit_records: List[Dict[str, Any]] = []

    def register(
        self,
        name: str,
        agent_type: str,
        config: Optional[Dict] = None,
    ) -> str:
        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        self._agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "status": AgentStatus.PENDING.value,
            "config": config or {},
            "enabled": self._config_enabled(config),
            "created_at": timestamp,
            "updated_at": timestamp,
            "version": "1.0.0",
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }
        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)
        self._invalidate_list_cache()
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(agent_id)

    def list(
        self,
        status: Optional[AgentStatus] = None,
        group: Optional[str] = None,
        include_disabled: bool = False,
    ) -> List[Dict[str, Any]]:
        cache_key = (status.value if status else None, group, include_disabled)
        if cache_key in self._list_cache:
            return [agent.copy() for agent in self._list_cache[cache_key]]

        agents = self._agents.values()
        if status:
            agents = [a for a in agents if a["status"] == status.value]
        if group:
            agent_ids = self._index.get(group, [])
            agents = [a for a in agents if a["id"] in agent_ids]
        agents = list(agents)
        if not include_disabled:
            visible_agents = [a for a in agents if self._is_discoverable(a)]
            self._record_filtered_listing(
                len(agents) - len(visible_agents),
                status,
                group,
            )
            agents = visible_agents

        self._list_cache[cache_key] = [agent.copy() for agent in agents]
        return [agent.copy() for agent in agents]

    def resolve(
        self,
        agent_id: Optional[str] = None,
        agent_type: Optional[str] = None,
        group: Optional[str] = None,
        include_disabled: bool = False,
    ) -> Optional[Dict[str, Any]]:
        agents = list(self._agents.values())
        if group:
            agent_ids = self._index.get(group, [])
            agents = [agent for agent in agents if agent["id"] in agent_ids]

        for agent in agents:
            if agent_id and agent["id"] != agent_id:
                continue
            if agent_type and agent["type"] != agent_type:
                continue
            if include_disabled or self._is_discoverable(agent):
                return agent.copy()
            self._record_rejected_resolution(
                agent,
                agent_id,
                agent_type,
                group,
            )
        return None

    def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        if agent_id not in self._agents:
            return False
        self._agents[agent_id]["status"] = status.value
        self._agents[agent_id]["updated_at"] = time.time()
        self._invalidate_list_cache()
        return True

    def set_enabled(self, agent_id: str, enabled: bool) -> bool:
        if agent_id not in self._agents:
            return False
        self._agents[agent_id]["enabled"] = bool(enabled)
        self._agents[agent_id]["updated_at"] = time.time()
        self._invalidate_list_cache()
        return True

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        self._invalidate_list_cache()
        return True

    def count(self) -> int:
        return len(self._agents)

    def audit_records(self) -> List[Dict[str, Any]]:
        return [record.copy() for record in self._audit_records]

    def _invalidate_list_cache(self) -> None:
        self._list_cache.clear()

    @staticmethod
    def _config_enabled(config: Optional[Dict]) -> bool:
        if not config:
            return True
        if "enabled" in config:
            return bool(config["enabled"])
        if "disabled" in config:
            return not bool(config["disabled"])
        return True

    @staticmethod
    def _is_discoverable(agent: Dict[str, Any]) -> bool:
        return (
            agent.get("enabled", True)
            and agent["status"] not in UNAVAILABLE_STATUSES
        )

    def _record_filtered_listing(
        self,
        filtered_count: int,
        status: Optional[AgentStatus],
        group: Optional[str],
    ) -> None:
        if filtered_count <= 0:
            return
        self._audit_records.append({
            "event": "registry.disabled_entries_filtered",
            "filtered_count": filtered_count,
            "status": status.value if status else None,
            "group": group,
            "timestamp": time.time(),
        })
        metrics.increment("registry.disabled_entries_filtered", filtered_count)

    def _record_rejected_resolution(
        self,
        agent: Dict[str, Any],
        agent_id: Optional[str],
        agent_type: Optional[str],
        group: Optional[str],
    ) -> None:
        self._audit_records.append({
            "event": "registry.disabled_resolution_rejected",
            "agent_id": agent_id,
            "agent_type": agent_type or agent["type"],
            "group": group or agent["type"].split(".")[0],
            "status": agent["status"],
            "timestamp": time.time(),
        })
        metrics.increment("registry.disabled_resolution_rejected")

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
