"""File runtime helpers for execution run markers."""

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional


class TemporaryRunFileRuntime:
    """Tracks temporary run files and terminal cleanup outcomes."""

    def __init__(self, base_path: Optional[str] = None):
        runtime_dir = base_path or tempfile.mkdtemp(prefix="ao_file_runtime_")
        self.base_path = Path(runtime_dir)
        self.active_path = self.base_path / "active"
        self.completed_path = self.base_path / "completed"
        self.active_path.mkdir(parents=True, exist_ok=True)
        self.completed_path.mkdir(parents=True, exist_ok=True)

    def start_run(
        self,
        execution_id: str,
        agent_id: str,
        task: Dict[str, Any],
    ) -> Path:
        payload = {
            "execution_id": execution_id,
            "agent_id": agent_id,
            "task_id": task.get("id"),
            "started_at": time.time(),
        }
        path = self._active_file(execution_id)
        self._write_json_atomic(path, payload)
        return path

    def finalize_run(
        self,
        execution_id: str,
        outcome: str,
        error: Optional[str] = None,
        cleanup_retries: int = 3,
    ) -> Dict[str, Any]:
        outcome_path = self._outcome_file(execution_id)
        if outcome_path.exists():
            payload = json.loads(outcome_path.read_text())
            if self._active_file(execution_id).exists():
                self._remove_active_file(execution_id, cleanup_retries)
                payload["temporary_run_file_cleaned"] = True
                self._write_json_atomic(outcome_path, payload)
            return payload

        payload: Dict[str, Any] = {
            "execution_id": execution_id,
            "outcome": outcome,
            "finalized_at": time.time(),
            "temporary_run_file_cleaned": False,
        }
        if error:
            payload["error"] = error

        self._write_json_atomic(outcome_path, payload)
        self._remove_active_file(execution_id, cleanup_retries)
        payload["temporary_run_file_cleaned"] = True
        self._write_json_atomic(outcome_path, payload)
        return payload

    def get_outcome(self, execution_id: str) -> Optional[Dict[str, Any]]:
        path = self._outcome_file(execution_id)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def active_run_files(self) -> Dict[str, Path]:
        return {
            path.stem: path
            for path in self.active_path.glob("*.json")
            if path.is_file()
        }

    def _active_file(self, execution_id: str) -> Path:
        return self.active_path / f"{execution_id}.json"

    def _outcome_file(self, execution_id: str) -> Path:
        return self.completed_path / f"{execution_id}.json"

    def _remove_active_file(
        self,
        execution_id: str,
        cleanup_retries: int,
    ) -> None:
        path = self._active_file(execution_id)
        for attempt in range(max(1, cleanup_retries)):
            try:
                path.unlink(missing_ok=True)
                return
            except OSError:
                if attempt == cleanup_retries - 1:
                    raise
                time.sleep(0.01)

    def _write_json_atomic(self, path: Path, payload: Dict[str, Any]) -> None:
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, sort_keys=True))
        os.replace(tmp_path, path)
