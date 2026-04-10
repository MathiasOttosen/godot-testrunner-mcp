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


def test_inspect_ui_scene_full_unloads_on_get_ui_failure():
    """Sends unload even when get_ui fails, to leave the editor plugin clean."""
    server = _MockServer(16005, [
        {"ok": True},                          # load_scene
        {"ok": False, "error": "timed out"},   # get_ui
        {"ok": True},                          # unload
    ])
    bridge = EditorBridge()
    bridge.EDITOR_PORT = 16005
    result = bridge.inspect_ui_scene_full("scenes/hud.tscn", depth=1)
    assert result["ok"] is False
    assert "timed out" in result["error"]
    assert [r["cmd"] for r in server.received] == ["load_scene", "get_ui", "unload"]


def test_send_session_command_sets_socket_timeout():
    """send_session_command temporarily overrides and restores the socket timeout."""
    bridge = EditorBridge()
    conn_mock = MagicMock()
    bridge._session_conn = conn_mock

    with patch.object(EditorBridge, "_transact", return_value={"ok": True}) as transact:
        result = bridge.send_session_command("ping", socket_timeout=7.5, value=1)

    assert result == {"ok": True}
    transact.assert_called_once_with(conn_mock, "ping", {"value": 1})
    conn_mock.settimeout.assert_any_call(7.5)
    conn_mock.settimeout.assert_any_call(bridge.CONNECT_TIMEOUT)


def test_send_session_command_no_timeout_does_not_call_settimeout():
    """No settimeout call when socket_timeout is not provided."""
    bridge = EditorBridge()
    conn_mock = MagicMock()
    bridge._session_conn = conn_mock

    with patch.object(EditorBridge, "_transact", return_value={"ok": True}):
        bridge.send_session_command("ping")

    conn_mock.settimeout.assert_not_called()


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


def test_screenshot_ui_returns_json_with_metadata(monkeypatch, tmp_path):
    """screenshot_ui returns JSON dict with path, viewport_size, scene, frame."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.screenshot = MagicMock(
        return_value={
            "ok": True,
            "path": "/tmp/shot.png",
            "viewport_size": [1920, 1080],
            "scene": "res://scenes/game.tscn",
            "frame": 42,
        }
    )
    result = srv.screenshot_ui()
    data = json.loads(result)
    assert data["path"] == "/tmp/shot.png"
    assert data["viewport_size"] == [1920, 1080]
    assert data["scene"] == "res://scenes/game.tscn"
    assert data["frame"] == 42


def test_screenshot_ui_error_still_returns_error_string(monkeypatch, tmp_path):
    """screenshot_ui returns error string (not JSON) on failure."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.screenshot = MagicMock(
        return_value={"ok": False, "error": "no scene loaded"}
    )
    result = srv.screenshot_ui()
    assert "no scene loaded" in result
    assert not result.startswith("{")


def test_send_key_no_session(monkeypatch, tmp_path):
    """send_key returns error when no session is active."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge._session_conn = None
    result = srv.send_key("Right")
    assert "no active UI session" in result


def test_send_key_sends_correct_command(monkeypatch, tmp_path):
    """send_key forwards all params to send_key command."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(return_value={"ok": True})
    srv._bridge._session_conn = MagicMock()
    result = srv.send_key("Right", shift=True)
    srv._bridge.send_session_command.assert_called_once_with(
        "send_key", key="Right", pressed=True, shift=True, ctrl=False, alt=False, echo=False
    )
    assert result == "ok"


def test_send_mouse_sends_correct_command(monkeypatch, tmp_path):
    """send_mouse forwards x, y to send_mouse_move command."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(return_value={"ok": True})
    srv._bridge._session_conn = MagicMock()
    result = srv.send_mouse(100.0, 200.0)
    srv._bridge.send_session_command.assert_called_once_with(
        "send_mouse_move", x=100.0, y=200.0
    )
    assert result == "ok"


def test_click_sends_correct_command(monkeypatch, tmp_path):
    """click forwards x, y, button to click command."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(return_value={"ok": True})
    srv._bridge._session_conn = MagicMock()
    result = srv.click(50.0, 75.0, button=2)
    srv._bridge.send_session_command.assert_called_once_with(
        "click", x=50.0, y=75.0, button=2
    )
    assert result == "ok"


def test_drag_sends_correct_command(monkeypatch, tmp_path):
    """drag forwards all params to drag command."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(return_value={"ok": True})
    srv._bridge._session_conn = MagicMock()
    result = srv.drag(0.0, 0.0, 100.0, 200.0, steps=10)
    srv._bridge.send_session_command.assert_called_once_with(
        "drag", from_x=0.0, from_y=0.0, to_x=100.0, to_y=200.0, button=1, steps=10
    )
    assert result == "ok"


def test_get_node_no_session(monkeypatch, tmp_path):
    """get_node returns error when no session is active."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge._session_conn = None
    result = srv.get_node("Player")
    assert "no active UI session" in result


def test_get_node_success_returns_json(monkeypatch, tmp_path):
    """get_node returns JSON node data on success."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    node_data = {
        "name": "Player",
        "type": "CharacterBody2D",
        "path": "/root/Player",
        "position": [100.0, 200.0],
    }
    srv._bridge.send_session_command = MagicMock(return_value={"ok": True, "node": node_data})
    srv._bridge._session_conn = MagicMock()
    result = srv.get_node("Player")
    assert json.loads(result) == node_data
    srv._bridge.send_session_command.assert_called_once_with("get_node", node_path="Player")


def test_get_node_with_extra_properties(monkeypatch, tmp_path):
    """get_node passes properties list when provided."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(
        return_value={"ok": True, "node": {"name": "Player", "health": 100}}
    )
    srv._bridge._session_conn = MagicMock()
    srv.get_node("Player", properties=["health"])
    srv._bridge.send_session_command.assert_called_once_with(
        "get_node", node_path="Player", properties=["health"]
    )


def test_find_nodes_no_session(monkeypatch, tmp_path):
    """find_nodes returns error when no session is active."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge._session_conn = None
    result = srv.find_nodes(type="Label")
    assert "no active UI session" in result


def test_find_nodes_returns_json_array(monkeypatch, tmp_path):
    """find_nodes returns JSON array of {path, type} dicts."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    nodes = [{"path": "/root/HUD/Label", "type": "Label"}]
    srv._bridge.send_session_command = MagicMock(return_value={"ok": True, "nodes": nodes})
    srv._bridge._session_conn = MagicMock()
    result = srv.find_nodes(type="Label")
    assert json.loads(result) == nodes
    srv._bridge.send_session_command.assert_called_once_with("find_nodes", type="Label")


def test_find_nodes_omits_empty_filters(monkeypatch, tmp_path):
    """find_nodes does not send empty name/type params."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(return_value={"ok": True, "nodes": []})
    srv._bridge._session_conn = MagicMock()
    srv.find_nodes(name="Player")
    call_kwargs = srv._bridge.send_session_command.call_args.kwargs
    assert "name" in call_kwargs
    assert "type" not in call_kwargs


def test_await_frames_no_session(monkeypatch, tmp_path):
    """await_frames returns error when no session is active."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge._session_conn = None
    result = srv.await_frames(5)
    assert "no active UI session" in result


def test_await_frames_passes_socket_timeout(monkeypatch, tmp_path):
    """await_frames passes a socket_timeout of at least 10s."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(return_value={"ok": True})
    srv._bridge._session_conn = MagicMock()
    srv.await_frames(30)
    call_kwargs = srv._bridge.send_session_command.call_args.kwargs
    assert "socket_timeout" in call_kwargs
    assert call_kwargs["socket_timeout"] >= 10.0


def test_await_frames_sends_n(monkeypatch, tmp_path):
    """await_frames sends n to the await_frames command."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(return_value={"ok": True})
    srv._bridge._session_conn = MagicMock()
    srv.await_frames(10)
    srv._bridge.send_session_command.assert_called_once_with(
        "await_frames", socket_timeout=pytest.approx(10.0, abs=1.0), n=10
    )


def test_await_node_property_no_session(monkeypatch, tmp_path):
    """await_node_property returns error when no session is active."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge._session_conn = None
    result = srv.await_node_property("Player", "visible", True)
    assert "no active UI session" in result


def test_await_node_property_sends_correct_params(monkeypatch, tmp_path):
    """await_node_property sends params and passes socket_timeout."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(return_value={"ok": True})
    srv._bridge._session_conn = MagicMock()
    srv.await_node_property("Player", "visible", True, timeout=3.0)
    srv._bridge.send_session_command.assert_called_once_with(
        "await_node_property",
        socket_timeout=5.0,
        node_path="Player",
        property="visible",
        value=True,
        timeout=3.0,
    )


def test_await_signal_no_session(monkeypatch, tmp_path):
    """await_signal returns error when no session is active."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge._session_conn = None
    result = srv.await_signal("Player", "animation_finished")
    assert "no active UI session" in result


def test_await_signal_sends_correct_params(monkeypatch, tmp_path):
    """await_signal sends params and passes socket_timeout."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(return_value={"ok": True})
    srv._bridge._session_conn = MagicMock()
    srv.await_signal("Player", "animation_finished", timeout=4.0)
    srv._bridge.send_session_command.assert_called_once_with(
        "await_signal",
        socket_timeout=6.0,
        node_path="Player",
        signal="animation_finished",
        timeout=4.0,
    )


def test_call_node_method_no_session(monkeypatch, tmp_path):
    """call_node_method returns error when no session is active."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge._session_conn = None
    result = srv.call_node_method("Player", "get_health")
    assert "no active UI session" in result


def test_call_node_method_returns_json_result(monkeypatch, tmp_path):
    """call_node_method returns JSON-encoded return value on success."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(return_value={"ok": True, "result": 42})
    srv._bridge._session_conn = MagicMock()
    result = srv.call_node_method("Player", "get_health")
    assert json.loads(result) == 42
    srv._bridge.send_session_command.assert_called_once_with(
        "call_node_method", node_path="Player", method="get_health", args=[]
    )


def test_call_node_method_passes_args(monkeypatch, tmp_path):
    """call_node_method passes args list to command."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(return_value={"ok": True, "result": None})
    srv._bridge._session_conn = MagicMock()
    srv.call_node_method("Player", "take_damage", args=[10])
    srv._bridge.send_session_command.assert_called_once_with(
        "call_node_method", node_path="Player", method="take_damage", args=[10]
    )


def test_call_node_method_error_propagates(monkeypatch, tmp_path):
    """call_node_method returns error string when Godot reports method not found."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(
        return_value={"ok": False, "error": "method not found: fly"}
    )
    srv._bridge._session_conn = MagicMock()
    result = srv.call_node_method("Player", "fly")
    assert "method not found" in result
