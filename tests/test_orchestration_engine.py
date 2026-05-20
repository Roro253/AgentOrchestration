import asyncio

from src.agent.registry import AgentStatus
from src.orchestrator.engine import OrchestrationEngine


class TestOrchestrationEngine:
    def test_execute_task_rejects_disabled_target_before_running(self):
        engine = OrchestrationEngine()
        agent_id = engine.registry.register(
            "agent-1",
            "worker.processor",
            config={"enabled": False, "secret": "private-token"},
        )
        errors = []

        async def on_error(task, error):
            errors.append((task["id"], str(error)))

        async def fail_if_run(agent, task):
            raise AssertionError("disabled agent should not execute")

        engine.register_hook("on_error", on_error)
        engine._run_agent_task = fail_if_run

        asyncio.run(engine._execute_task({
            "id": "task-1",
            "target_agent": agent_id,
        }))

        agent = engine.registry.get(agent_id)
        records = engine.registry.audit_records()
        assert agent["status"] == AgentStatus.PENDING.value
        assert errors == [("task-1", f"Agent {agent_id} not available")]
        assert records[-1]["event"] == "registry.disabled_resolution_rejected"
        assert "private-token" not in str(records[-1])

    def test_execute_task_rejects_paused_target_before_status_mutation(self):
        engine = OrchestrationEngine()
        agent_id = engine.registry.register("agent-1", "worker.processor")
        engine.registry.update_status(agent_id, AgentStatus.PAUSED)
        errors = []

        async def on_error(task, error):
            errors.append(str(error))

        async def fail_if_run(agent, task):
            raise AssertionError("paused agent should not execute")

        engine.register_hook("on_error", on_error)
        engine._run_agent_task = fail_if_run

        asyncio.run(engine._execute_task({
            "id": "task-2",
            "target_agent": agent_id,
        }))

        agent = engine.registry.get(agent_id)
        assert agent["status"] == AgentStatus.PAUSED.value
        assert errors == [f"Agent {agent_id} not available"]
