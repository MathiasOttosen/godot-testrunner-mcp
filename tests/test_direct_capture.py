import json
from unittest.mock import MagicMock

import server


def test_capture_scene_starts_ui_session_waits_screenshots_and_ends(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/usr/bin/false")
    (tmp_path / "scenes").mkdir()
    (tmp_path / "scenes" / "night_zero.tscn").touch()
    screenshot_path = tmp_path / "tests" / "ui_screenshots" / "night_zero.png"

    bridge = MagicMock()
    bridge.start_session.return_value = {"ok": True, "status": "ready", "command": ["/bin/false"]}
    bridge.send_session_command.return_value = {"ok": True}
    bridge.screenshot.return_value = {
        "ok": True,
        "path": str(screenshot_path),
        "viewport_size": [320, 180],
        "scene": "res://scenes/night_zero.tscn",
        "frame": 4,
    }
    monkeypatch.setattr(server, "_bridge", bridge)

    result = json.loads(server.capture_scene("scenes/night_zero.tscn", "tests/ui_screenshots/night_zero.png"))

    assert result["status"] == "captured"
    assert result["scene_path"] == "scenes/night_zero.tscn"
    assert result["screenshot_path"] == str(screenshot_path)
    bridge.start_session.assert_called_once_with(
        "/usr/bin/false",
        str(tmp_path),
        "scenes/night_zero.tscn",
        15,
        launch_mode="ui",
    )
    bridge.send_session_command.assert_called_once_with("await_frames", socket_timeout=10.0, n=3)
    bridge.screenshot.assert_called_once_with("tests/ui_screenshots/night_zero.png", str(tmp_path))
    bridge.end_session.assert_called_once()


def test_capture_scene_returns_launch_failure_without_waiting_or_screenshot(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/usr/bin/false")
    (tmp_path / "scenes").mkdir()
    (tmp_path / "scenes" / "room.tscn").touch()

    bridge = MagicMock()
    bridge.start_session.return_value = {
        "ok": False,
        "status": "launch_failed_autoload_exit",
        "summary": "headless tests exited",
    }
    monkeypatch.setattr(server, "_bridge", bridge)

    result = json.loads(server.capture_scene("scenes/room.tscn"))

    assert result["status"] == "launch_failed_autoload_exit"
    assert result["error"] == "launch_failed"
    bridge.send_session_command.assert_not_called()
    bridge.screenshot.assert_not_called()
    bridge.end_session.assert_not_called()


def test_capture_scene_always_ends_after_successful_launch_when_screenshot_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/usr/bin/false")
    (tmp_path / "scenes").mkdir()
    (tmp_path / "scenes" / "room.tscn").touch()

    bridge = MagicMock()
    bridge.start_session.return_value = {"ok": True, "status": "ready"}
    bridge.send_session_command.return_value = {"ok": True}
    bridge.screenshot.return_value = {"ok": False, "error": "no viewport"}
    monkeypatch.setattr(server, "_bridge", bridge)

    result = json.loads(server.capture_scene("scenes/room.tscn"))

    assert result["error"] == "screenshot_failed"
    assert result["message"] == "no viewport"
    bridge.end_session.assert_called_once()


def test_capture_scene_rejects_paths_outside_project(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/usr/bin/false")

    result = server.capture_scene("../outside.tscn")

    assert result == "Error: path escapes project root"
