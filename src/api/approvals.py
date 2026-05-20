"""Approval endpoint service guards."""

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple


RUN_WAITING_FOR_HUMAN = "waiting_for_human"


@dataclass
class ApprovalStep:
    run_id: str
    step_id: str
    workspace_id: str
    run_state: str = RUN_WAITING_FOR_HUMAN
    requires_human: bool = True
    approved: bool = False


class ApprovalService:
    """Shared approval service that validates before lookup or mutation."""

    def __init__(self, steps: Optional[Iterable[ApprovalStep]] = None):
        self._run_states: Dict[Tuple[str, str], str] = {}
        self._step_index: Dict[Tuple[str, str, str], ApprovalStep] = {}
        self.protected_lookup_count = 0
        self.mutation_count = 0
        for step in steps or ():
            self.add(step)

    def add(self, step: ApprovalStep) -> None:
        self._run_states[(step.workspace_id, step.run_id)] = step.run_state
        self._step_index[(step.workspace_id, step.run_id, step.step_id)] = step

    def approve_step(
        self,
        run_id: str,
        step_id: str,
        workspace_id: str,
        role: str,
    ) -> ApprovalStep:
        run_id = run_id.strip()
        step_id = step_id.strip()
        workspace_id = workspace_id.strip()
        role = role.strip().lower()

        if not run_id or not step_id or not workspace_id:
            raise ApprovalMalformed
        if role not in {"operator", "admin"}:
            raise ApprovalUnauthorized

        run_state = self._run_states.get((workspace_id, run_id))
        if run_state is None:
            raise ApprovalNotFound
        if run_state != RUN_WAITING_FOR_HUMAN:
            raise ApprovalInvalidRunState

        key = (workspace_id, run_id, step_id)
        step = self._step_index.get(key)
        if step is None or not step.requires_human:
            raise ApprovalNotFound

        self.protected_lookup_count += 1
        step.approved = True
        self.mutation_count += 1
        return step


class ApprovalMalformed(Exception):
    pass


class ApprovalUnauthorized(Exception):
    pass


class ApprovalNotFound(Exception):
    pass


class ApprovalInvalidRunState(Exception):
    pass


approval_service = ApprovalService()


def get_approval_service() -> ApprovalService:
    return approval_service
