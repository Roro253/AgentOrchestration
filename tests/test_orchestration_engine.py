import asyncio

import pytest

from src.orchestrator.engine import OrchestrationEngine


class TestOrchestrationEngine:
    def setup_method(self):
        self.engine = OrchestrationEngine()

    def test_enqueue_task_pins_worker_capability_epoch(self):
        agent_id = self.engine.registry.register(
            "hot-reload-worker",
            "worker.processor",
            capabilities=["summarize"],
        )

        task_id = self.engine.enqueue_task(
            agent_id,
            {"type": "summarize"},
            required_capability="summarize",
        )
        task = asyncio.run(self.engine.scheduler.dequeue())

        assert task["id"] == task_id
        assert task["target_agent"] == agent_id
        assert task["required_capability"] == "summarize"
        assert task["worker_capability_epoch"] == 1

    def test_dequeue_defers_stale_worker_epoch_after_reconnect(self):
        agent_id = self.engine.registry.register(
            "hot-reload-worker",
            "worker.processor",
            capabilities=["summarize"],
        )
        task_id = self.engine.enqueue_task(
            agent_id,
            {"type": "summarize"},
            required_capability="summarize",
        )
        self.engine.registry.refresh_capabilities(agent_id, ["translate"])

        task = asyncio.run(self.engine.scheduler.dequeue())

        assert task is None
        assert task_id not in self.engine.scheduler._in_flight
        assert self.engine.dispatch_decisions[-1] == {
            "task_id": task_id,
            "target_agent": agent_id,
            "allowed": False,
            "reason": "stale_capability_epoch",
        }
        assert self.engine.scheduler.claim_audit()[-1] == {
            "event": "task_dispatch_deferred",
            "task_id": task_id,
            "target_agent": agent_id,
            "reason": "stale_capability_epoch",
        }

    def test_enqueue_task_rejects_unknown_agent(self):
        with pytest.raises(ValueError, match="Agent missing not found"):
            self.engine.enqueue_task("missing", {"type": "summarize"})
