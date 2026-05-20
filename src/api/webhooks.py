"""Webhook delivery logging with secret redaction."""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.common.metrics import metrics


SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "password",
    "secret",
    "signature",
    "token",
)
INTERNAL_KEY_PARTS = (
    "internal",
    "private",
)
REDACTED = "[REDACTED]"


@dataclass(frozen=True)
class WebhookEndpoint:
    id: str
    workspace_id: str
    url: str
    secret: str
    enabled: bool = True
    version: int = 1


@dataclass
class DeliveryRecord:
    event_id: str
    endpoint_id: str
    workspace_id: str
    attempt: int
    status: str
    reason: str
    delivered: bool
    created_at: float
    log_fields: Dict[str, Any]
    callback_payload: Dict[str, Any]


@dataclass
class WebhookDeliveryService:
    endpoints: Iterable[WebhookEndpoint] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._endpoints = {
            endpoint.id: endpoint for endpoint in self.endpoints
        }
        self._delivery_records: Dict[
            Tuple[str, str, int],
            DeliveryRecord,
        ] = {}

    def register_endpoint(self, endpoint: WebhookEndpoint) -> None:
        self._endpoints[endpoint.id] = endpoint

    def rotate_endpoint(
        self,
        endpoint_id: str,
        secret: str,
    ) -> WebhookEndpoint:
        endpoint = self._require_endpoint(endpoint_id)
        rotated = WebhookEndpoint(
            id=endpoint.id,
            workspace_id=endpoint.workspace_id,
            url=endpoint.url,
            secret=secret,
            enabled=endpoint.enabled,
            version=endpoint.version + 1,
        )
        self._endpoints[endpoint_id] = rotated
        return rotated

    def disable_endpoint(self, endpoint_id: str) -> WebhookEndpoint:
        endpoint = self._require_endpoint(endpoint_id)
        disabled = WebhookEndpoint(
            id=endpoint.id,
            workspace_id=endpoint.workspace_id,
            url=endpoint.url,
            secret=endpoint.secret,
            enabled=False,
            version=endpoint.version,
        )
        self._endpoints[endpoint_id] = disabled
        return disabled

    def deliver(
        self,
        workspace_id: str,
        endpoint_id: str,
        event_id: str,
        payload: Dict[str, Any],
        *,
        endpoint_version: Optional[int] = None,
        attempt: int = 1,
    ) -> DeliveryRecord:
        return self._record_delivery(
            workspace_id,
            endpoint_id,
            event_id,
            payload,
            endpoint_version=endpoint_version,
            attempt=attempt,
            valid_status="delivered",
            valid_reason="accepted",
            delivered=True,
        )

    def record_failure(
        self,
        workspace_id: str,
        endpoint_id: str,
        event_id: str,
        failure_fields: Dict[str, Any],
        *,
        endpoint_version: Optional[int] = None,
        attempt: int = 1,
    ) -> DeliveryRecord:
        return self._record_delivery(
            workspace_id,
            endpoint_id,
            event_id,
            failure_fields,
            endpoint_version=endpoint_version,
            attempt=attempt,
            valid_status="failed",
            valid_reason="delivery_failed",
            delivered=False,
        )

    def retry(
        self,
        record: DeliveryRecord,
        payload: Dict[str, Any],
    ) -> DeliveryRecord:
        return self.deliver(
            record.workspace_id,
            record.endpoint_id,
            record.event_id,
            payload,
            attempt=record.attempt + 1,
        )

    def records(self) -> List[DeliveryRecord]:
        return list(self._delivery_records.values())

    def _record_delivery(
        self,
        workspace_id: str,
        endpoint_id: str,
        event_id: str,
        fields: Dict[str, Any],
        *,
        endpoint_version: Optional[int],
        attempt: int,
        valid_status: str,
        valid_reason: str,
        delivered: bool,
    ) -> DeliveryRecord:
        existing = self._delivery_records.get(
            (endpoint_id, event_id, attempt),
        )
        if existing:
            return existing

        endpoint = self._endpoints.get(endpoint_id)
        status = valid_status
        reason = valid_reason
        if not endpoint:
            status = "rejected"
            reason = "endpoint_not_found"
        elif endpoint.workspace_id != workspace_id:
            status = "rejected"
            reason = "workspace_mismatch"
        elif not endpoint.enabled:
            status = "rejected"
            reason = "endpoint_disabled"
        elif (
            endpoint_version is not None
            and endpoint.version != endpoint_version
        ):
            status = "rejected"
            reason = "endpoint_rotated"

        is_delivered = delivered and status == "delivered"
        sanitized_payload = sanitize_delivery_fields(fields)
        callback_payload = self._build_callback_payload(
            workspace_id,
            endpoint_id,
            event_id,
            attempt,
            status,
            reason,
            sanitized_payload,
        )
        record = DeliveryRecord(
            event_id=event_id,
            endpoint_id=endpoint_id,
            workspace_id=workspace_id,
            attempt=attempt,
            status=status,
            reason=reason,
            delivered=is_delivered,
            created_at=time.time(),
            log_fields={
                "event_id": event_id,
                "endpoint_id": endpoint_id,
                "workspace_id": workspace_id,
                "attempt": attempt,
                "status": status,
                "reason": reason,
                "payload": sanitized_payload,
            },
            callback_payload=callback_payload,
        )
        self._delivery_records[(endpoint_id, event_id, attempt)] = record
        metrics.increment(f"webhook.delivery.{status}.{reason}")
        return record

    def _require_endpoint(self, endpoint_id: str) -> WebhookEndpoint:
        endpoint = self._endpoints.get(endpoint_id)
        if not endpoint:
            raise KeyError(endpoint_id)
        return endpoint

    def _build_callback_payload(
        self,
        workspace_id: str,
        endpoint_id: str,
        event_id: str,
        attempt: int,
        status: str,
        reason: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "workspace_id": workspace_id,
            "endpoint_id": endpoint_id,
            "event_id": event_id,
            "attempt": attempt,
            "status": status,
            "reason": reason,
            "payload": payload,
        }


def sanitize_delivery_fields(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, nested_value in value.items():
            normalized_key = key.lower().replace("-", "_")
            if _matches(normalized_key, INTERNAL_KEY_PARTS):
                continue
            if _matches(normalized_key, SENSITIVE_KEY_PARTS):
                sanitized[key] = REDACTED
            else:
                sanitized[key] = sanitize_delivery_fields(nested_value)
        return sanitized
    if isinstance(value, list):
        return [sanitize_delivery_fields(item) for item in value]
    if isinstance(value, str):
        return _sanitize_url(value)
    return value


def _matches(key: str, parts: Iterable[str]) -> bool:
    return any(part in key for part in parts)


def _sanitize_url(value: str) -> str:
    split = urlsplit(value)
    if split.scheme not in ("http", "https") or not split.netloc:
        return value

    sanitized_query = []
    changed = False
    for key, nested_value in parse_qsl(
        split.query,
        keep_blank_values=True,
    ):
        normalized_key = key.lower().replace("-", "_")
        if _matches(normalized_key, SENSITIVE_KEY_PARTS):
            sanitized_query.append((key, REDACTED))
            changed = True
        else:
            sanitized_query.append((key, nested_value))

    if not changed:
        return value

    return urlunsplit(
        (
            split.scheme,
            split.netloc,
            split.path,
            urlencode(sanitized_query),
            split.fragment,
        )
    )
