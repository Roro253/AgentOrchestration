"""Task monitor authorization and state access."""

import time
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from typing import Dict, Iterable, Optional, Set


MONITOR_SCOPE = "tasks:monitor"
MONITOR_ROLES = {"viewer", "operator", "admin"}


@dataclass
class MonitorCredential:
    subject: str
    workspace_id: str
    role: str
    scopes: Set[str] = field(default_factory=set)
    revoked: bool = False
    disabled: bool = False
    expires_at: Optional[float] = None


@dataclass
class MonitorPrincipal:
    subject: str
    workspace_id: str
    role: str
    credential_type: str


class MonitorAuthError(Exception):
    status_code = 403
    detail = "Task monitor access denied"


class MonitorAnonymous(MonitorAuthError):
    status_code = 401
    detail = "Task monitor authentication required"


class MonitorInvalidCredential(MonitorAuthError):
    status_code = 401
    detail = "Task monitor credential is invalid"


class MonitorRevokedCredential(MonitorAuthError):
    status_code = 401
    detail = "Task monitor credential is revoked"


class MonitorDisabledCredential(MonitorAuthError):
    status_code = 403
    detail = "Task monitor principal is disabled"


class MonitorExpiredCredential(MonitorAuthError):
    status_code = 401
    detail = "Task monitor credential is expired"


class MonitorInsufficientScope(MonitorAuthError):
    status_code = 403
    detail = "Task monitor scope is required"


class MonitorWorkspaceDenied(MonitorAuthError):
    status_code = 403
    detail = "Task monitor workspace access denied"


class MonitorRoleDenied(MonitorAuthError):
    status_code = 403
    detail = "Task monitor role is required"


class TaskMonitorAuthService:
    """Revalidates API key or browser-session credentials on each poll."""

    def __init__(
        self,
        api_keys: Optional[Dict[str, MonitorCredential]] = None,
        sessions: Optional[Dict[str, MonitorCredential]] = None,
        now=None,
    ):
        self._api_keys = api_keys or {}
        self._sessions = sessions or {}
        self._now = now or time.time

    def validate(
        self,
        *,
        authorization: Optional[str],
        cookie_header: Optional[str],
        session_token: Optional[str],
        workspace_id: Optional[str],
        required_scope: str = MONITOR_SCOPE,
    ) -> MonitorPrincipal:
        credential_type, token = self._extract_credential(
            authorization=authorization,
            cookie_header=cookie_header,
            session_token=session_token,
        )
        if token is None or credential_type is None:
            raise MonitorAnonymous

        credential = self._lookup(credential_type, token)
        if credential is None:
            raise MonitorInvalidCredential
        if credential.revoked:
            raise MonitorRevokedCredential
        if credential.disabled:
            raise MonitorDisabledCredential
        if (
            credential.expires_at is not None
            and credential.expires_at <= self._now()
        ):
            raise MonitorExpiredCredential
        if required_scope not in credential.scopes:
            raise MonitorInsufficientScope
        if credential.role not in MONITOR_ROLES:
            raise MonitorRoleDenied
        if not workspace_id or workspace_id != credential.workspace_id:
            raise MonitorWorkspaceDenied

        return MonitorPrincipal(
            subject=credential.subject,
            workspace_id=credential.workspace_id,
            role=credential.role,
            credential_type=credential_type,
        )

    def revoke_api_key(self, token: str) -> None:
        if token in self._api_keys:
            self._api_keys[token].revoked = True

    def _lookup(
        self, credential_type: str, token: str
    ) -> Optional[MonitorCredential]:
        if credential_type == "api_key":
            return self._api_keys.get(token)
        if credential_type == "session":
            return self._sessions.get(token)
        return None

    @staticmethod
    def _extract_credential(
        *,
        authorization: Optional[str],
        cookie_header: Optional[str],
        session_token: Optional[str],
    ) -> tuple[Optional[str], Optional[str]]:
        if authorization:
            parts = authorization.split(" ", 1)
            if len(parts) != 2 or parts[0] != "Bearer" or not parts[1].strip():
                raise MonitorInvalidCredential
            return "api_key", parts[1].strip()

        if session_token:
            token = session_token.strip()
            if not token:
                raise MonitorInvalidCredential
            return "session", token

        if cookie_header:
            cookie = SimpleCookie()
            cookie.load(cookie_header)
            if "ao_session" in cookie:
                token = cookie["ao_session"].value.strip()
                if not token:
                    raise MonitorInvalidCredential
                return "session", token

        return None, None


class TaskMonitorStore:
    """Small in-memory task monitor state store used by the API."""

    def __init__(self, tasks: Optional[Iterable[Dict]] = None):
        self._tasks = {}
        self.read_count = 0
        for task in tasks or ():
            self.add(task)

    def add(self, task: Dict) -> None:
        self._tasks[task["id"]] = dict(task)

    def get(self, task_id: str, workspace_id: str) -> Optional[Dict]:
        task = self._tasks.get(task_id)
        if not task or task.get("workspace_id") != workspace_id:
            return None
        self.read_count += 1
        return dict(task)


task_monitor_auth_service = TaskMonitorAuthService()
task_monitor_store = TaskMonitorStore()


def get_task_monitor_auth_service() -> TaskMonitorAuthService:
    return task_monitor_auth_service


def get_task_monitor_store() -> TaskMonitorStore:
    return task_monitor_store
