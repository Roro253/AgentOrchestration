import asyncio

from src.agent import AgentStatus
from src.orchestrator.engine import OrchestrationEngine


class TestOrchestrationEngine:
    def test_unhealthy_target_is_rejected_before_execution(self):
        engine = OrchestrationEngine()
        agent_id = engine.registry.register("worker-v1", "worker.processor")
        engine.registry.update_status(agent_id, AgentStatus.RUNNING)
        engine.registry.update_health(
            agent_id,
            healthy=False,
            reason="rolling deploy drain",
            accepting_tasks=False,
        )

        status_updates = []
        original_update_status = engine.registry.update_status

        def track_status_update(target_agent_id, status):
            status_updates.append((target_agent_id, status))
            return original_update_status(target_agent_id, status)

        async def fail_if_executed(agent, task):
            raise AssertionError("unhealthy handler should not execute")

        errors = []

        async def record_error(task, error):
            errors.append(error)

        engine.registry.update_status = track_status_update
        engine._run_agent_task = fail_if_executed
        engine.register_hook("on_error", record_error)

        asyncio.run(
            engine._execute_task(
                {
                    "id": "task-1",
                    "target_agent": agent_id,
                    "type": "worker.processor",
                }
            )
        )

        assert status_updates == []
        assert len(errors) == 1
        assert "no healthy handler" in str(errors[0])
