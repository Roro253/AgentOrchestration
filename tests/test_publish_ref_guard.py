import json
from pathlib import Path

import pytest
import yaml

from scripts.validate_publish_ref import PublishRefError, validate_publish_ref


def base_env(**overrides):
    env = {
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REF_NAME": "main",
        "GITHUB_REF_PROTECTED": "true",
        "GITHUB_REF_TYPE": "branch",
    }
    env.update(overrides)
    return env


def test_protected_main_branch_can_publish():
    result = validate_publish_ref(base_env())

    assert result == "allowed protected branch: main"


def test_protected_release_branch_can_publish():
    result = validate_publish_ref(
        base_env(
            GITHUB_REF="refs/heads/release/2.4",
            GITHUB_REF_NAME="release/2.4",
        )
    )

    assert result == "allowed protected branch: release/2.4"


def test_unprotected_manual_dispatch_branch_fails_before_auth(tmp_path):
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(
            {
                "inputs": {
                    "version": "2.4.1",
                    "source_ref": "refs/tags/v2.4.1",
                }
            }
        )
    )

    with pytest.raises(PublishRefError) as error:
        validate_publish_ref(
            base_env(
                GITHUB_EVENT_PATH=str(event_path),
                GITHUB_REF="refs/heads/feature/unreviewed",
                GITHUB_REF_NAME="feature/unreviewed",
                GITHUB_REF_PROTECTED="false",
            )
        )

    assert "protected release branch" in str(error.value)
    assert "feature/unreviewed" in str(error.value)


def test_signed_release_tag_can_publish():
    result = validate_publish_ref(
        base_env(
            GITHUB_EVENT_NAME="push",
            GITHUB_REF="refs/tags/v2.4.1",
            GITHUB_REF_NAME="v2.4.1",
            GITHUB_REF_PROTECTED="false",
            GITHUB_REF_TYPE="tag",
        ),
        tag_verifier=lambda name: name == "v2.4.1",
    )

    assert result == "allowed signed release tag: v2.4.1"


def test_unsigned_release_tag_is_rejected():
    with pytest.raises(PublishRefError) as error:
        validate_publish_ref(
            base_env(
                GITHUB_EVENT_NAME="push",
                GITHUB_REF="refs/tags/v2.4.1",
                GITHUB_REF_NAME="v2.4.1",
                GITHUB_REF_TYPE="tag",
            ),
            tag_verifier=lambda name: False,
        )

    assert "not signed" in str(error.value)


def test_non_release_tag_is_rejected_even_if_signed():
    with pytest.raises(PublishRefError) as error:
        validate_publish_ref(
            base_env(
                GITHUB_EVENT_NAME="push",
                GITHUB_REF="refs/tags/test-build",
                GITHUB_REF_NAME="test-build",
                GITHUB_REF_TYPE="tag",
            ),
            tag_verifier=lambda name: True,
        )

    assert "not a documented release tag" in str(error.value)


def test_v_prefixed_non_semver_tag_is_rejected_even_if_signed():
    with pytest.raises(PublishRefError) as error:
        validate_publish_ref(
            base_env(
                GITHUB_EVENT_NAME="push",
                GITHUB_REF="refs/tags/vnext",
                GITHUB_REF_NAME="vnext",
                GITHUB_REF_TYPE="tag",
            ),
            tag_verifier=lambda name: True,
        )

    assert "not a documented release tag" in str(error.value)


def test_dispatch_inputs_cannot_override_actual_ref(tmp_path):
    event_path = Path(tmp_path) / "event.json"
    event_path.write_text(
        json.dumps(
            {
                "inputs": {
                    "version": "2.4.1",
                    "protected": "true",
                    "ref": "refs/tags/v2.4.1",
                }
            }
        )
    )

    with pytest.raises(PublishRefError) as error:
        validate_publish_ref(
            base_env(
                GITHUB_EVENT_PATH=str(event_path),
                GITHUB_REF="refs/heads/dev-scratch",
                GITHUB_REF_NAME="dev-scratch",
                GITHUB_REF_PROTECTED="false",
            ),
            tag_verifier=lambda name: True,
        )

    assert "dev-scratch" in str(error.value)
    assert "refs/tags/v2.4.1" not in str(error.value)


def test_publish_workflow_validates_before_registry_auth():
    workflow_path = Path(".github/workflows/publish.yml")
    workflow = yaml.safe_load(workflow_path.read_text())
    steps = workflow["jobs"]["publish"]["steps"]
    names = [step["name"] for step in steps if "name" in step]

    validate_index = names.index(
        "Validate protected publish ref before registry auth"
    )
    publish_index = names.index("Publish to PyPI")

    assert validate_index < publish_index
    assert (
        steps[validate_index]["run"]
        == "python scripts/validate_publish_ref.py"
    )
