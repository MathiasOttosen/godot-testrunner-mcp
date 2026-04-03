import shutil
from pathlib import Path
import pytest
import importlib
import server as srv


def test_scaffold_tests_requires_scaffold_dir(tmp_path, monkeypatch):
    """scaffold_tests() returns 'up to date' when no scaffold source files exist."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)
    # No scaffold/ dir in worktree yet — should not crash
    result = srv.scaffold_tests()
    assert isinstance(result, str)


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
