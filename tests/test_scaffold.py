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
