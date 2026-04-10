import shutil
from pathlib import Path
import pytest
import importlib
import server as srv


def test_scaffold_tests_creates_core_files(tmp_path, monkeypatch):
    """scaffold_tests() copies base_test.gd, test_runner.gd, smoke_runner.gd."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)
    result = srv.scaffold_tests()
    assert (tmp_path / "tests" / "base_test.gd").exists()
    assert (tmp_path / "tests" / "test_runner.gd").exists()
    assert (tmp_path / "tests" / "smoke" / "smoke_runner.gd").exists()
    assert "base_test.gd" in result


def test_check_scaffold_reports_missing(tmp_path, monkeypatch):
    """check_scaffold() reports missing when test infrastructure not present."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)
    result = srv.check_scaffold()
    assert "missing" in result.lower()


def test_safe_path_allows_valid(tmp_path, monkeypatch):
    """safe_path returns a Path for valid relative paths inside project root."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)
    result = srv.safe_path("scenes/menu.tscn")
    assert result is not None
    assert str(result).startswith(str(tmp_path))


def test_safe_path_blocks_traversal(tmp_path, monkeypatch):
    """safe_path returns None for paths that escape the project root."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)
    result = srv.safe_path("../../etc/passwd")
    assert result is None


# ── UI verification scaffold tests ────────────────────────────────────────────

def test_scaffold_tests_creates_addon_files(tmp_path, monkeypatch):
    """scaffold_tests() copies addon files to addons/."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv.scaffold_tests()

    assert (tmp_path / "addons" / "godot_mcp" / "plugin.cfg").exists()
    assert (tmp_path / "addons" / "godot_mcp" / "plugin.gd").exists()
    assert (tmp_path / "addons" / "godot_mcp" / "remote_control.gd").exists()
    assert (tmp_path / "addons" / "godot_mcp" / "mcp_tree.gd").exists()


def test_scaffold_tests_creates_screenshots_dir(tmp_path, monkeypatch):
    """scaffold_tests() creates tests/ui_screenshots/ directory."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv.scaffold_tests()

    assert (tmp_path / "tests" / "ui_screenshots").is_dir()


def test_scaffold_tests_registers_remote_control_autoload(tmp_path, monkeypatch):
    """scaffold_tests() adds GodotMCPRemoteControl autoload to project.godot."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    (tmp_path / "project.godot").write_text(
        '[application]\nconfig/name="Test"\n\n[autoload]\n', encoding="utf-8"
    )
    srv.scaffold_tests()

    content = (tmp_path / "project.godot").read_text(encoding="utf-8")
    assert "GodotMCPRemoteControl" in content


def test_scaffold_tests_enables_editor_plugin(tmp_path, monkeypatch):
    """scaffold_tests() adds godot_mcp to [editor_plugins] in project.godot."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    (tmp_path / "project.godot").write_text(
        '[application]\nconfig/name="Test"\n', encoding="utf-8"
    )
    srv.scaffold_tests()

    content = (tmp_path / "project.godot").read_text(encoding="utf-8")
    assert "[editor_plugins]" in content
    assert "res://addons/godot_mcp/plugin.cfg" in content


def test_check_scaffold_detects_missing_addon_files(tmp_path, monkeypatch):
    """check_scaffold() reports missing when addon files are absent."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    # Install core scaffold only (no addons)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "base_test.gd").write_text('const SCAFFOLD_VERSION = "1.0"', encoding="utf-8")
    (tmp_path / "tests" / "test_runner.gd").touch()
    (tmp_path / "tests" / "smoke").mkdir()
    (tmp_path / "tests" / "smoke" / "smoke_runner.gd").touch()

    result = srv.check_scaffold()
    assert "plugin.gd" in result or "missing" in result.lower()


def test_scaffold_tests_creates_mcp_tree(tmp_path, monkeypatch):
    """scaffold_tests() copies mcp_tree.gd to addons/godot_mcp/."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv.scaffold_tests()

    assert (tmp_path / "addons" / "godot_mcp" / "mcp_tree.gd").exists()


def test_check_scaffold_detects_missing_mcp_tree(tmp_path, monkeypatch):
    """check_scaffold() reports missing when mcp_tree.gd is absent."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    addon_dir = tmp_path / "addons" / "godot_mcp"
    addon_dir.mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "base_test.gd").write_text(
        'const SCAFFOLD_VERSION = "1.0"', encoding="utf-8"
    )
    (tmp_path / "tests" / "test_runner.gd").touch()
    (tmp_path / "tests" / "smoke").mkdir()
    (tmp_path / "tests" / "smoke" / "smoke_runner.gd").touch()
    for fname in ("plugin.cfg", "plugin.gd", "remote_control.gd"):
        (addon_dir / fname).touch()

    result = srv.check_scaffold()
    assert "mcp_tree.gd" in result or "missing" in result.lower()
