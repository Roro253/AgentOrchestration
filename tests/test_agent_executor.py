import asyncio

from src.agent.executor import AgentExecutor
from src.agent.file_runtime import TemporaryRunFileRuntime


def make_executor(tmp_path):
    runtime = TemporaryRunFileRuntime(str(tmp_path / "run-files"))
    return AgentExecutor(run_file_runtime=runtime)


def test_execute_cleans_temporary_run_file_on_success(tmp_path):
    async def scenario():
        executor = make_executor(tmp_path)

        async def handler(agent_id, task):
            assert agent_id == "agent-1"
            assert task["id"] == "task-1"
            assert len(executor.active_run_files()) == 1
            return {"ok": True}

        execution_id = await executor.execute(
            "agent-1",
            {"id": "task-1"},
            handler,
        )

        assert executor.active_run_files() == {}
        assert executor.get_result(execution_id)["result"] == {"ok": True}
        outcome = executor.get_cleanup_outcome(execution_id)
        assert outcome["outcome"] == "completed"
        assert outcome["temporary_run_file_cleaned"]

    asyncio.run(scenario())


def test_execute_cleans_temporary_run_file_on_exception(tmp_path):
    async def scenario():
        executor = make_executor(tmp_path)

        async def handler(agent_id, task):
            assert len(executor.active_run_files()) == 1
            raise RuntimeError("boom")

        execution_id = await executor.execute(
            "agent-1",
            {"id": "task-1"},
            handler,
        )

        assert executor.active_run_files() == {}
        assert executor.get_result(execution_id) == {"error": "boom"}
        outcome = executor.get_cleanup_outcome(execution_id)
        assert outcome["outcome"] == "failed"
        assert outcome["error"] == "boom"
        assert outcome["temporary_run_file_cleaned"]

    asyncio.run(scenario())


def test_cancel_cleans_run_file_and_records_terminal_outcome(tmp_path):
    async def scenario():
        executor = make_executor(tmp_path)
        started = asyncio.Event()
        release = asyncio.Event()

        async def handler(agent_id, task):
            started.set()
            await release.wait()

        task = asyncio.create_task(
            executor.execute("agent-1", {"id": "task-1"}, handler)
        )
        await started.wait()
        execution_id = next(iter(executor.active_run_files()))

        assert executor.cancel(execution_id)
        returned_execution_id = await task

        assert returned_execution_id == execution_id
        assert executor.active_run_files() == {}
        assert executor.get_result(execution_id) == {"cancelled": True}
        outcome = executor.get_cleanup_outcome(execution_id)
        assert outcome["outcome"] == "cancelled"

    asyncio.run(scenario())


def test_shutdown_cleans_active_temporary_run_files(tmp_path):
    async def scenario():
        executor = make_executor(tmp_path)
        started = asyncio.Event()
        release = asyncio.Event()

        async def handler(agent_id, task):
            started.set()
            await release.wait()

        task = asyncio.create_task(
            executor.execute("agent-1", {"id": "task-1"}, handler)
        )
        await started.wait()
        execution_id = next(iter(executor.active_run_files()))

        await executor.shutdown()
        returned_execution_id = await task

        assert returned_execution_id == execution_id
        assert executor.active_run_files() == {}
        assert executor.get_result(execution_id) == {"cancelled": True}
        outcome = executor.get_cleanup_outcome(execution_id)
        assert outcome["outcome"] == "cancelled"

    asyncio.run(scenario())


def test_run_file_finalization_is_idempotent(tmp_path):
    runtime = TemporaryRunFileRuntime(str(tmp_path / "run-files"))
    runtime.start_run("exec-1", "agent-1", {"id": "task-1"})

    first = runtime.finalize_run("exec-1", "completed")
    second = runtime.finalize_run("exec-1", "failed", "late error")

    assert first == second
    assert second["outcome"] == "completed"
    assert "late error" not in second.values()
    assert runtime.active_run_files() == {}
