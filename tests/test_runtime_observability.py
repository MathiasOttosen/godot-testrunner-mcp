import json
from unittest.mock import MagicMock

import server


def test_start_ui_session_adds_elapsed_seconds(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/usr/bin/false")
    bridge = MagicMock()
    bridge.start_session.return_value = {"ok": True, "status": "ready"}
    monkeypatch.setattr(server, "_bridge", bridge)
    ticks = iter([10.0, 10.25])
    monkeypatch.setattr(server.time, "monotonic", lambda: next(ticks))

    result = json.loads(server.start_ui_session())

    assert result["elapsed_seconds"] == 0.25


def test_get_session_status_reports_no_active_session(monkeypatch):
    bridge = server.EditorBridge()
    monkeypatch.setattr(server, "_bridge", bridge)

    result = json.loads(server.get_session_status())

    assert result["session_active"] is False
    assert result["process_running"] is False
    assert result["last_launch"] is None


def test_get_session_status_reports_live_session_and_last_launch(monkeypatch):
    bridge = server.EditorBridge()
    bridge._session_conn = MagicMock()
    proc = MagicMock()
    proc.poll.return_value = None
    bridge._session_proc = proc
    bridge._last_launch_result = {
        "ok": True,
        "status": "ready",
        "command": ["/usr/bin/false", "--path", "/tmp/project"],
    }
    monkeypatch.setattr(server, "_bridge", bridge)

    result = json.loads(server.get_session_status())

    assert result["session_active"] is True
    assert result["process_running"] is True
    assert result["last_launch"]["status"] == "ready"


def test_editor_bridge_remembers_failed_launch_result():
    bridge = server.EditorBridge()

    observation = server._LaunchObservation(command=["godot"])
    result = bridge._finalize_failed_launch(observation, status="launch_failed_timeout")

    assert bridge._last_launch_result == result
    assert bridge._last_launch_result["status"] == "launch_failed_timeout"
