from pathlib import Path

from scripts.validate_action_pins import (
    find_mutable_refs,
    main,
    validate_dependabot_config,
)


def write_workflow(path: Path, body: str) -> Path:
    path.write_text(body)
    return path


def test_rejects_mutable_external_action_ref(tmp_path, capsys) -> None:
    workflow = write_workflow(
        tmp_path / "ci.yml",
        """
name: CI
jobs:
  test:
    steps:
      - uses: actions/checkout@v4
""",
    )

    assert main([str(workflow)]) == 1

    captured = capsys.readouterr()
    assert "actions/checkout@v4" in captured.err
    assert "Pin external actions" in captured.err


def test_accepts_full_sha_external_action_ref(tmp_path) -> None:
    workflow = write_workflow(
        tmp_path / "ci.yml",
        """
name: CI
jobs:
  test:
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
""",
    )

    assert find_mutable_refs([workflow]) == []


def test_ignores_local_actions(tmp_path) -> None:
    workflow = write_workflow(
        tmp_path / "ci.yml",
        """
name: CI
jobs:
  test:
    steps:
      - uses: ./.github/actions/internal
""",
    )

    assert find_mutable_refs([workflow]) == []


def test_rejects_external_action_without_ref(tmp_path) -> None:
    workflow = write_workflow(
        tmp_path / "ci.yml",
        """
name: CI
jobs:
  test:
    steps:
      - uses: actions/checkout
""",
    )

    failures = find_mutable_refs([workflow])

    assert "actions/checkout" in failures[0]


def test_rejects_invalid_workflow_yaml(tmp_path) -> None:
    workflow = write_workflow(
        tmp_path / "ci.yml",
        """
name: CI
jobs:
  test:
    steps: [
""",
    )

    failures = find_mutable_refs([workflow])

    assert "invalid YAML" in failures[0]


def test_accepts_github_actions_dependabot_config(tmp_path) -> None:
    config = tmp_path / ".github" / "dependabot.yml"
    config.parent.mkdir()
    config.write_text(
        """
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
"""
    )

    assert validate_dependabot_config(tmp_path) == []


def test_rejects_missing_github_actions_dependabot_config(tmp_path) -> None:
    failures = validate_dependabot_config(tmp_path)

    assert "missing GitHub Actions update automation" in failures[0]
