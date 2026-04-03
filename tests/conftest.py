import os
import pytest


@pytest.fixture(autouse=True)
def set_env_vars(tmp_path, monkeypatch):
    """Set required env vars for tests that don't set their own."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
