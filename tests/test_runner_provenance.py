import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from validate_runner_provenance import (  # noqa: E402
    ProvenanceError,
    validate_runner,
    write_summary,
)


APPROVED_DIGEST = "sha256:" + "a" * 64


def base_env(**overrides):
    env = {
        "AO_RUNNER_LABELS": "self-hosted,linux,x64,agent-orchestration-build",
        "AO_REQUIRED_RUNNER_LABELS": (
            "self-hosted,linux,x64,agent-orchestration-build"
        ),
        "AO_APPROVED_RUNNER_LABELS": (
            "self-hosted,linux,x64,agent-orchestration-build"
        ),
        "AO_RUNNER_IMAGE_DIGEST": APPROVED_DIGEST,
        "AO_APPROVED_RUNNER_IMAGE_DIGESTS": APPROVED_DIGEST,
        "AO_RUNNER_IMAGE_BUILT_AT": "2026-05-19T12:00:00Z",
        "AO_MAX_RUNNER_IMAGE_AGE_DAYS": "7",
    }
    env.update(overrides)
    return env


def now():
    return dt.datetime(2026, 5, 20, 12, 0, tzinfo=dt.timezone.utc)


def test_valid_runner_provenance_passes():
    provenance = validate_runner(base_env(), now=now())

    assert provenance.image_digest == APPROVED_DIGEST
    assert "agent-orchestration-build" in provenance.labels


def test_unapproved_label_fails_closed():
    with pytest.raises(ProvenanceError, match="unapproved labels"):
        validate_runner(
            base_env(
                AO_RUNNER_LABELS=(
                    "self-hosted,linux,x64,agent-orchestration-build,gpu"
                )
            ),
            now=now(),
        )


def test_unapproved_digest_fails_closed():
    with pytest.raises(ProvenanceError, match="digest is not approved"):
        validate_runner(
            base_env(AO_RUNNER_IMAGE_DIGEST="sha256:" + "b" * 64),
            now=now(),
        )


def test_stale_build_timestamp_fails_closed():
    with pytest.raises(ProvenanceError, match="stale"):
        validate_runner(
            base_env(AO_RUNNER_IMAGE_BUILT_AT="2026-05-01T12:00:00Z"),
            now=now(),
        )


def test_missing_approved_digest_fails_closed():
    with pytest.raises(ProvenanceError, match="approved runner image digests"):
        validate_runner(
            base_env(AO_APPROVED_RUNNER_IMAGE_DIGESTS=""),
            now=now(),
        )


def test_summary_redacts_digest(tmp_path):
    summary = tmp_path / "summary.md"
    provenance = validate_runner(base_env(), now=now())

    write_summary(str(summary), provenance, "passed", "ok")

    contents = summary.read_text()
    assert "sha256:aaaaaaaaaaa" in contents
    assert APPROVED_DIGEST not in contents
    assert "agent-orchestration-build" in contents


def test_release_workflow_requires_strict_preflight_before_build():
    workflow = Path(".github/workflows/release.yml").read_text()

    preflight = workflow.index("Runner provenance preflight")
    build = workflow.index("Build package")

    assert "--strict" in workflow
    assert preflight < build
    assert "AO_APPROVED_RUNNER_IMAGE_DIGESTS" in workflow
    assert "agent-orchestration-build" in workflow
