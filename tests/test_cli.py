import sys

import pytest

from src.cli import main


def run_cli(monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["ao", *args])
    return main.cli()


def test_deploy_dry_run_validates_manifest_without_deploying(
    tmp_path,
    monkeypatch,
    capsys,
):
    manifest = tmp_path / "agent.yaml"
    manifest.write_text("name: dry-run-agent\nversion: 1\n", encoding="utf-8")

    def fail_deploy(_manifest):
        raise AssertionError("dry-run must not call the deploy backend")

    monkeypatch.setattr(main, "_deploy_agent", fail_deploy)

    run_cli(monkeypatch, ["deploy", "--dry-run", str(manifest)])

    output = capsys.readouterr().out
    assert "Dry run successful" in output
    assert str(manifest) in output


def test_deploy_dry_run_rejects_missing_manifest(monkeypatch):
    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch, ["deploy", "--dry-run", "missing.yaml"])

    assert exc.value.code == 2


def test_deploy_dry_run_rejects_non_mapping_manifest(tmp_path, monkeypatch):
    manifest = tmp_path / "agent.yaml"
    manifest.write_text("- agent\n- worker\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch, ["deploy", "--dry-run", str(manifest)])

    assert exc.value.code == 2


def test_deploy_without_dry_run_calls_deploy_backend(tmp_path, monkeypatch):
    manifest = tmp_path / "agent.json"
    manifest.write_text('{"name": "live-agent"}', encoding="utf-8")
    deployed = []

    monkeypatch.setattr(main, "_deploy_agent", deployed.append)

    run_cli(monkeypatch, ["deploy", str(manifest)])

    assert deployed == [str(manifest)]
