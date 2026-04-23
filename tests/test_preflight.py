import json
from pathlib import Path

import server


def test_preflight_recommends_fix_environment_when_project_file_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/usr/bin/false")
    monkeypatch.setattr(server, "_port_accepting", lambda port, timeout=0.2: False, raising=False)

    result = json.loads(server.preflight_project())

    assert result["project_path"] == str(tmp_path)
    assert result["project_exists"] is True
    assert result["project_godot_exists"] is False
    assert result["recommended_path"] == "fix_environment"
    assert "project.godot not found" in result["warnings"]


def test_preflight_recommends_scaffold_tests_when_project_lacks_mcp_scaffold(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/usr/bin/false")
    monkeypatch.setattr(server, "_port_accepting", lambda port, timeout=0.2: False, raising=False)
    (tmp_path / "project.godot").write_text('[application]\nconfig/name="Test"\n', encoding="utf-8")

    result = json.loads(server.preflight_project())

    assert result["project_godot_exists"] is True
    assert result["scaffold_status"] == "missing"
    assert result["recommended_path"] == "scaffold_tests"


def test_preflight_recommends_runtime_session_when_scaffold_exists_without_editor(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/usr/bin/false")
    monkeypatch.setattr(server, "_port_accepting", lambda port, timeout=0.2: False, raising=False)
    (tmp_path / "project.godot").write_text('[application]\nconfig/name="Test"\n', encoding="utf-8")
    server.scaffold_tests()

    result = json.loads(server.preflight_project())

    assert result["scaffold_status"] == "ok"
    assert result["editor_bridge_available"] is False
    assert result["recommended_path"] == "runtime_session"


def test_preflight_reports_editor_and_remote_port_status(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/usr/bin/false")
    (tmp_path / "project.godot").write_text('[application]\nconfig/name="Test"\n', encoding="utf-8")
    server.scaffold_tests()

    def fake_port(port: int, timeout: float = 0.2) -> bool:
        return port in {server.EditorBridge.EDITOR_PORT, server.EditorBridge.REMOTE_PORT}

    monkeypatch.setattr(server, "_port_accepting", fake_port, raising=False)

    result = json.loads(server.preflight_project())

    assert result["editor_bridge_available"] is True
    assert result["remote_port_busy"] is True
    assert "remote control port 6790 is already accepting connections" in result["warnings"]


def test_project_preflight_never_launches_godot(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/usr/bin/false")
    monkeypatch.setattr(server, "_port_accepting", lambda port, timeout=0.2: False, raising=False)
    (tmp_path / "project.godot").write_text('[application]\nconfig/name="Test"\n', encoding="utf-8")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("preflight must not spawn processes")

    monkeypatch.setattr(server.subprocess, "Popen", fail_if_called)

    result = json.loads(server.preflight_project())

    assert result["recommended_path"] in {"scaffold_tests", "fix_environment", "runtime_session"}


def test_preflight_inferrs_project_from_cwd_when_env_points_at_root(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", "/")
    monkeypatch.setenv("GODOT_BIN", "/usr/bin/false")
    monkeypatch.setattr(server, "_port_accepting", lambda port, timeout=0.2: False, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "project.godot").write_text('[application]\nconfig/name="Test"\n', encoding="utf-8")

    result = json.loads(server.preflight_project())

    assert result["project_path"] == str(tmp_path)
    assert result["configured_project_path"] == "/"
    assert result["project_godot_exists"] is True
    assert "GODOT_PROJECT resolved from cwd because configured value was not a Godot project" in result["warnings"]
