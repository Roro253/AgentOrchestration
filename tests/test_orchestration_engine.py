import asyncio

from src.agent import AgentStatus
from src.orchestrator.engine import OrchestrationEngine


def test_execute_task_rechecks_required_permission_before_status_change():
    engine = OrchestrationEngine()
    agent_id = engine.registry.register(
        "safe-worker",
        "worker.processor",
        {"permissions": ["tasks:run"]},
    )
    cached = engine.registry.resolve_authorized(
        "worker.processor",
        "tasks:run",
        agent_id=agent_id,
    )
    assert cached["id"] == agent_id
    assert engine.registry.update_permissions(agent_id, ["tasks:read"])

    errors = []

    async def on_error(_task, error):
        errors.append(error)

    engine.register_hook("on_error", on_error)
    asyncio.run(
        engine._execute_task(
            {
                "id": "task-1",
                "target_agent": agent_id,
                "required_permission": "tasks:run",
            },
        ),
    )

    agent = engine.registry.get(agent_id)
    assert agent["status"] == AgentStatus.PENDING.value
    assert len(errors) == 1
    assert isinstance(errors[0], PermissionError)
