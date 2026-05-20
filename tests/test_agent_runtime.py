import sys
import time

from src.agent.runtime import AgentRuntime, RuntimeState


def wait_for_exit(runtime: AgentRuntime, agent_id: str) -> int:
    proc = runtime._processes[agent_id]
    return proc.wait(timeout=5)


def test_zero_exit_process_reports_stopped() -> None:
    runtime = AgentRuntime()

    assert runtime.start(
        "zero-exit", [sys.executable, "-c", "raise SystemExit(0)"]
    )
    assert wait_for_exit(runtime, "zero-exit") == 0

    assert runtime.get_state("zero-exit") == RuntimeState.STOPPED
    assert runtime.is_running("zero-exit") is False


def test_nonzero_exit_process_reports_crashed() -> None:
    runtime = AgentRuntime()

    assert runtime.start(
        "nonzero-exit", [sys.executable, "-c", "raise SystemExit(7)"]
    )
    assert wait_for_exit(runtime, "nonzero-exit") == 7

    assert runtime.get_state("nonzero-exit") == RuntimeState.CRASHED
    assert runtime.is_running("nonzero-exit") is False


def test_running_process_stays_running_until_exit() -> None:
    runtime = AgentRuntime()

    assert runtime.start(
        "still-running", [sys.executable, "-c", "import time; time.sleep(2)"]
    )
    try:
        assert runtime.get_state("still-running") == RuntimeState.RUNNING
        assert runtime.is_running("still-running") is True
    finally:
        runtime.stop("still-running")


def test_intentional_stop_is_not_reclassified_as_crashed() -> None:
    runtime = AgentRuntime()

    assert runtime.start(
        "stopped-agent", [sys.executable, "-c", "import time; time.sleep(10)"]
    )
    time.sleep(0.05)

    assert runtime.stop("stopped-agent", timeout=1)
    assert runtime.get_state("stopped-agent") == RuntimeState.STOPPED
    assert runtime.is_running("stopped-agent") is False
