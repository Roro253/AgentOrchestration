"""Task Scheduler — Priority-based task queuing and dispatch."""

import heapq
import logging
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.common.metrics import metrics

logger = logging.getLogger(__name__)


class PriorityQueue:
    def __init__(self):
        self._queue = []
        self._counter = 0

    def push(self, item: Any, priority: int = 0) -> None:
        heapq.heappush(self._queue, (-priority, self._counter, item))
        self._counter += 1

    def pop(self) -> Optional[Any]:
        if self._queue:
            return heapq.heappop(self._queue)[2]
        return None

    def peek(self) -> Optional[Any]:
        if self._queue:
            return self._queue[0][2]
        return None

    def __len__(self) -> int:
        return len(self._queue)


class TaskScheduler:
    def __init__(self):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._claim_audit: List[Dict[str, Any]] = []
        self._max_retries = 3

    def enqueue(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(
        self,
        task: Dict,
        delay: float,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(
        self,
        queue: str = "default",
        timeout: float = 1.0,
    ) -> Optional[Dict]:
        self._promote_scheduled(queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                self._in_flight[task["id"]] = task
                return task
        return None

    async def claim_for_worker(
        self,
        worker_snapshot: Dict[str, Any],
        queue: str = "default",
        timeout: float = 1.0,
    ) -> Optional[Dict]:
        self._promote_scheduled(queue)
        if queue not in self._queues or len(self._queues[queue]) == 0:
            return None

        skipped = []
        claimed = None
        while len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            decision = self._worker_claim_decision(task, worker_snapshot)
            if decision == "claim":
                claimed = task
                break
            self._record_claim_decision(task, worker_snapshot, decision)
            skipped.append(task)

        for task in skipped:
            self._queues[queue].push(task, task.get("priority", 0))

        if claimed:
            claimed["claimed_by"] = worker_snapshot["id"]
            claimed["worker_capability_epoch"] = (
                worker_snapshot["capability_epoch"]
            )
            self._in_flight[claimed["id"]] = claimed
            metrics.increment("scheduler.worker_claim.accepted")
            return claimed
        return None

    def complete(self, task_id: str) -> bool:
        return self._in_flight.pop(task_id, None) is not None

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False

    def claim_audit(self) -> List[Dict[str, Any]]:
        return list(self._claim_audit)

    def _promote_scheduled(self, queue: str) -> None:
        now = time.time()
        expired = [
            tid
            for tid, scheduled_at in self._scheduled.items()
            if scheduled_at <= now
        ]
        for task_id in expired:
            task = self._scheduled.pop(task_id)
            if task:
                self.enqueue(task, queue)

    def _worker_claim_decision(
        self,
        task: Dict[str, Any],
        worker_snapshot: Dict[str, Any],
    ) -> str:
        worker_id = worker_snapshot["id"]
        if task.get("target_agent") and task["target_agent"] != worker_id:
            return "target_agent_mismatch"

        required_epoch = task.get("worker_capability_epoch")
        if (
            required_epoch is not None
            and required_epoch != worker_snapshot["capability_epoch"]
        ):
            return "stale_capability_epoch"

        required_capability = task.get("required_capability")
        capabilities = set(worker_snapshot.get("capabilities", []))
        if required_capability and required_capability not in capabilities:
            return "missing_capability"

        return "claim"

    def _record_claim_decision(
        self,
        task: Dict[str, Any],
        worker_snapshot: Dict[str, Any],
        decision: str,
    ) -> None:
        audit = {
            "event": "worker_claim_deferred",
            "task_id": task.get("id"),
            "worker_id": worker_snapshot["id"],
            "worker_capability_epoch": worker_snapshot["capability_epoch"],
            "reason": decision,
        }
        self._claim_audit.append(audit)
        metrics.increment(f"scheduler.worker_claim.deferred.{decision}")
        logger.info(
            "Deferred worker claim",
            extra={
                "task_id": task.get("id"),
                "worker_id": worker_snapshot["id"],
                "reason": decision,
            },
        )

# 2019-04-25T08:37:12 update

# 2019-06-04T16:40:00 update

# 2019-07-11T12:01:28 update

# 2019-08-02T12:20:21 update

# 2019-08-23T10:38:50 update

# 2019-10-31T13:55:52 update

# 2019-11-04T20:12:32 update

# 2019-12-13T12:22:36 update

# 2020-02-01T10:32:37 update

# 2020-02-26T09:44:38 update

# 2020-03-09T19:00:55 update

# 2020-05-01T18:40:34 update

# 2020-05-12T15:10:31 update

# 2020-06-30T13:24:19 update

# 2020-09-22T16:00:45 update

# 2020-10-20T10:52:48 update

# 2020-10-21T12:18:08 update

# 2020-11-06T12:35:01 update

# 2020-12-09T08:09:33 update

# 2021-01-07T08:20:36 update

# 2021-10-02T15:23:16 update

# 2021-10-06T16:14:57 update

# 2021-10-06T09:27:41 update

# 2021-11-19T08:37:40 update

# 2022-03-01T16:39:54 update

# 2022-05-26T13:43:07 update

# 2022-06-02T10:50:58 update

# 2022-06-14T10:46:48 update

# 2022-07-31T16:44:34 update

# 2022-08-30T18:20:12 update

# 2022-11-04T14:47:03 update

# 2022-12-06T10:36:49 update

# 2022-12-22T13:21:12 update

# 2022-12-26T12:24:50 update

# 2023-03-09T08:09:55 update

# 2023-05-01T10:07:37 update

# 2023-06-08T14:32:15 update

# 2023-07-14T17:24:18 update

# 2023-12-14T08:38:31 update

# 2024-02-20T13:43:58 update

# 2024-03-24T08:52:42 update

# 2024-03-28T15:27:17 update

# 2024-03-29T18:10:33 update

# 2024-04-15T20:18:31 update

# 2024-05-27T13:11:52 update

# 2024-05-27T16:42:56 update

# 2024-06-20T13:03:45 update

# 2024-06-28T12:32:58 update

# 2024-07-10T14:10:16 update

# 2024-07-26T14:18:59 update

# 2024-08-12T08:21:05 update

# 2024-08-21T16:58:40 update

# 2024-09-27T19:54:30 update

# 2024-10-21T13:47:42 update

# 2024-11-11T09:19:27 update

# 2024-12-24T08:23:41 update

# 2025-02-14T10:35:15 update

# 2025-03-31T18:09:40 update

# 2025-06-21T17:32:49 update

# 2025-07-21T16:52:28 update

# 2025-08-20T19:45:16 update

# 2025-11-04T18:54:24 update

# 2025-12-09T20:17:36 update

# 2026-01-12T15:42:32 update

# 2026-01-23T14:41:20 update

# 2026-03-18T14:43:07 update

# 2026-04-13T11:43:19 update
