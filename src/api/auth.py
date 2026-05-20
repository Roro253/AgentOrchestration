"""Central API authorization helpers."""

import time
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional


class AuthorizationError(Exception):
    def __init__(self, status_code: int, reason: str):
        super().__init__(reason)
        self.status_code = status_code
        self.reason = reason


@dataclass
class Principal:
    subject: str
    scopes: List[str]
    workspace_roles: Dict[str, str]
    expires_at: float
    revoked: bool = False
    disabled: bool = False
    client_type: str = "token"


class SessionStore:
    def __init__(self):
        self._principals: Dict[str, Principal] = {}
        self._invalidated: set[str] = set()

    def register(self, token: str, principal: Principal) -> None:
        self._principals[token] = principal
        self._invalidated.discard(token)

    def get(self, token: str) -> Optional[Principal]:
        if token in self._invalidated:
            return None
        return self._principals.get(token)

    def invalidate(self, token: str) -> None:
        self._invalidated.add(token)


class TemplateAuthorizationService:
    def __init__(self, session_store: Optional[SessionStore] = None):
        self.session_store = session_store or SessionStore()
        self._audit_records: List[Dict[str, object]] = []

    def require_template_clone(
        self,
        headers: Mapping[str, str],
        cookies: Mapping[str, str],
        workspace_id: str,
    ) -> Principal:
        token, client_type = self._extract_credential(headers, cookies)
        principal = self.session_store.get(token)
        if principal is None:
            self._deny("unknown", client_type, workspace_id)

        now = time.time()
        if principal.revoked:
            self.session_store.invalidate(token)
            self._deny("revoked", principal.client_type, workspace_id)
        if principal.disabled:
            self.session_store.invalidate(token)
            self._deny("disabled", principal.client_type, workspace_id)
        if principal.expires_at <= now:
            self.session_store.invalidate(token)
            self._deny("stale", principal.client_type, workspace_id)
        if "templates:clone" not in principal.scopes:
            self._deny(
                "insufficient_scope",
                principal.client_type,
                workspace_id,
            )

        role = principal.workspace_roles.get(workspace_id)
        if role not in {"owner", "admin", "editor"}:
            self._deny(
                "insufficient_role",
                principal.client_type,
                workspace_id,
            )

        self._audit_records.append({
            "event": "template_clone_authorized",
            "client_type": principal.client_type,
            "workspace_id": workspace_id,
            "role": role,
        })
        return principal

    def audit_records(self) -> List[Dict[str, object]]:
        return [record.copy() for record in self._audit_records]

    def _extract_credential(
        self,
        headers: Mapping[str, str],
        cookies: Mapping[str, str],
    ) -> tuple[str, str]:
        authorization = (
            headers.get("authorization")
            or headers.get("Authorization")
        )
        if authorization:
            prefix = "Bearer "
            if not authorization.startswith(prefix):
                self._deny("malformed", "token", None)
            token = authorization[len(prefix):].strip()
            if not token:
                self._deny("malformed", "token", None)
            return token, "token"

        session = (
            headers.get("x-integration-session")
            or headers.get("X-Integration-Session")
            or cookies.get("ao_session")
        )
        if not session:
            self._deny("anonymous", "unknown", None)
        if not session.startswith("sess_"):
            self._deny("malformed", "browser", None)
        return session, "browser"

    def _deny(
        self,
        reason: str,
        client_type: str,
        workspace_id: Optional[str],
    ) -> None:
        self._audit_records.append({
            "event": "template_clone_denied",
            "reason": reason,
            "client_type": client_type,
            "workspace_id": workspace_id,
        })
        status_code = 403 if reason.startswith("insufficient") else 401
        raise AuthorizationError(status_code, reason)


session_store = SessionStore()
template_authorization = TemplateAuthorizationService(session_store)
