#!/usr/bin/env python3
"""Validate that a package publish run came from an approved source ref."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping


PROTECTED_BRANCHES = ("main",)
PROTECTED_BRANCH_PREFIXES = ("release/",)
RELEASE_TAG_PATTERN = re.compile(
    r"^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


class PublishRefError(ValueError):
    """Raised when the current GitHub ref is not allowed to publish."""


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def _load_event_inputs(event_path: str | None) -> dict[str, object]:
    if not event_path:
        return {}
    path = Path(event_path)
    if not path.exists():
        return {}
    try:
        event = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    inputs = event.get("inputs")
    return inputs if isinstance(inputs, dict) else {}


def _branch_is_allowed(name: str) -> bool:
    return (
        name in PROTECTED_BRANCHES
        or name.startswith(PROTECTED_BRANCH_PREFIXES)
    )


def _tag_name_is_release(name: str) -> bool:
    return bool(RELEASE_TAG_PATTERN.match(name))


def git_tag_is_signed(tag_name: str) -> bool:
    result = subprocess.run(
        ["git", "tag", "-v", tag_name],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    output = f"{result.stdout}\n{result.stderr}"
    return result.returncode == 0 and "Good signature" in output


def validate_publish_ref(
    env: Mapping[str, str],
    tag_verifier: Callable[[str], bool] = git_tag_is_signed,
) -> str:
    ref_type = env.get("GITHUB_REF_TYPE", "")
    ref_name = env.get("GITHUB_REF_NAME", "")
    ref = env.get("GITHUB_REF", "")
    event_name = env.get("GITHUB_EVENT_NAME", "")
    protected = _truthy(env.get("GITHUB_REF_PROTECTED"))
    inputs = _load_event_inputs(env.get("GITHUB_EVENT_PATH"))

    if not ref_type or not ref_name:
        raise PublishRefError("missing GitHub ref metadata")

    if ref_type == "branch":
        if protected and _branch_is_allowed(ref_name):
            return f"allowed protected branch: {ref_name}"
        raise PublishRefError(
            "package publishing requires a protected release branch; "
            f"actual ref {ref or ref_name!r} is not eligible"
        )

    if ref_type == "tag":
        if not _tag_name_is_release(ref_name):
            raise PublishRefError(
                f"tag {ref_name!r} is not a documented release tag"
            )
        if tag_verifier(ref_name):
            return f"allowed signed release tag: {ref_name}"
        raise PublishRefError(f"release tag {ref_name!r} is not signed")

    input_keys = ", ".join(sorted(inputs)) or "none"
    raise PublishRefError(
        "package publishing only accepts protected branches or signed release "
        f"tags; event={event_name!r}, ref_type={ref_type!r}, "
        f"dispatch_input_keys={input_keys}"
    )


def main() -> int:
    try:
        message = validate_publish_ref(os.environ)
    except PublishRefError as exc:
        print(f"publish ref rejected: {exc}", file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
