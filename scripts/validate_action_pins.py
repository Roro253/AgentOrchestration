"""Validate that external GitHub Actions references are pinned to SHAs."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable, List

import yaml


USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*['\"]?([^'\"\s#]+)")
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DOCKER_DIGEST_RE = re.compile(r"^docker://.+@sha256:[0-9a-f]{64}$")


def workflow_files(root: Path) -> Iterable[Path]:
    workflows = root / ".github" / "workflows"
    if not workflows.exists():
        return []
    return sorted(
        path
        for path in workflows.iterdir()
        if path.is_file() and path.suffix in {".yml", ".yaml"}
    )


def is_external_action(reference: str) -> bool:
    return not (
        reference.startswith("./")
        or reference.startswith("../")
        or reference.startswith("docker://")
    )


def is_pinned(reference: str) -> bool:
    if reference.startswith("docker://"):
        return bool(DOCKER_DIGEST_RE.match(reference))
    if "@" not in reference:
        return False
    ref = reference.rsplit("@", 1)[1]
    return bool(FULL_SHA_RE.match(ref))


def find_mutable_refs(paths: Iterable[Path]) -> List[str]:
    failures: List[str] = []
    for path in paths:
        try:
            yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            failures.append(f"{path}: invalid YAML: {exc}")
            continue
        lines = path.read_text().splitlines()
        for line_number, line in enumerate(lines, start=1):
            match = USES_RE.match(line)
            if not match:
                continue
            reference = match.group(1)
            if is_external_action(reference) and not is_pinned(reference):
                failures.append(f"{path}:{line_number}: uses {reference!r}")
    return failures


def validate_dependabot_config(root: Path) -> List[str]:
    path = root / ".github" / "dependabot.yml"
    if not path.exists():
        return [f"{path}: missing GitHub Actions update automation"]

    try:
        config = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        return [f"{path}: invalid YAML: {exc}"]

    updates = config.get("updates") or []
    for update in updates:
        if not isinstance(update, dict):
            continue
        if (
            update.get("package-ecosystem") == "github-actions"
            and update.get("directory") == "/"
        ):
            return []

    return [f"{path}: missing github-actions updates for directory '/'"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help=(
            "Workflow files to validate. Defaults to "
            ".github/workflows/*.yml."
        ),
    )
    args = parser.parse_args(argv)

    root = Path.cwd()
    paths = args.paths or list(workflow_files(root))
    failures = find_mutable_refs(paths)
    if not args.paths:
        failures.extend(validate_dependabot_config(root))
    if failures:
        print(
            "GitHub Actions supply-chain validation failed:",
            file=sys.stderr,
        )
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        print(
            "Pin external actions to full 40-character commit SHAs.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Validated {len(paths)} workflow file(s); "
        "all external actions are pinned."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
