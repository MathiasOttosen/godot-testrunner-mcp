import socket
import threading
import json
import time
import subprocess
import pytest
from unittest.mock import MagicMock, patch


# ── Mock TCP server ────────────────────────────────────────────────────────────

class _MockServer:
    """Minimal TCP server that returns canned JSON responses one per request."""

    def __init__(self, port: int, responses: list[dict]):
        self.received: list[dict] = []
        self._responses = list(responses)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("localhost", port))
        self._sock.listen(1)
        self._sock.settimeout(3)
        threading.Thread(target=self._serve, daemon=True).start()
        time.sleep(0.05)

    def _serve(self):
        try:
            conn, _ = self._sock.accept()
            buf = b""
            for resp in self._responses:
                while b"\n" not in buf:
                    chunk = conn.recv(4096)
                    if not chunk:
                        return
                    buf += chunk
                line, buf = buf.split(b"\n", 1)
                self.received.append(json.loads(line))
                conn.sendall((json.dumps(resp) + "\n").encode())
            conn.close()
        except Exception:
            pass
        finally:
            try:
                self._sock.close()
            except Exception:
                pass


# ── EditorBridge tests ─────────────────────────────────────────────────────────

from server import EditorBridge


def test_transact_sends_json_and_returns_parsed_response():
    """_transact sends {"cmd": ..., ...params} and parses JSON response."""
    server = _MockServer(16001, [{"ok": True, "value": "pong"}])
    conn = socket.create_connection(("localhost", 16001), timeout=2)
    result = EditorBridge._transact(conn, "ping", {"x": 1})
    conn.close()
    assert result == {"ok": True, "value": "pong"}
    assert server.received[0] == {"cmd": "ping", "x": 1}


def test_send_editor_command_connection_refused():
    """Returns error dict when no server is listening on the editor port."""
    bridge = EditorBridge()
    bridge.EDITOR_PORT = 16002  # nothing listening here
    result = bridge.send_editor_command("get_ui", depth=1)
    assert result["ok"] is False
    assert "editor bridge not available" in result["error"]


def test_inspect_ui_scene_full_success():
    """Sends load_scene → get_ui → unload in a single connection, returns tree."""
    tree = {"name": "HUD", "type": "CanvasLayer", "children": []}
    server = _MockServer(16003, [
        {"ok": True},
        {"ok": True, "tree": tree},
        {"ok": True},
    ])
    bridge = EditorBridge()
    bridge.EDITOR_PORT = 16003
    result = bridge.inspect_ui_scene_full("scenes/hud.tscn", depth=1)
    assert result == {"ok": True, "tree": tree}
    assert [r["cmd"] for r in server.received] == ["load_scene", "get_ui", "unload"]
    assert server.received[0]["path"] == "scenes/hud.tscn"
    assert server.received[1]["depth"] == 1


def test_inspect_ui_scene_full_stops_on_load_failure():
    """Returns load error immediately without sending get_ui or unload."""
    server = _MockServer(16004, [{"ok": False, "error": "scene not found"}])
    bridge = EditorBridge()
    bridge.EDITOR_PORT = 16004
    result = bridge.inspect_ui_scene_full("missing.tscn", depth=1)
    assert result["ok"] is False
    assert "scene not found" in result["error"]
    assert len(server.received) == 1


def test_send_session_command_no_session():
    """Returns error dict when no session is active."""
    bridge = EditorBridge()
    result = bridge.send_session_command("get_ui", depth=1)
    assert result["ok"] is False
    assert "no active UI session" in result["error"]


def test_end_session_safe_when_no_session():
    """end_session() returns ok even when no session was started."""
    bridge = EditorBridge()
    result = bridge.end_session()
    assert result["ok"] is True


# ── inspect_ui_scene tests ─────────────────────────────────────────────────────

import server as srv


def test_inspect_ui_scene_path_traversal(monkeypatch, tmp_path):
    """Rejects paths that escape the project root."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)
    result = srv.inspect_ui_scene("../../etc/passwd")
    assert result.startswith("Error: path escapes project root")


def test_inspect_ui_scene_editor_not_running(monkeypatch, tmp_path):
    """Returns error string when EditorBridge cannot connect."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)
    srv._bridge.EDITOR_PORT = 16005  # nothing listening
    result = srv.inspect_ui_scene("scenes/menu.tscn")
    assert "editor bridge not available" in result


def test_inspect_ui_scene_returns_json_tree(monkeypatch, tmp_path):
    """Returns JSON string of the UI tree on success."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)

    tree = {"name": "Menu", "type": "Control", "children": []}
    srv._bridge.inspect_ui_scene_full = MagicMock(
        return_value={"ok": True, "tree": tree}
    )
    result = srv.inspect_ui_scene("scenes/menu.tscn", depth=2)
    assert json.loads(result) == tree
    srv._bridge.inspect_ui_scene_full.assert_called_once_with("scenes/menu.tscn", 2)


# ── Session MCP tool tests ─────────────────────────────────────────────────────

import server as srv
import importlib


def test_start_ui_session_timeout(monkeypatch, tmp_path):
    """Returns error string when game does not connect within timeout."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.start_session = MagicMock(
        return_value={"ok": False, "error": "game did not connect within 1s — check for autoload errors"}
    )
    result = srv.start_ui_session(timeout=1)
    assert "game did not connect within" in result


def test_start_ui_session_success(monkeypatch, tmp_path):
    """Returns confirmation string on successful session start."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/usr/bin/true")
    importlib.reload(srv)

    srv._bridge.start_session = MagicMock(return_value={"ok": True})
    result = srv.start_ui_session()
    assert "ready" in result.lower()


def test_end_ui_session(monkeypatch, tmp_path):
    """Calls bridge.end_session() and returns ok string."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.end_session = MagicMock(return_value={"ok": True})
    result = srv.end_ui_session()
    srv._bridge.end_session.assert_called_once()
    assert "ok" in result.lower() or result == "ok"


def test_navigate_ui_no_session(monkeypatch, tmp_path):
    """Returns error string when no session is active."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge._session_conn = None
    result = srv.navigate_ui("press_button", {"node_path": "Menu/Start"})
    assert "no active UI session" in result


def test_navigate_ui_change_scene(monkeypatch, tmp_path):
    """Routes change_scene action to change_scene command."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(return_value={"ok": True})
    srv._bridge._session_conn = MagicMock()
    result = srv.navigate_ui("change_scene", {"path": "scenes/game.tscn"})
    srv._bridge.send_session_command.assert_called_once_with(
        "change_scene", path="scenes/game.tscn"
    )
    assert result == "ok"


def test_navigate_ui_press_button(monkeypatch, tmp_path):
    """Routes press_button action to send_input command."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(return_value={"ok": True})
    srv._bridge._session_conn = MagicMock()
    result = srv.navigate_ui("press_button", {"node_path": "Menu/StartButton"})
    srv._bridge.send_session_command.assert_called_once_with(
        "send_input", action="press_button", params={"node_path": "Menu/StartButton"}
    )
    assert result == "ok"


def test_get_live_ui_no_session(monkeypatch, tmp_path):
    """Returns error string when no session is active."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge._session_conn = None
    result = srv.get_live_ui()
    assert "no active UI session" in result


def test_get_live_ui_returns_json(monkeypatch, tmp_path):
    """Returns JSON tree from session on success."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    tree = {"name": "GameHUD", "type": "CanvasLayer", "children": []}
    srv._bridge.send_session_command = MagicMock(
        return_value={"ok": True, "tree": tree}
    )
    srv._bridge._session_conn = MagicMock()
    result = srv.get_live_ui(depth=2)
    assert json.loads(result) == tree
    srv._bridge.send_session_command.assert_called_once_with("get_ui", depth=2)


def test_screenshot_ui_routes_to_bridge(monkeypatch, tmp_path):
    """screenshot_ui delegates to bridge.screenshot."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.screenshot = MagicMock(
        return_value={"ok": True, "path": "/tmp/shot.png"}
    )
    result = srv.screenshot_ui()
    srv._bridge.screenshot.assert_called_once()
    assert "/tmp/shot.png" in result


def test_screenshot_ui_error(monkeypatch, tmp_path):
    """Returns error string on screenshot failure."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.screenshot = MagicMock(
        return_value={"ok": False, "error": "no scene loaded"}
    )
    result = srv.screenshot_ui()
    assert "no scene loaded" in result
