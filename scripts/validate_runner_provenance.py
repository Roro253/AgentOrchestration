#!/usr/bin/env python3
"""Validate self-hosted runner provenance before release/build steps."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ProvenanceError(ValueError):
    """Raised when runner provenance fails validation."""


@dataclass(frozen=True)
class RunnerProvenance:
    labels: frozenset[str]
    image_digest: str
    built_at: dt.datetime


def _split_values(value: str | None) -> set[str]:
    if not value:
        return set()
    value = value.strip()
    if not value:
        return set()
    if value.startswith("["):
        parsed = json.loads(value)
        return {str(item).strip() for item in parsed if str(item).strip()}
    return {item.strip() for item in value.split(",") if item.strip()}


def _parse_timestamp(value: str | None) -> dt.datetime:
    if not value:
        raise ProvenanceError("runner image build timestamp is missing")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ProvenanceError(
            "runner image build timestamp must be ISO-8601"
        ) from exc
    if parsed.tzinfo is None:
        raise ProvenanceError(
            "runner image build timestamp must include a timezone"
        )
    return parsed.astimezone(dt.timezone.utc)


def _parse_digest(value: str | None) -> str:
    digest = (value or "").strip().lower()
    if not digest:
        raise ProvenanceError("runner image digest is missing")
    if not DIGEST_RE.fullmatch(digest):
        raise ProvenanceError("runner image digest must be sha256:<64 hex>")
    return digest


def _max_age_days(value: str | None) -> int:
    if value is None or not value.strip():
        return 14
    try:
        days = int(value)
    except ValueError as exc:
        message = "max runner image age must be an integer"
        raise ProvenanceError(message) from exc
    if days < 1:
        raise ProvenanceError("max runner image age must be at least 1 day")
    return days


def _load_provenance(env: dict[str, str]) -> RunnerProvenance:
    labels = frozenset(_split_values(env.get("AO_RUNNER_LABELS")))
    if not labels:
        raise ProvenanceError("runner labels are missing")
    return RunnerProvenance(
        labels=labels,
        image_digest=_parse_digest(env.get("AO_RUNNER_IMAGE_DIGEST")),
        built_at=_parse_timestamp(env.get("AO_RUNNER_IMAGE_BUILT_AT")),
    )


def _validate_labels(
    runner_labels: Iterable[str],
    required_labels: set[str],
    approved_labels: set[str],
) -> None:
    labels = set(runner_labels)
    missing = required_labels - labels
    if missing:
        raise ProvenanceError(
            "runner is missing required labels: " + ", ".join(sorted(missing))
        )
    unapproved = labels - approved_labels
    if unapproved:
        raise ProvenanceError(
            "runner has unapproved labels: " + ", ".join(sorted(unapproved))
        )


def validate_runner(
    env: dict[str, str],
    now: dt.datetime | None = None,
) -> RunnerProvenance:
    provenance = _load_provenance(env)
    required_labels = _split_values(env.get("AO_REQUIRED_RUNNER_LABELS"))
    approved_labels = _split_values(env.get("AO_APPROVED_RUNNER_LABELS"))
    approved_digests = {
        digest.lower()
        for digest in _split_values(
            env.get("AO_APPROVED_RUNNER_IMAGE_DIGESTS")
        )
    }

    if not required_labels:
        raise ProvenanceError("required runner labels are missing")
    if not approved_labels:
        raise ProvenanceError("approved runner labels are missing")
    if not approved_digests:
        raise ProvenanceError("approved runner image digests are missing")

    _validate_labels(provenance.labels, required_labels, approved_labels)
    if provenance.image_digest not in approved_digests:
        raise ProvenanceError("runner image digest is not approved")

    current_time = now or dt.datetime.now(dt.timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=dt.timezone.utc)
    max_age = dt.timedelta(
        days=_max_age_days(env.get("AO_MAX_RUNNER_IMAGE_AGE_DAYS"))
    )
    age = current_time.astimezone(dt.timezone.utc) - provenance.built_at
    if age < dt.timedelta(0):
        raise ProvenanceError("runner image build timestamp is in the future")
    if age > max_age:
        raise ProvenanceError(
            "runner image is stale: "
            f"age {age.days} days exceeds {max_age.days}"
        )
    return provenance


def _redact_digest(digest: str) -> str:
    return f"{digest[:18]}...{digest[-8:]}"


def write_summary(
    summary_path: str | None,
    provenance: RunnerProvenance | None,
    status: str,
    message: str,
) -> None:
    if not summary_path:
        return
    lines = [
        "## Runner provenance preflight",
        "",
        f"- Status: `{status}`",
        f"- Detail: {message}",
    ]
    if provenance is not None:
        lines.extend(
            [
                f"- Labels: `{', '.join(sorted(provenance.labels))}`",
                f"- Image digest: `{_redact_digest(provenance.image_digest)}`",
                f"- Image built at: `{provenance.built_at.isoformat()}`",
            ]
        )
    Path(summary_path).open("a", encoding="utf-8").write(
        "\n".join(lines) + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail closed on missing provenance inputs",
    )
    args = parser.parse_args()
    try:
        provenance = validate_runner(dict(os.environ))
    except ProvenanceError as exc:
        write_summary(
            os.environ.get("GITHUB_STEP_SUMMARY"),
            None,
            "failed",
            str(exc),
        )
        print(f"runner provenance validation failed: {exc}", file=sys.stderr)
        return 1 if args.strict else 0

    write_summary(
        os.environ.get("GITHUB_STEP_SUMMARY"),
        provenance,
        "passed",
        "runner labels, image digest, and build timestamp are approved",
    )
    print("runner provenance validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
