"""API middleware components."""

import hashlib
import logging
import re
import time
from typing import Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

AUDIT_ACTOR_HEADER = "X-Audit-Actor"
AUDIT_STATUS_HEADER = "X-Audit-Status"
AUDIT_STATE_FIELDS = (
    "audit_actor",
    "audit_authenticated",
)
AUTH_TOKEN_PATH = "/api/v2/auth/token"
PROTECTED_API_PREFIX = "/api/v2"
SAFE_ACTOR_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        _clear_audit_state(request)
        actor = None
        outcome = "public"
        status_code = 200

        try:
            if _requires_auth(request):
                token = _extract_bearer_token(request)
                if token is None:
                    outcome = "rejected"
                    status_code = 401
                    return Response(
                        status_code=status_code,
                        content="Unauthorized",
                        headers={AUDIT_STATUS_HEADER: outcome},
                    )

                try:
                    actor = _resolve_audit_actor(request, token)
                except ValueError:
                    outcome = "rejected"
                    status_code = 400
                    return Response(
                        status_code=status_code,
                        content="Invalid audit actor",
                        headers={AUDIT_STATUS_HEADER: outcome},
                    )

                request.state.audit_actor = actor
                request.state.audit_authenticated = True
                outcome = "authenticated"

            response = await call_next(request)
            status_code = response.status_code
            response.headers[AUDIT_STATUS_HEADER] = outcome
            if actor is not None:
                response.headers[AUDIT_ACTOR_HEADER] = actor
            return response
        except Exception:
            status_code = 500
            logger.exception(
                "request failed after audit middleware decision",
                extra=_audit_log_extra(request, actor, outcome, status_code),
            )
            raise
        finally:
            logger.info(
                "audit middleware completed",
                extra=_audit_log_extra(request, actor, outcome, status_code),
            )
            _clear_audit_state(request)


def _requires_auth(request: Request) -> bool:
    path = request.url.path
    return path.startswith(PROTECTED_API_PREFIX) and path != AUTH_TOKEN_PATH


def _extract_bearer_token(request: Request) -> Optional[str]:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return None
    token = authorization[len("Bearer "):].strip()
    return token or None


def _resolve_audit_actor(request: Request, token: str) -> str:
    actor = (
        request.headers.get("X-Audit-Actor")
        or request.headers.get("X-Actor-Id")
        or request.headers.get("X-User-Id")
    )
    if actor:
        actor = actor.strip()
        if not SAFE_ACTOR_RE.fullmatch(actor):
            raise ValueError("invalid audit actor")
        return actor

    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"token:{digest[:12]}"


def _audit_log_extra(
    request: Request,
    actor: Optional[str],
    outcome: str,
    status_code: int,
) -> dict:
    return {
        "audit_actor": actor or "anonymous",
        "audit_outcome": outcome,
        "audit_status_code": status_code,
        "method": request.method,
        "path": request.url.path,
    }


def _clear_audit_state(request: Request) -> None:
    for field in AUDIT_STATE_FIELDS:
        try:
            delattr(request.state, field)
        except (AttributeError, KeyError):
            pass


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 100, window: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window
        self._requests = {}

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        if client_ip not in self._requests:
            self._requests[client_ip] = []

        self._requests[client_ip] = [
            t for t in self._requests[client_ip]
            if now - t < self.window
        ]

        if len(self._requests[client_ip]) >= self.max_requests:
            return Response(status_code=429, content="Too many requests")

        self._requests[client_ip].append(now)
        return await call_next(request)


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        logger.info(
            "%s %s %s %.3fs",
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )
        return response

# 2019-03-01T18:35:19 update

# 2019-04-03T13:22:05 update

# 2019-04-30T17:18:49 update

# 2019-08-20T09:29:03 update

# 2019-08-30T15:52:06 update

# 2019-11-23T16:58:42 update

# 2020-02-18T10:04:07 update

# 2020-04-21T17:35:30 update

# 2020-05-22T11:10:34 update

# 2020-07-02T12:31:26 update

# 2020-07-05T13:52:59 update

# 2020-08-21T20:36:45 update

# 2021-01-19T09:17:15 update

# 2021-01-29T11:34:24 update

# 2021-02-04T15:21:21 update

# 2021-04-19T19:23:15 update

# 2021-05-20T16:50:15 update

# 2021-06-22T19:23:44 update

# 2021-09-09T13:44:55 update

# 2021-09-16T09:30:20 update

# 2021-10-14T20:42:33 update

# 2021-12-28T16:39:14 update

# 2022-01-26T19:07:27 update

# 2022-01-28T08:03:41 update

# 2022-03-23T12:17:02 update

# 2022-04-06T12:12:27 update

# 2022-04-21T14:53:01 update

# 2022-06-30T08:37:32 update

# 2022-07-06T10:44:45 update

# 2022-11-02T11:12:47 update

# 2022-11-15T20:54:21 update

# 2022-11-23T14:13:34 update

# 2023-01-26T10:03:44 update

# 2023-02-09T17:08:10 update

# 2023-02-16T10:04:00 update

# 2023-03-14T11:52:03 update

# 2023-04-10T12:42:07 update

# 2023-04-26T10:43:39 update

# 2023-06-27T08:18:07 update

# 2023-08-30T15:30:40 update

# 2023-08-30T14:10:05 update

# 2023-10-09T18:32:46 update

# 2023-11-21T20:35:55 update

# 2024-03-07T19:17:39 update

# 2024-04-01T18:06:19 update

# 2024-07-18T15:37:34 update

# 2024-07-25T09:21:53 update

# 2024-08-12T14:24:22 update

# 2024-11-18T08:50:54 update

# 2025-04-08T12:43:05 update

# 2025-06-03T08:10:47 update

# 2025-06-12T08:37:52 update

# 2025-06-17T08:36:56 update

# 2025-07-02T18:09:42 update

# 2025-07-22T12:39:21 update

# 2025-10-13T12:13:46 update

# 2025-12-05T09:44:22 update

# 2025-12-22T18:34:47 update

# 2026-01-26T15:36:23 update

# 2026-02-13T12:36:40 update

# 2026-02-26T11:07:15 update

# 2026-03-19T11:00:17 update

# 2026-03-27T12:58:53 update

# 2026-05-12T17:19:36 update
