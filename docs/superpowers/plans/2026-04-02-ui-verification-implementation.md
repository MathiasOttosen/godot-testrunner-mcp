# UI Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add runtime UI verification to godot-mcp — an EditorPlugin (port 6789) for fast scene inspection and a RemoteControl autoload (port 6790) for full game-flow sessions with input simulation.

**Architecture:** `EditorBridge` Python class in `server.py` manages both TCP connections. Six new MCP tools wrap it. Two new GDScript files are installed into target projects by the existing `scaffold_tests()` tool.

**Tech Stack:** Python 3.12, FastMCP ≥3.1.1, stdlib `socket`/`subprocess`/`json`, GDScript 4, Godot 4 TCPServer/StreamPeerTCP.

**Prerequisite:** The existing implementation plan (`2026-03-29-godot-mcp-implementation.md`) must be complete. This plan assumes `server.py` has `GODOT_BIN`, `GODOT_PROJECT`, `safe_path()`, `scaffold_tests()`, and `check_scaffold()` already implemented, and that `scaffold/` exists with `base_test.gd`, `test_runner.gd`, and `smoke_runner.gd`.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `server.py` | Modify | Add `EditorBridge` class + 6 new MCP tools; extend `scaffold_tests()` and `check_scaffold()` |
| `tests/test_ui_verification.py` | Create | pytest tests for EditorBridge and all 6 MCP tools |
| `tests/test_scaffold.py` | Modify | Add tests for new scaffold files and autoload registration |
| `scaffold/addons/godot_mcp/plugin.cfg` | Create | EditorPlugin metadata (required by Godot) |
| `scaffold/addons/godot_mcp/plugin.gd` | Create | EditorPlugin: TCP server on :6789, SubViewport scene inspection |
| `scaffold/addons/godot_mcp/remote_control.gd` | Create | Autoload: TCP server on :6790, live game session control |

---

## Task 1: `EditorBridge` Python class

**Files:**
- Modify: `server.py` (add class before tool definitions)
- Create: `tests/test_ui_verification.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui_verification.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/kognido/game dev/godot-mcp"
uv run pytest tests/test_ui_verification.py -v 2>&1 | head -40
```

Expected: `ImportError: cannot import name 'EditorBridge' from 'server'`

- [ ] **Step 3: Implement `EditorBridge` in `server.py`**

Add this class after the existing imports and constants, before the first `@mcp.tool` definition:

```python
import socket
import json
import time


class EditorBridge:
    """Manages TCP connections to the Godot EditorPlugin (:6789) and
    the in-game RemoteControl autoload (:6790)."""

    EDITOR_PORT: int = 6789
    REMOTE_PORT: int = 6790
    CONNECT_TIMEOUT: float = 2.0

    def __init__(self) -> None:
        self._session_conn: socket.socket | None = None
        self._session_proc: object | None = None  # subprocess.Popen

    # ── Editor (stateless, per-call connection) ────────────────────────────

    def send_editor_command(self, cmd: str, **params) -> dict:
        """Open a connection to the EditorPlugin, send one command, return response."""
        try:
            with socket.create_connection(
                ("localhost", self.EDITOR_PORT), timeout=self.CONNECT_TIMEOUT
            ) as conn:
                return self._transact(conn, cmd, params)
        except ConnectionRefusedError:
            return {
                "ok": False,
                "error": "editor bridge not available — is the Godot editor open?",
            }
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    def inspect_ui_scene_full(self, path: str, depth: int) -> dict:
        """Load scene, capture UI tree, unload — all in one connection."""
        try:
            with socket.create_connection(
                ("localhost", self.EDITOR_PORT), timeout=self.CONNECT_TIMEOUT
            ) as conn:
                r = self._transact(conn, "load_scene", {"path": path})
                if not r["ok"]:
                    return r
                r = self._transact(conn, "get_ui", {"depth": depth})
                if not r["ok"]:
                    return r
                tree = r["tree"]
                self._transact(conn, "unload", {})
                return {"ok": True, "tree": tree}
        except ConnectionRefusedError:
            return {
                "ok": False,
                "error": "editor bridge not available — is the Godot editor open?",
            }
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    # ── Session (persistent connection to running game) ────────────────────

    def start_session(
        self, godot_bin: str, project_path: str, scene_path: str, timeout: int
    ) -> dict:
        """Launch game with --mcp flag, wait for RemoteControl to connect."""
        import subprocess

        args = [godot_bin, "--path", project_path, "--", "--mcp"]
        if scene_path:
            args += ["--mcp-scene", scene_path]
        self._session_proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                conn = socket.create_connection(
                    ("localhost", self.REMOTE_PORT), timeout=1.0
                )
                self._session_conn = conn
                return {"ok": True}
            except (ConnectionRefusedError, OSError):
                time.sleep(0.5)
        self._session_proc.kill()
        self._session_proc = None
        return {
            "ok": False,
            "error": f"game did not connect within {timeout}s — check for autoload errors",
        }

    def send_session_command(self, cmd: str, **params) -> dict:
        """Send a command to the active game session."""
        if self._session_conn is None:
            return {
                "ok": False,
                "error": "no active UI session — call start_ui_session first",
            }
        try:
            return self._transact(self._session_conn, cmd, params)
        except OSError:
            self._session_conn = None
            return {
                "ok": False,
                "error": "session disconnected — call start_ui_session to reconnect",
            }

    def end_session(self) -> dict:
        """Send quit to game and close connection."""
        if self._session_conn is not None:
            try:
                self._transact(self._session_conn, "quit", {})
            except OSError:
                pass
            try:
                self._session_conn.close()
            except OSError:
                pass
            self._session_conn = None
        if self._session_proc is not None:
            try:
                self._session_proc.wait(timeout=5)
            except Exception:
                self._session_proc.kill()
            self._session_proc = None
        return {"ok": True}

    def screenshot(self, save_path: str, project_path: str) -> dict:
        """Capture from active game session if running, else from editor plugin."""
        resolved = save_path or self._default_screenshot_path(project_path)
        if self._session_conn is not None:
            return self.send_session_command("screenshot", save_path=resolved)
        return self.send_editor_command("screenshot", save_path=resolved)

    # ── Shared helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _transact(conn: socket.socket, cmd: str, params: dict) -> dict:
        msg = json.dumps({"cmd": cmd, **params}) + "\n"
        conn.sendall(msg.encode())
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                raise OSError("connection closed before response")
            buf += chunk
        return json.loads(buf.split(b"\n")[0])

    @staticmethod
    def _default_screenshot_path(project_path: str) -> str:
        from pathlib import Path
        from datetime import datetime

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(Path(project_path) / "tests" / "ui_screenshots" / f"{ts}.png")


_bridge = EditorBridge()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd "/Users/kognido/game dev/godot-mcp"
uv run pytest tests/test_ui_verification.py -v 2>&1 | head -40
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
cd "/Users/kognido/game dev/godot-mcp"
git add server.py tests/test_ui_verification.py
git commit -m "feat: add EditorBridge class for UI verification TCP connections"
```

---

## Task 2: `inspect_ui_scene` MCP tool

**Files:**
- Modify: `server.py` (add tool)
- Modify: `tests/test_ui_verification.py` (add tests)

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_ui_verification.py`:

```python
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
    (tmp_path / "scenes").mkdir()
    (tmp_path / "scenes" / "menu.tscn").touch()
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/kognido/game dev/godot-mcp"
uv run pytest tests/test_ui_verification.py::test_inspect_ui_scene_path_traversal tests/test_ui_verification.py::test_inspect_ui_scene_editor_not_running tests/test_ui_verification.py::test_inspect_ui_scene_returns_json_tree -v 2>&1 | head -30
```

Expected: `AttributeError: module 'server' has no attribute 'inspect_ui_scene'`

- [ ] **Step 3: Implement the tool in `server.py`**

Add after the `_bridge = EditorBridge()` line:

```python
@mcp.tool()
def inspect_ui_scene(path: str, depth: int = 1) -> str:
    """Load a Godot scene into the editor's SubViewport and return its UI node tree as JSON.
    path is relative to the project root (e.g. 'scenes/hud.tscn').
    depth controls how many levels of children to include; default 1 = top-level only.
    Each call is a full load/unload cycle — any previously loaded scene is unloaded first.
    Requires the Godot editor to be open with the project loaded.
    Use this after editing a .tscn file or a script that populates UI in _ready."""
    safe = safe_path(path)
    if safe is None:
        return "Error: path escapes project root"
    result = _bridge.inspect_ui_scene_full(path, depth)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return json.dumps(result["tree"], indent=2)
```

Also add `import json` at the top of `server.py` if not already present.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd "/Users/kognido/game dev/godot-mcp"
uv run pytest tests/test_ui_verification.py -v 2>&1 | head -40
```

Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
cd "/Users/kognido/game dev/godot-mcp"
git add server.py tests/test_ui_verification.py
git commit -m "feat: add inspect_ui_scene MCP tool"
```

---

## Task 3: `plugin.gd` EditorPlugin (GDScript)

**Files:**
- Create: `scaffold/addons/godot_mcp/plugin.cfg`
- Create: `scaffold/addons/godot_mcp/plugin.gd`

No pytest tests for GDScript. Verified manually via MCP Inspector after scaffold installation.

- [ ] **Step 1: Create the addon directory**

```bash
mkdir -p "/Users/kognido/game dev/godot-mcp/scaffold/addons/godot_mcp"
```

- [ ] **Step 2: Create `scaffold/addons/godot_mcp/plugin.cfg`**

```ini
[plugin]

name="godot_mcp"
description="MCP remote control and UI inspection for godot-mcp"
author="godot-mcp"
version="1.0"
script="plugin.gd"
```

- [ ] **Step 3: Create `scaffold/addons/godot_mcp/plugin.gd`**

```gdscript
@tool
extends EditorPlugin

const PORT := 6789
const READY_FRAMES := 3

var _server: TCPServer
var _peer: StreamPeerTCP
var _viewport: SubViewport
var _scene_root: Node
var _pending_load_response := false
var _load_frame_count := 0


func _enter_tree() -> void:
	set_process(true)
	_server = TCPServer.new()
	var err := _server.listen(PORT)
	if err != OK:
		push_error("godot-mcp plugin: failed to listen on port %d (err %d)" % [PORT, err])


func _exit_tree() -> void:
	set_process(false)
	_unload_scene()
	if _peer:
		_peer.disconnect_from_host()
		_peer = null
	if _server:
		_server.stop()
		_server = null


func _process(_delta: float) -> void:
	# Accept new connection (one at a time)
	if _server and _server.is_connection_available():
		if _peer:
			_peer.disconnect_from_host()
		_peer = _server.take_connection()

	if not (_peer and _peer.get_status() == StreamPeerTCP.STATUS_CONNECTED):
		return

	# Advance frame counter for pending load_scene response
	if _pending_load_response:
		_load_frame_count += 1
		if _load_frame_count >= READY_FRAMES:
			_pending_load_response = false
			_load_frame_count = 0
			_respond({"ok": true})
		return  # don't read new commands while waiting

	# Read incoming data
	var available := _peer.get_available_bytes()
	if available <= 0:
		return
	var res := _peer.get_data(available)
	if res[0] != OK:
		return
	var raw: String = res[1].get_string_from_utf8()
	for line in raw.split("\n", false):
		line = line.strip_edges()
		if line != "":
			_handle_command(line)


func _handle_command(raw: String) -> void:
	var parsed = JSON.parse_string(raw)
	if parsed == null:
		_respond({"ok": false, "error": "invalid JSON"})
		return
	match parsed.get("cmd", ""):
		"load_scene":
			_cmd_load_scene(parsed.get("path", ""))
		"get_ui":
			_cmd_get_ui(int(parsed.get("depth", 1)))
		"screenshot":
			_cmd_screenshot(parsed.get("save_path", ""))
		"unload":
			_unload_scene()
			_respond({"ok": true})
		_:
			_respond({"ok": false, "error": "unknown command: " + str(parsed.get("cmd", ""))})


func _cmd_load_scene(path: String) -> void:
	_unload_scene()
	var full_path := "res://" + path
	var packed = ResourceLoader.load(full_path)
	if packed == null:
		_respond({"ok": false, "error": "failed to load scene: " + path})
		return

	_viewport = SubViewport.new()
	_viewport.size = Vector2i(1920, 1080)
	_viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	add_child(_viewport)

	_scene_root = packed.instantiate()
	_viewport.add_child(_scene_root)

	# Response is deferred — sent after READY_FRAMES ticks in _process
	_pending_load_response = true
	_load_frame_count = 0


func _cmd_get_ui(depth: int) -> void:
	if _scene_root == null:
		_respond({"ok": false, "error": "no scene loaded — call load_scene first"})
		return
	_respond({"ok": true, "tree": _get_ui_tree(_scene_root, depth)})


func _cmd_screenshot(save_path: String) -> void:
	if _viewport == null:
		_respond({"ok": false, "error": "no scene loaded — call load_scene first"})
		return
	var img := _viewport.get_texture().get_image()
	var path := save_path if save_path != "" else _default_screenshot_path()
	var err := img.save_png(path)
	if err != OK:
		_respond({"ok": false, "error": "failed to save screenshot to: " + path})
		return
	_respond({"ok": true, "path": path})


func _unload_scene() -> void:
	if _scene_root:
		_scene_root.queue_free()
		_scene_root = null
	if _viewport:
		_viewport.queue_free()
		_viewport = null


func _get_ui_tree(node: Node, depth: int) -> Dictionary:
	var d: Dictionary = {
		"name": node.name,
		"type": node.get_class(),
		"children": [],
	}
	if node is CanvasItem:
		d["visible"] = (node as CanvasItem).visible
	if node is Control:
		var c := node as Control
		d["position"] = [c.position.x, c.position.y]
		d["size"] = [c.size.x, c.size.y]
	if node is Label:
		d["text"] = (node as Label).text
	elif node is Button:
		d["text"] = (node as Button).text
	elif node is LineEdit:
		d["text"] = (node as LineEdit).text
	elif node is RichTextLabel:
		d["text"] = (node as RichTextLabel).text
	if depth > 0:
		for child in node.get_children():
			if child is CanvasItem:
				d["children"].append(_get_ui_tree(child, depth - 1))
	return d


func _respond(data: Dictionary) -> void:
	if _peer and _peer.get_status() == StreamPeerTCP.STATUS_CONNECTED:
		var msg := JSON.stringify(data) + "\n"
		_peer.put_data(msg.to_utf8_buffer())


func _default_screenshot_path() -> String:
	var project := ProjectSettings.globalize_path("res://")
	var ts := Time.get_datetime_string_from_system(false, true).replace(":", "").replace("-", "")
	return project.path_join("tests/ui_screenshots/%s.png" % ts)
```

- [ ] **Step 4: Commit**

```bash
cd "/Users/kognido/game dev/godot-mcp"
git add scaffold/addons/godot_mcp/plugin.cfg scaffold/addons/godot_mcp/plugin.gd
git commit -m "feat: add EditorPlugin scaffold for scene inspection (port 6789)"
```

---

## Task 4: Session MCP tools + tests

**Files:**
- Modify: `server.py` (add 5 tools)
- Modify: `tests/test_ui_verification.py` (add tests)

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_ui_verification.py`:

```python
# ── Session MCP tool tests ─────────────────────────────────────────────────────


def test_start_ui_session_timeout(monkeypatch, tmp_path):
    """Returns error string when game does not connect within timeout."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)

    # Patch start_session to simulate timeout immediately
    srv._bridge.start_session = MagicMock(
        return_value={"ok": False, "error": "game did not connect within 1s — check for autoload errors"}
    )
    result = srv.start_ui_session(timeout=1)
    assert "game did not connect within" in result


def test_start_ui_session_success(monkeypatch, tmp_path):
    """Returns confirmation string on successful session start."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/usr/bin/true")
    import importlib
    importlib.reload(srv)

    srv._bridge.start_session = MagicMock(return_value={"ok": True})
    result = srv.start_ui_session()
    assert "ready" in result.lower()


def test_end_ui_session(monkeypatch, tmp_path):
    """Calls bridge.end_session() and returns ok string."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)

    srv._bridge.end_session = MagicMock(return_value={"ok": True})
    result = srv.end_ui_session()
    srv._bridge.end_session.assert_called_once()
    assert "ok" in result.lower() or result == "ok"


def test_navigate_ui_no_session(monkeypatch, tmp_path):
    """Returns error string when no session is active."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)

    srv._bridge._session_conn = None
    result = srv.navigate_ui("press_button", {"node_path": "Menu/Start"})
    assert "no active UI session" in result


def test_navigate_ui_change_scene(monkeypatch, tmp_path):
    """Routes change_scene action to change_scene command."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
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
    import importlib
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
    import importlib
    importlib.reload(srv)

    srv._bridge._session_conn = None
    result = srv.get_live_ui()
    assert "no active UI session" in result


def test_get_live_ui_returns_json(monkeypatch, tmp_path):
    """Returns JSON tree from session on success."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)

    tree = {"name": "GameHUD", "type": "CanvasLayer", "children": []}
    srv._bridge.send_session_command = MagicMock(
        return_value={"ok": True, "tree": tree}
    )
    srv._bridge._session_conn = MagicMock()
    result = srv.get_live_ui(depth=2)
    assert json.loads(result) == tree
    srv._bridge.send_session_command.assert_called_once_with("get_ui", depth=2)


def test_screenshot_ui_prefers_session(monkeypatch, tmp_path):
    """When session is active, screenshot goes to session not editor."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
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
    import importlib
    importlib.reload(srv)

    srv._bridge.screenshot = MagicMock(
        return_value={"ok": False, "error": "no scene loaded"}
    )
    result = srv.screenshot_ui()
    assert "no scene loaded" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/kognido/game dev/godot-mcp"
uv run pytest tests/test_ui_verification.py -k "session or navigate or live_ui or screenshot_ui" -v 2>&1 | head -30
```

Expected: `AttributeError: module 'server' has no attribute 'start_ui_session'`

- [ ] **Step 3: Implement the 5 tools in `server.py`**

Add after `inspect_ui_scene`:

```python
@mcp.tool()
def start_ui_session(scene_path: str = "", timeout: int = 15) -> str:
    """Launch the Godot game with the --mcp flag and wait for the RemoteControl autoload
    to connect on localhost:6790. If scene_path is given (relative to project root),
    the game navigates to that scene after connecting.
    Returns confirmation when the session is ready.
    The Godot editor does NOT need to be open for this tool."""
    if scene_path:
        safe = safe_path(scene_path)
        if safe is None:
            return "Error: path escapes project root"
    result = _bridge.start_session(GODOT_BIN, GODOT_PROJECT, scene_path, timeout)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "Session ready — call get_live_ui, navigate_ui, or screenshot_ui."


@mcp.tool()
def end_ui_session() -> str:
    """Send quit to the running game and close the RemoteControl connection.
    Safe to call even if no session is active."""
    _bridge.end_session()
    return "ok"


@mcp.tool()
def navigate_ui(action: str, params: dict = {}) -> str:
    """Send a navigation or input command to the active UI session.
    Requires an active session started by start_ui_session.

    action values:
      'change_scene' — params: {"path": "scenes/gameplay.tscn"}
      'press_button' — params: {"node_path": "MainMenu/StartButton"}
      'input_action' — params: {"action": "ui_accept"}
    """
    if action == "change_scene":
        result = _bridge.send_session_command("change_scene", path=params.get("path", ""))
    else:
        result = _bridge.send_session_command("send_input", action=action, params=params)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"


@mcp.tool()
def get_live_ui(depth: int = 1) -> str:
    """Return the current UI node tree from the active game session as JSON.
    depth controls how many levels of children to include; default 1 = top-level only.
    Requires an active session started by start_ui_session.
    Call this after navigate_ui to verify the UI changed as expected."""
    result = _bridge.send_session_command("get_ui", depth=depth)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return json.dumps(result["tree"], indent=2)


@mcp.tool()
def screenshot_ui(save_path: str = "") -> str:
    """Capture the current viewport as a PNG and return the absolute path to the saved file.
    If save_path is empty, saves to tests/ui_screenshots/<timestamp>.png in the project root.
    Uses the active game session if running; otherwise captures from the editor plugin's SubViewport.
    Call inspect_ui_scene or start_ui_session first."""
    result = _bridge.screenshot(save_path, GODOT_PROJECT)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return result["path"]
```

- [ ] **Step 4: Run all tests**

```bash
cd "/Users/kognido/game dev/godot-mcp"
uv run pytest tests/test_ui_verification.py -v 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
cd "/Users/kognido/game dev/godot-mcp"
git add server.py tests/test_ui_verification.py
git commit -m "feat: add session MCP tools (start_ui_session, navigate_ui, get_live_ui, screenshot_ui, end_ui_session)"
```

---

## Task 5: `remote_control.gd` autoload (GDScript)

**Files:**
- Create: `scaffold/addons/godot_mcp/remote_control.gd`

No pytest tests. Verified after scaffold installation by running `start_ui_session` against a real project.

- [ ] **Step 1: Create `scaffold/addons/godot_mcp/remote_control.gd`**

```gdscript
extends Node
## RemoteControl: activated by --mcp CLI flag.
## Starts a TCP server on localhost:6790 for MCP session commands.
## Registered as an autoload by scaffold_tests() — dormant unless --mcp is present.

const PORT := 6790

var _server: TCPServer
var _peer: StreamPeerTCP


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	if "--mcp" not in args:
		return  # dormant in normal gameplay

	_server = TCPServer.new()
	var err := _server.listen(PORT)
	if err != OK:
		push_error("godot-mcp remote_control: failed to listen on port %d (err %d)" % [PORT, err])
		return

	set_process(true)

	# Navigate to initial scene if --mcp-scene was provided
	var idx := args.find("--mcp-scene")
	if idx != -1 and idx + 1 < args.size():
		var scene_path: String = "res://" + args[idx + 1]
		get_tree().change_scene_to_file(scene_path)


func _process(_delta: float) -> void:
	if _server == null:
		return
	if _server.is_connection_available():
		if _peer:
			_peer.disconnect_from_host()
		_peer = _server.take_connection()

	if not (_peer and _peer.get_status() == StreamPeerTCP.STATUS_CONNECTED):
		return

	var available := _peer.get_available_bytes()
	if available <= 0:
		return
	var res := _peer.get_data(available)
	if res[0] != OK:
		return
	var raw: String = res[1].get_string_from_utf8()
	for line in raw.split("\n", false):
		line = line.strip_edges()
		if line != "":
			_handle_command(line)


func _handle_command(raw: String) -> void:
	var parsed = JSON.parse_string(raw)
	if parsed == null:
		_respond({"ok": false, "error": "invalid JSON"})
		return
	match parsed.get("cmd", ""):
		"get_ui":
			var root := get_tree().current_scene
			if root == null:
				_respond({"ok": false, "error": "no current scene"})
			else:
				_respond({"ok": true, "tree": _get_ui_tree(root, int(parsed.get("depth", 1)))})
		"change_scene":
			var path: String = "res://" + parsed.get("path", "")
			get_tree().change_scene_to_file(path)
			_respond({"ok": true})
		"send_input":
			_cmd_send_input(parsed)
		"screenshot":
			_cmd_screenshot(parsed.get("save_path", ""))
		"quit":
			_respond({"ok": true})
			await get_tree().process_frame
			get_tree().quit()
		_:
			_respond({"ok": false, "error": "unknown command: " + str(parsed.get("cmd", ""))})


func _cmd_send_input(params: Dictionary) -> void:
	var action: String = params.get("action", "")
	var p: Dictionary = params.get("params", {})
	match action:
		"press_button":
			var node_path: String = p.get("node_path", "")
			var node := get_tree().current_scene.get_node_or_null(node_path)
			if node == null:
				_respond({"ok": false, "error": "node not found: " + node_path})
				return
			if not (node is Button):
				_respond({"ok": false, "error": "node is not a Button: " + node_path})
				return
			(node as Button).pressed.emit()
			_respond({"ok": true})
		"input_action":
			var action_name: String = p.get("action", "")
			var event := InputEventAction.new()
			event.action = action_name
			event.pressed = true
			Input.parse_input_event(event)
			_respond({"ok": true})
		_:
			_respond({"ok": false, "error": "unknown input action: " + action})


func _cmd_screenshot(save_path: String) -> void:
	var img := get_viewport().get_texture().get_image()
	var path := save_path if save_path != "" else _default_screenshot_path()
	var err := img.save_png(path)
	if err != OK:
		_respond({"ok": false, "error": "failed to save screenshot to: " + path})
		return
	_respond({"ok": true, "path": path})


func _get_ui_tree(node: Node, depth: int) -> Dictionary:
	var d: Dictionary = {
		"name": node.name,
		"type": node.get_class(),
		"children": [],
	}
	if node is CanvasItem:
		d["visible"] = (node as CanvasItem).visible
	if node is Control:
		var c := node as Control
		d["position"] = [c.position.x, c.position.y]
		d["size"] = [c.size.x, c.size.y]
	if node is Label:
		d["text"] = (node as Label).text
	elif node is Button:
		d["text"] = (node as Button).text
	elif node is LineEdit:
		d["text"] = (node as LineEdit).text
	elif node is RichTextLabel:
		d["text"] = (node as RichTextLabel).text
	if depth > 0:
		for child in node.get_children():
			if child is CanvasItem:
				d["children"].append(_get_ui_tree(child, depth - 1))
	return d


func _respond(data: Dictionary) -> void:
	if _peer and _peer.get_status() == StreamPeerTCP.STATUS_CONNECTED:
		var msg := JSON.stringify(data) + "\n"
		_peer.put_data(msg.to_utf8_buffer())


func _default_screenshot_path() -> String:
	var project := ProjectSettings.globalize_path("res://")
	var ts := Time.get_datetime_string_from_system(false, true).replace(":", "").replace("-", "")
	return project.path_join("tests/ui_screenshots/%s.png" % ts)
```

- [ ] **Step 2: Commit**

```bash
cd "/Users/kognido/game dev/godot-mcp"
git add scaffold/addons/godot_mcp/remote_control.gd
git commit -m "feat: add RemoteControl autoload scaffold for live game session (port 6790)"
```

---

## Task 6: Scaffold changes

Extend `scaffold_tests()` to install addon files and register the autoload. Extend `check_scaffold()` to verify them.

**Files:**
- Modify: `server.py` (`scaffold_tests` and `check_scaffold` functions)
- Modify: `tests/test_scaffold.py` (add tests for new scaffold files)

- [ ] **Step 1: Add failing tests**

Open `tests/test_scaffold.py` and append:

```python
# ── UI verification scaffold tests ────────────────────────────────────────────


def test_scaffold_tests_creates_addon_files(tmp_path, monkeypatch):
    """scaffold_tests() copies plugin.cfg, plugin.gd, remote_control.gd to addons/."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)

    srv.scaffold_tests()

    assert (tmp_path / "addons" / "godot_mcp" / "plugin.cfg").exists()
    assert (tmp_path / "addons" / "godot_mcp" / "plugin.gd").exists()
    assert (tmp_path / "addons" / "godot_mcp" / "remote_control.gd").exists()


def test_scaffold_tests_creates_screenshots_dir(tmp_path, monkeypatch):
    """scaffold_tests() creates tests/ui_screenshots/ directory."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)

    srv.scaffold_tests()

    assert (tmp_path / "tests" / "ui_screenshots").is_dir()


def test_scaffold_tests_registers_remote_control_autoload(tmp_path, monkeypatch):
    """scaffold_tests() adds GodotMCPRemoteControl autoload to project.godot."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)

    # Create a minimal project.godot
    (tmp_path / "project.godot").write_text(
        '[application]\nconfig/name="Test"\n\n[autoload]\n'
    )
    srv.scaffold_tests()

    content = (tmp_path / "project.godot").read_text()
    assert "GodotMCPRemoteControl" in content


def test_check_scaffold_detects_missing_addon_files(tmp_path, monkeypatch):
    """check_scaffold() reports missing addon files."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)

    # Install core scaffold but not addons
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "base_test.gd").touch()
    (tmp_path / "tests" / "test_runner.gd").touch()

    result = srv.check_scaffold()
    assert "plugin.gd" in result or "missing" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/kognido/game dev/godot-mcp"
uv run pytest tests/test_scaffold.py -k "addon or screenshots or remote_control or missing_addon" -v 2>&1 | head -30
```

Expected: tests fail because `scaffold_tests()` doesn't yet copy the addon files.

- [ ] **Step 3: Extend `scaffold_tests()` in `server.py`**

Find the existing `scaffold_tests()` function and add the following block inside it, after the existing file-copy logic:

```python
    # Install UI verification addon
    addon_src = Path(__file__).parent / "scaffold" / "addons" / "godot_mcp"
    addon_dst = Path(GODOT_PROJECT) / "addons" / "godot_mcp"
    addon_dst.mkdir(parents=True, exist_ok=True)
    for fname in ("plugin.cfg", "plugin.gd", "remote_control.gd"):
        src = addon_src / fname
        dst = addon_dst / fname
        if not dst.exists():
            shutil.copy(src, dst)
            created.append(str(dst.relative_to(GODOT_PROJECT)))

    # Create screenshots directory
    screenshots_dir = Path(GODOT_PROJECT) / "tests" / "ui_screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    gitkeep = screenshots_dir / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()
        created.append("tests/ui_screenshots/.gitkeep")

    # Register RemoteControl autoload in project.godot (if not already present)
    project_godot = Path(GODOT_PROJECT) / "project.godot"
    if project_godot.exists():
        content = project_godot.read_text(encoding="utf-8")
        if "GodotMCPRemoteControl" not in content:
            autoload_line = 'GodotMCPRemoteControl="*res://addons/godot_mcp/remote_control.gd"'
            if "[autoload]" in content:
                content = content.replace("[autoload]", f"[autoload]\n{autoload_line}")
            else:
                content += f"\n[autoload]\n{autoload_line}\n"
            project_godot.write_text(content, encoding="utf-8")
            created.append("project.godot (GodotMCPRemoteControl autoload)")
```

- [ ] **Step 4: Extend `check_scaffold()` in `server.py`**

Find `check_scaffold()` and add the addon files to its missing-file checklist:

```python
    # Check UI verification addon files
    addon_files = [
        Path(GODOT_PROJECT) / "addons" / "godot_mcp" / "plugin.cfg",
        Path(GODOT_PROJECT) / "addons" / "godot_mcp" / "plugin.gd",
        Path(GODOT_PROJECT) / "addons" / "godot_mcp" / "remote_control.gd",
    ]
    for f in addon_files:
        if not f.exists():
            missing.append(str(f.relative_to(GODOT_PROJECT)))
```

- [ ] **Step 5: Run all scaffold tests**

```bash
cd "/Users/kognido/game dev/godot-mcp"
uv run pytest tests/test_scaffold.py -v 2>&1 | tail -20
```

Expected: all scaffold tests pass.

- [ ] **Step 6: Run the full test suite**

```bash
cd "/Users/kognido/game dev/godot-mcp"
uv run pytest tests/ -v 2>&1 | tail -30
```

Expected: all tests pass, no regressions.

- [ ] **Step 7: Commit**

```bash
cd "/Users/kognido/game dev/godot-mcp"
git add server.py tests/test_scaffold.py
git commit -m "feat: extend scaffold_tests and check_scaffold for UI verification addon"
```

---

## Self-Review

**Spec coverage:**
- Architecture (EditorPlugin + RemoteControl + EditorBridge) — covered in Tasks 1, 3, 5
- Protocol (newline-delimited JSON, command tables) — covered by `_transact` in Task 1; GDScript counterpart in Tasks 3, 5
- `inspect_ui_scene` — Task 2
- `start_ui_session` — Task 4
- `navigate_ui` — Task 4
- `get_live_ui` — Task 4
- `screenshot_ui` — Task 4
- `end_ui_session` — Task 4
- Scaffold changes (`scaffold_tests`, `check_scaffold`) — Task 6
- UI tree structure (name, type, visible, position, size, text) — in `_get_ui_tree` in Tasks 3, 5
- Error handling rules — all tools return strings; all cases from the spec are handled

**Notes for implementation:**
- `plugin.gd` must be manually enabled once in the Godot editor (Project → Project Settings → Plugins → godot_mcp → Enable). This is a one-time step per project; add a note to the return value of `scaffold_tests()`.
- `remote_control.gd` does NOT need manual activation — it auto-activates via the `--mcp` flag.
- The `_get_ui_tree` function is intentionally duplicated between `plugin.gd` and `remote_control.gd`. They run in different Godot contexts (editor vs. game process) and cannot share code without an additional autoload.
