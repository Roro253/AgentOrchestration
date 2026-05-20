import asyncio

from src.orchestrator.engine import OrchestrationEngine


async def _dequeue_registered_task(engine):
    agent_id = engine.registry.register("worker-1", "worker.processor")
    engine.scheduler.enqueue({"type": "sync", "target_agent": agent_id})
    return await engine.scheduler.dequeue()


def test_releases_task_lock_and_records_retry_after_execution_exception():
    async def run():
        engine = OrchestrationEngine()
        task = await _dequeue_registered_task(engine)
        task_id = task["id"]
        errors = []

        async def failing_run_agent_task(agent, task):
            raise RuntimeError("handler crashed")

        async def on_error(task, error):
            errors.append((task["id"], str(error)))

        engine._run_agent_task = failing_run_agent_task
        engine.register_hook("on_error", on_error)

        await engine._execute_task(task)

        assert not await engine.lock_manager.is_locked(task_id)
        assert task_id not in engine.scheduler._in_flight
        assert errors == [(task_id, "handler crashed")]

        retry = await engine.scheduler.dequeue()
        assert retry is not None
        assert retry["retries"] == 1
        assert retry["id"] != task_id

    asyncio.run(run())


def test_duplicate_task_dispatch_is_skipped_while_lock_is_held():
    async def run():
        engine = OrchestrationEngine()
        task = await _dequeue_registered_task(engine)
        task_id = task["id"]
        entered = asyncio.Event()
        release = asyncio.Event()
        executions = []

        async def blocking_run_agent_task(agent, task):
            executions.append(task["id"])
            entered.set()
            await release.wait()
            return {"status": "completed"}

        engine._run_agent_task = blocking_run_agent_task

        first = asyncio.create_task(engine._execute_task(task))
        await entered.wait()
        await engine._execute_task(task)
        release.set()
        await first

        assert executions == [task_id]
        assert not await engine.lock_manager.is_locked(task_id)
        assert task_id not in engine.scheduler._in_flight

    asyncio.run(run())
