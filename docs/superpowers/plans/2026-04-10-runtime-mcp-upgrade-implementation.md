# Runtime MCP Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand godot-mcp's runtime surface with input injection, Node2D inspection, await primitives, call_node_method, screenshot metadata, and a shared GDScript tree-serialization helper.

**Architecture:** New `mcp_tree.gd` static class owns all node serialization; both `plugin.gd` and `remote_control.gd` preload it. `remote_control.gd` gains a formal await state machine, full input commands, and `call_node_method`. `server.py` adds ten new MCP tools with per-call socket timeouts for blocking await commands.

**Tech Stack:** GDScript 4, Python 3.12, FastMCP, pytest

**Spec:** `docs/superpowers/specs/2026-04-10-runtime-mcp-upgrade-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `scaffold/addons/godot_mcp/mcp_tree.gd` | Create | Static node serializer shared by plugin and runtime |
| `scaffold/addons/godot_mcp/plugin.gd` | Rewrite | Editor plugin: adopt mcp_tree, add get_node/find_nodes, screenshot metadata |
| `scaffold/addons/godot_mcp/remote_control.gd` | Rewrite | Runtime autoload: all new commands + await state machine |
| `server.py` | Modify | 10 new MCP tools, socket_timeout, screenshot metadata, docstring updates |
| `tests/test_scaffold.py` | Modify | Add mcp_tree.gd scaffold/check tests |
| `tests/test_ui_verification.py` | Modify | Tests for new server.py tools |

---

## Task 1: Create `mcp_tree.gd` and update scaffold

**Files:**
- Create: `scaffold/addons/godot_mcp/mcp_tree.gd`
- Modify: `server.py` (scaffold_tests and check_scaffold functions)
- Test: `tests/test_scaffold.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_scaffold.py`:

```python
def test_scaffold_tests_creates_mcp_tree(tmp_path, monkeypatch):
    """scaffold_tests() copies mcp_tree.gd to addons/godot_mcp/."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)
    srv.scaffold_tests()
    assert (tmp_path / "addons" / "godot_mcp" / "mcp_tree.gd").exists()


def test_check_scaffold_detects_missing_mcp_tree(tmp_path, monkeypatch):
    """check_scaffold() reports missing when mcp_tree.gd is absent."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)

    addon_dir = tmp_path / "addons" / "godot_mcp"
    addon_dir.mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "base_test.gd").write_text('const SCAFFOLD_VERSION = "1.0"', encoding="utf-8")
    (tmp_path / "tests" / "test_runner.gd").touch()
    (tmp_path / "tests" / "smoke").mkdir()
    (tmp_path / "tests" / "smoke" / "smoke_runner.gd").touch()
    for f in ("plugin.cfg", "plugin.gd", "remote_control.gd"):
        (addon_dir / f).touch()
    # mcp_tree.gd intentionally absent

    result = srv.check_scaffold()
    assert "mcp_tree.gd" in result or "missing" in result.lower()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/kognido/game-dev/godot-mcp
uv run pytest tests/test_scaffold.py::test_scaffold_tests_creates_mcp_tree tests/test_scaffold.py::test_check_scaffold_detects_missing_mcp_tree -v
```

Expected: FAILED — `mcp_tree.gd` doesn't exist yet.

- [ ] **Step 3: Create `scaffold/addons/godot_mcp/mcp_tree.gd`**

```gdscript
class_name MCPTree


static func get_ui_tree(node: Node, depth: int) -> Dictionary:
	var d: Dictionary = {
		"name": node.name,
		"type": node.get_class(),
		"path": str(node.get_path()),
		"children": [],
	}
	if node is CanvasItem:
		d["visible"] = (node as CanvasItem).visible
	if node is Control:
		var c := node as Control
		d["position"] = [c.position.x, c.position.y]
		d["size"] = [c.size.x, c.size.y]
	if node is Node2D:
		var n2 := node as Node2D
		d["position"] = [n2.position.x, n2.position.y]
		d["global_position"] = [n2.global_position.x, n2.global_position.y]
		d["rotation"] = n2.rotation
		d["scale"] = [n2.scale.x, n2.scale.y]
	if node is Camera2D:
		var cam := node as Camera2D
		d["zoom"] = [cam.zoom.x, cam.zoom.y]
	if node is CharacterBody2D:
		var body := node as CharacterBody2D
		d["velocity"] = [body.velocity.x, body.velocity.y]
	elif node is RigidBody2D:
		var body := node as RigidBody2D
		d["linear_velocity"] = [body.linear_velocity.x, body.linear_velocity.y]
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
				d["children"].append(get_ui_tree(child, depth - 1))
	return d


static func get_node_data(node: Node, extra_properties: Array) -> Dictionary:
	var d := get_ui_tree(node, 0)
	d.erase("children")
	var known_props: Dictionary = {}
	for p in node.get_property_list():
		known_props[p["name"]] = true
	for prop in extra_properties:
		if prop in known_props:
			d[prop] = node.get(prop)
		else:
			d[prop] = "<error: property not found>"
	return d
```

- [ ] **Step 4: Update `server.py` — add `mcp_tree.gd` to scaffold_tests and check_scaffold**

In `scaffold_tests()`, find the block that copies addon files:

```python
    for fname in ("plugin.cfg", "plugin.gd", "remote_control.gd"):
```

Change to:

```python
    for fname in ("plugin.cfg", "plugin.gd", "remote_control.gd", "mcp_tree.gd"):
```

In `check_scaffold()`, find the `addon_files` list:

```python
    addon_files = [
        Path(project) / "addons" / "godot_mcp" / "plugin.cfg",
        Path(project) / "addons" / "godot_mcp" / "plugin.gd",
        Path(project) / "addons" / "godot_mcp" / "remote_control.gd",
    ]
```

Change to:

```python
    addon_files = [
        Path(project) / "addons" / "godot_mcp" / "plugin.cfg",
        Path(project) / "addons" / "godot_mcp" / "plugin.gd",
        Path(project) / "addons" / "godot_mcp" / "remote_control.gd",
        Path(project) / "addons" / "godot_mcp" / "mcp_tree.gd",
    ]
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
uv run pytest tests/test_scaffold.py -v
```

Expected: all PASSED.

- [ ] **Step 6: Commit**

```bash
git add scaffold/addons/godot_mcp/mcp_tree.gd server.py tests/test_scaffold.py
git commit -m "feat: add MCPTree shared GDScript node serializer"
```

---

## Task 2: Rewrite `plugin.gd`

**Files:**
- Rewrite: `scaffold/addons/godot_mcp/plugin.gd`

No new Python tests — GDScript content is verified by reading and full test suite staying green.

- [ ] **Step 1: Replace `scaffold/addons/godot_mcp/plugin.gd` entirely**

```gdscript
@tool
extends EditorPlugin

const PORT := 6789
const READY_FRAMES := 3

const MCPTree = preload("res://addons/godot_mcp/mcp_tree.gd")

var _server: TCPServer
var _peer: StreamPeerTCP
var _viewport: SubViewport
var _scene_root: Node
var _pending_load_response := false
var _load_frame_count := 0
var _loaded_scene_path := ""


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
	if _server and _server.is_connection_available():
		if _peer:
			_peer.disconnect_from_host()
		_peer = _server.take_connection()

	if not (_peer and _peer.get_status() == StreamPeerTCP.STATUS_CONNECTED):
		return

	if _pending_load_response:
		_load_frame_count += 1
		if _load_frame_count >= READY_FRAMES:
			_pending_load_response = false
			_load_frame_count = 0
			_respond({"ok": true})
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
		"load_scene":
			_cmd_load_scene(parsed.get("path", ""))
		"get_ui":
			_cmd_get_ui(int(parsed.get("depth", 1)))
		"get_node":
			_cmd_get_node(parsed)
		"find_nodes":
			_cmd_find_nodes(parsed)
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
	_loaded_scene_path = full_path
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

	_pending_load_response = true
	_load_frame_count = 0


func _cmd_get_ui(depth: int) -> void:
	if _scene_root == null:
		_respond({"ok": false, "error": "no scene loaded — call load_scene first"})
		return
	_respond({"ok": true, "tree": MCPTree.get_ui_tree(_scene_root, depth)})


func _cmd_get_node(params: Dictionary) -> void:
	if _scene_root == null:
		_respond({"ok": false, "error": "no scene loaded — call load_scene first"})
		return
	var node_path: String = params.get("node_path", "")
	var node := _scene_root.get_node_or_null(node_path)
	if node == null:
		_respond({"ok": false, "error": "node not found: " + node_path})
		return
	var extra: Array = params.get("properties", [])
	_respond({"ok": true, "node": MCPTree.get_node_data(node, extra)})


func _cmd_find_nodes(params: Dictionary) -> void:
	if _scene_root == null:
		_respond({"ok": false, "error": "no scene loaded — call load_scene first"})
		return
	var name_filter: String = params.get("name", "")
	var type_filter: String = params.get("type", "")
	var matches: Array = []
	_walk_find(_scene_root, name_filter, type_filter, matches)
	_respond({"ok": true, "nodes": matches})


func _walk_find(node: Node, name_filter: String, type_filter: String, out: Array) -> void:
	var name_ok := name_filter == "" or node.name == name_filter
	var type_ok := type_filter == "" or node.get_class() == type_filter
	if name_ok and type_ok:
		out.append({"path": str(node.get_path()), "type": node.get_class()})
	for child in node.get_children():
		_walk_find(child, name_filter, type_filter, out)


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
	var vp_size := _viewport.size
	_respond({
		"ok": true,
		"path": path,
		"viewport_size": [vp_size.x, vp_size.y],
		"scene": _loaded_scene_path,
		"frame": 0,
	})


func _unload_scene() -> void:
	if _scene_root:
		_scene_root.queue_free()
		_scene_root = null
	if _viewport:
		_viewport.queue_free()
		_viewport = null
	_loaded_scene_path = ""


func _respond(data: Dictionary) -> void:
	if _peer and _peer.get_status() == StreamPeerTCP.STATUS_CONNECTED:
		var msg := JSON.stringify(data) + "\n"
		_peer.put_data(msg.to_utf8_buffer())


func _default_screenshot_path() -> String:
	var project := ProjectSettings.globalize_path("res://")
	var ts := Time.get_datetime_string_from_system(false, true).replace(":", "").replace("-", "")
	return project.path_join("tests/ui_screenshots/%s.png" % ts)
```

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest -v
```

Expected: all existing tests PASSED.

- [ ] **Step 3: Commit**

```bash
git add scaffold/addons/godot_mcp/plugin.gd
git commit -m "feat: update plugin.gd — shared MCPTree, get_node, find_nodes, screenshot metadata"
```

---

## Task 3: Rewrite `remote_control.gd`

**Files:**
- Rewrite: `scaffold/addons/godot_mcp/remote_control.gd`

- [ ] **Step 1: Replace `scaffold/addons/godot_mcp/remote_control.gd` entirely**

```gdscript
extends Node
## RemoteControl: activated by --mcp CLI flag.
## Starts a TCP server on localhost:6790 for MCP session commands.
## Registered as an autoload by scaffold_tests() — dormant unless --mcp is present.

const PORT := 6790
const MCPTree = preload("res://addons/godot_mcp/mcp_tree.gd")

var _server: TCPServer
var _peer: StreamPeerTCP

enum _AwaitState { NONE, FRAMES, NODE_PROP, SIGNAL }
var _await_state := _AwaitState.NONE
var _await_frames_left := 0
var _await_node_path := ""
var _await_property := ""
var _await_value = null
var _await_deadline_ms := 0


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	if "--mcp" not in args:
		return

	_server = TCPServer.new()
	var err := _server.listen(PORT)
	if err != OK:
		push_error("godot-mcp remote_control: failed to listen on port %d" % PORT)
		return

	set_process(true)

	var idx := args.find("--mcp-scene")
	if idx != -1 and idx + 1 < args.size():
		var scene_path: String = "res://" + args[idx + 1]
		get_tree().change_scene_to_file.call_deferred(scene_path)


func _process(_delta: float) -> void:
	if _server == null:
		return
	if _server.is_connection_available():
		if _peer:
			_peer.disconnect_from_host()
		_peer = _server.take_connection()

	if not (_peer and _peer.get_status() == StreamPeerTCP.STATUS_CONNECTED):
		return

	if _await_state != _AwaitState.NONE:
		_tick_await()
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
				_respond({"ok": true, "tree": MCPTree.get_ui_tree(root, int(parsed.get("depth", 1)))})
		"get_node":
			_cmd_get_node(parsed)
		"find_nodes":
			_cmd_find_nodes(parsed)
		"change_scene":
			var path: String = "res://" + parsed.get("path", "")
			get_tree().change_scene_to_file(path)
			_respond({"ok": true})
		"send_input":
			_cmd_send_input(parsed)
		"send_key":
			_cmd_send_key(parsed)
		"send_mouse_move":
			_cmd_send_mouse_move(parsed)
		"send_mouse_button":
			_cmd_send_mouse_button(parsed)
		"click":
			_cmd_click(parsed)
		"drag":
			_cmd_drag(parsed)
		"await_frames":
			_cmd_await_frames(parsed)
		"await_node_property":
			_cmd_await_node_property(parsed)
		"await_signal":
			_cmd_await_signal(parsed)
		"call_node_method":
			_cmd_call_node_method(parsed)
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


func _cmd_send_key(params: Dictionary) -> void:
	var key_str: String = params.get("key", "")
	var event := InputEventKey.new()
	event.keycode = OS.find_keycode_from_string(key_str)
	event.pressed = bool(params.get("pressed", true))
	event.echo = bool(params.get("echo", false))
	event.shift_pressed = bool(params.get("shift", false))
	event.ctrl_pressed = bool(params.get("ctrl", false))
	event.alt_pressed = bool(params.get("alt", false))
	Input.parse_input_event(event)
	_respond({"ok": true})


func _cmd_send_mouse_move(params: Dictionary) -> void:
	var event := InputEventMouseMotion.new()
	event.position = Vector2(float(params.get("x", 0)), float(params.get("y", 0)))
	Input.parse_input_event(event)
	_respond({"ok": true})


func _cmd_send_mouse_button(params: Dictionary) -> void:
	var event := InputEventMouseButton.new()
	event.position = Vector2(float(params.get("x", 0)), float(params.get("y", 0)))
	event.button_index = int(params.get("button", MOUSE_BUTTON_LEFT))
	event.pressed = bool(params.get("pressed", true))
	Input.parse_input_event(event)
	_respond({"ok": true})


func _cmd_click(params: Dictionary) -> void:
	var x := float(params.get("x", 0))
	var y := float(params.get("y", 0))
	var button := int(params.get("button", MOUSE_BUTTON_LEFT))
	var pos := Vector2(x, y)

	var move := InputEventMouseMotion.new()
	move.position = pos
	Input.parse_input_event(move)

	var down := InputEventMouseButton.new()
	down.position = pos
	down.button_index = button
	down.pressed = true
	Input.parse_input_event(down)

	var up := InputEventMouseButton.new()
	up.position = pos
	up.button_index = button
	up.pressed = false
	Input.parse_input_event(up)

	_respond({"ok": true})


func _cmd_drag(params: Dictionary) -> void:
	var from_x := float(params.get("from_x", 0))
	var from_y := float(params.get("from_y", 0))
	var to_x := float(params.get("to_x", 0))
	var to_y := float(params.get("to_y", 0))
	var button := int(params.get("button", MOUSE_BUTTON_LEFT))
	var steps := int(params.get("steps", 5))
	if steps < 1:
		steps = 1

	var from_pos := Vector2(from_x, from_y)
	var to_pos := Vector2(to_x, to_y)

	var start_move := InputEventMouseMotion.new()
	start_move.position = from_pos
	Input.parse_input_event(start_move)

	var down := InputEventMouseButton.new()
	down.position = from_pos
	down.button_index = button
	down.pressed = true
	Input.parse_input_event(down)

	for i in range(1, steps + 1):
		var t := float(i) / float(steps)
		var mid := InputEventMouseMotion.new()
		mid.position = from_pos.lerp(to_pos, t)
		Input.parse_input_event(mid)

	var up := InputEventMouseButton.new()
	up.position = to_pos
	up.button_index = button
	up.pressed = false
	Input.parse_input_event(up)

	_respond({"ok": true})


func _cmd_get_node(params: Dictionary) -> void:
	var root := get_tree().current_scene
	if root == null:
		_respond({"ok": false, "error": "no current scene"})
		return
	var node_path: String = params.get("node_path", "")
	var node := root.get_node_or_null(node_path)
	if node == null:
		_respond({"ok": false, "error": "node not found: " + node_path})
		return
	var extra: Array = params.get("properties", [])
	_respond({"ok": true, "node": MCPTree.get_node_data(node, extra)})


func _cmd_find_nodes(params: Dictionary) -> void:
	var root := get_tree().current_scene
	if root == null:
		_respond({"ok": false, "error": "no current scene"})
		return
	var name_filter: String = params.get("name", "")
	var type_filter: String = params.get("type", "")
	var matches: Array = []
	_walk_find(root, name_filter, type_filter, matches)
	_respond({"ok": true, "nodes": matches})


func _walk_find(node: Node, name_filter: String, type_filter: String, out: Array) -> void:
	var name_ok := name_filter == "" or node.name == name_filter
	var type_ok := type_filter == "" or node.get_class() == type_filter
	if name_ok and type_ok:
		out.append({"path": str(node.get_path()), "type": node.get_class()})
	for child in node.get_children():
		_walk_find(child, name_filter, type_filter, out)


func _cmd_await_frames(params: Dictionary) -> void:
	var n := int(params.get("n", 1))
	if n <= 0:
		_respond({"ok": true})
		return
	_await_frames_left = n
	_await_state = _AwaitState.FRAMES


func _cmd_await_node_property(params: Dictionary) -> void:
	_await_node_path = params.get("node_path", "")
	_await_property = params.get("property", "")
	_await_value = params.get("value", null)
	var timeout := float(params.get("timeout", 5.0))
	_await_deadline_ms = Time.get_ticks_msec() + int(timeout * 1000)
	_await_state = _AwaitState.NODE_PROP


func _cmd_await_signal(params: Dictionary) -> void:
	var node_path: String = params.get("node_path", "")
	var signal_name: String = params.get("signal", "")
	var timeout := float(params.get("timeout", 5.0))

	var root := get_tree().current_scene
	if root == null:
		_respond({"ok": false, "error": "no current scene"})
		return
	var node := root.get_node_or_null(node_path)
	if node == null:
		_respond({"ok": false, "error": "node not found: " + node_path})
		return
	if not node.has_signal(signal_name):
		_respond({"ok": false, "error": "signal not found: " + signal_name})
		return

	var arg_count := 0
	for sig in node.get_signal_list():
		if sig["name"] == signal_name:
			arg_count = sig["args"].size()
			break

	_await_state = _AwaitState.SIGNAL
	_await_deadline_ms = Time.get_ticks_msec() + int(timeout * 1000)

	match arg_count:
		0: node.connect(signal_name, _on_signal_0, CONNECT_ONE_SHOT)
		1: node.connect(signal_name, _on_signal_1, CONNECT_ONE_SHOT)
		_: node.connect(signal_name, _on_signal_2, CONNECT_ONE_SHOT)


func _on_signal_0() -> void: _finish_signal_await()
func _on_signal_1(_a) -> void: _finish_signal_await()
func _on_signal_2(_a, _b) -> void: _finish_signal_await()


func _finish_signal_await() -> void:
	if _await_state == _AwaitState.SIGNAL:
		_await_state = _AwaitState.NONE
		_respond({"ok": true})


func _tick_await() -> void:
	match _await_state:
		_AwaitState.FRAMES:
			_await_frames_left -= 1
			if _await_frames_left <= 0:
				_await_state = _AwaitState.NONE
				_respond({"ok": true})
		_AwaitState.NODE_PROP:
			var root := get_tree().current_scene
			if root == null:
				_await_state = _AwaitState.NONE
				_respond({"ok": false, "error": "no current scene"})
				return
			var node := root.get_node_or_null(_await_node_path)
			if node == null:
				_await_state = _AwaitState.NONE
				_respond({"ok": false, "error": "node not found: " + _await_node_path})
				return
			var actual = node.get(_await_property)
			if actual == _await_value:
				_await_state = _AwaitState.NONE
				_respond({"ok": true, "value": actual})
				return
			if Time.get_ticks_msec() > _await_deadline_ms:
				_await_state = _AwaitState.NONE
				_respond({"ok": false, "error": "timeout waiting for property", "actual": str(actual)})
		_AwaitState.SIGNAL:
			if Time.get_ticks_msec() > _await_deadline_ms:
				_await_state = _AwaitState.NONE
				_respond({"ok": false, "error": "timeout waiting for signal"})


func _cmd_call_node_method(params: Dictionary) -> void:
	var root := get_tree().current_scene
	if root == null:
		_respond({"ok": false, "error": "no current scene"})
		return
	var node_path: String = params.get("node_path", "")
	var method: String = params.get("method", "")
	var args: Array = params.get("args", [])

	var node := root.get_node_or_null(node_path)
	if node == null:
		_respond({"ok": false, "error": "node not found: " + node_path})
		return
	if not node.has_method(method):
		_respond({"ok": false, "error": "method not found: " + method})
		return

	var result = node.callv(method, args)
	var serializable
	if result == null or result is bool or result is int or result is float or result is String or result is Array or result is Dictionary:
		serializable = result
	else:
		serializable = str(result)
	_respond({"ok": true, "result": serializable})


func _cmd_screenshot(save_path: String) -> void:
	var img := get_viewport().get_texture().get_image()
	var path := save_path if save_path != "" else _default_screenshot_path()
	var err := img.save_png(path)
	if err != OK:
		_respond({"ok": false, "error": "failed to save screenshot to: " + path})
		return
	var vp_size := get_viewport().get_visible_rect().size
	var scene_path := ""
	if get_tree().current_scene:
		scene_path = get_tree().current_scene.scene_file_path
	_respond({
		"ok": true,
		"path": path,
		"viewport_size": [int(vp_size.x), int(vp_size.y)],
		"scene": scene_path,
		"frame": Engine.get_process_frames(),
	})


func _respond(data: Dictionary) -> void:
	if _peer and _peer.get_status() == StreamPeerTCP.STATUS_CONNECTED:
		var msg := JSON.stringify(data) + "\n"
		_peer.put_data(msg.to_utf8_buffer())


func _default_screenshot_path() -> String:
	var project := ProjectSettings.globalize_path("res://")
	var ts := Time.get_datetime_string_from_system(false, true).replace(":", "").replace("-", "")
	return project.path_join("tests/ui_screenshots/%s.png" % ts)
```

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest -v
```

Expected: all existing tests PASSED.

- [ ] **Step 3: Commit**

```bash
git add scaffold/addons/godot_mcp/remote_control.gd
git commit -m "feat: update remote_control.gd — input, inspection, await, call_node_method, screenshot metadata"
```

---

## Task 4: `server.py` — socket timeout + screenshot metadata + input tools

**Files:**
- Modify: `server.py` (`EditorBridge.send_session_command`, `screenshot_ui`, new tools)
- Test: `tests/test_ui_verification.py`

- [ ] **Step 1: Write failing tests**

First, add `call as mock_call` to the existing `unittest.mock` import line at the top of `tests/test_ui_verification.py`:

```python
from unittest.mock import MagicMock, patch, call as mock_call
```

Then add the following tests to `tests/test_ui_verification.py`:

```python
# ── socket timeout ─────────────────────────────────────────────────────────────

def test_send_session_command_sets_socket_timeout():
    """socket_timeout param is applied to the session socket before _transact."""
    bridge = EditorBridge()
    conn_mock = MagicMock()
    bridge._session_conn = conn_mock
    with patch.object(EditorBridge, '_transact', return_value={"ok": True}):
        bridge.send_session_command("ping", socket_timeout=7.0)
    conn_mock.settimeout.assert_any_call(7.0)


def test_send_session_command_restores_timeout_after_call():
    """Default timeout is restored on the socket after a socket_timeout call."""
    bridge = EditorBridge()
    conn_mock = MagicMock()
    bridge._session_conn = conn_mock
    with patch.object(EditorBridge, '_transact', return_value={"ok": True}):
        bridge.send_session_command("ping", socket_timeout=7.0)
    last_call = conn_mock.settimeout.call_args_list[-1]
    assert last_call == mock_call(bridge.CONNECT_TIMEOUT)


def test_send_session_command_no_timeout_does_not_call_settimeout():
    """No settimeout call when socket_timeout is not provided."""
    bridge = EditorBridge()
    conn_mock = MagicMock()
    bridge._session_conn = conn_mock
    with patch.object(EditorBridge, '_transact', return_value={"ok": True}):
        bridge.send_session_command("ping")
    conn_mock.settimeout.assert_not_called()


# ── screenshot_ui metadata ─────────────────────────────────────────────────────

def test_screenshot_ui_returns_json_with_metadata(monkeypatch, tmp_path):
    """screenshot_ui returns JSON dict with path, viewport_size, scene, frame."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)

    srv._bridge.screenshot = MagicMock(return_value={
        "ok": True,
        "path": "/tmp/shot.png",
        "viewport_size": [1920, 1080],
        "scene": "res://scenes/game.tscn",
        "frame": 42,
    })
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
    import importlib
    importlib.reload(srv)

    srv._bridge.screenshot = MagicMock(return_value={"ok": False, "error": "no scene loaded"})
    result = srv.screenshot_ui()
    assert "no scene loaded" in result
    assert not result.startswith("{")


# ── input tools ────────────────────────────────────────────────────────────────

def test_send_key_no_session(monkeypatch, tmp_path):
    """send_key returns error when no session is active."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)
    srv._bridge._session_conn = None
    result = srv.send_key("Right")
    assert "no active UI session" in result


def test_send_key_sends_correct_command(monkeypatch, tmp_path):
    """send_key forwards all params to send_key command."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
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
    import importlib
    importlib.reload(srv)
    srv._bridge.send_session_command = MagicMock(return_value={"ok": True})
    srv._bridge._session_conn = MagicMock()
    result = srv.send_mouse(100.0, 200.0)
    srv._bridge.send_session_command.assert_called_once_with("send_mouse_move", x=100.0, y=200.0)
    assert result == "ok"


def test_click_sends_correct_command(monkeypatch, tmp_path):
    """click forwards x, y, button to click command."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)
    srv._bridge.send_session_command = MagicMock(return_value={"ok": True})
    srv._bridge._session_conn = MagicMock()
    result = srv.click(50.0, 75.0, button=2)
    srv._bridge.send_session_command.assert_called_once_with("click", x=50.0, y=75.0, button=2)
    assert result == "ok"


def test_drag_sends_correct_command(monkeypatch, tmp_path):
    """drag forwards all params to drag command."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)
    srv._bridge.send_session_command = MagicMock(return_value={"ok": True})
    srv._bridge._session_conn = MagicMock()
    result = srv.drag(0.0, 0.0, 100.0, 200.0, steps=10)
    srv._bridge.send_session_command.assert_called_once_with(
        "drag", from_x=0.0, from_y=0.0, to_x=100.0, to_y=200.0, button=1, steps=10
    )
    assert result == "ok"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_ui_verification.py::test_send_session_command_sets_socket_timeout tests/test_ui_verification.py::test_send_key_no_session tests/test_ui_verification.py::test_screenshot_ui_returns_json_with_metadata -v
```

Expected: FAILED — functions don't exist yet.

- [ ] **Step 3: Update `EditorBridge.send_session_command` in `server.py`**

Replace the existing method:

```python
    def send_session_command(self, cmd: str, socket_timeout: float | None = None, **params) -> dict:
        """Send a command to the active game session."""
        if self._session_conn is None:
            return {
                "ok": False,
                "error": "no active UI session — call start_ui_session first",
            }
        try:
            if socket_timeout is not None:
                self._session_conn.settimeout(socket_timeout)
            return self._transact(self._session_conn, cmd, params)
        except OSError:
            self._session_conn = None
            return {
                "ok": False,
                "error": "session disconnected — call start_ui_session to reconnect",
            }
        finally:
            if socket_timeout is not None:
                try:
                    if self._session_conn is not None:
                        self._session_conn.settimeout(self.CONNECT_TIMEOUT)
                except OSError:
                    pass
```

- [ ] **Step 4: Update `screenshot_ui` in `server.py` to return JSON**

Replace the existing `screenshot_ui` tool:

```python
@mcp.tool()
def screenshot_ui(save_path: str = "") -> str:
    """Capture the current viewport as a PNG and return JSON with path and metadata.
    Metadata fields: path (absolute), viewport_size [w, h], scene (current scene file path),
    frame (process frame count; 0 for editor captures).
    If save_path is empty, saves to tests/ui_screenshots/<timestamp>.png in the project root.
    Uses the active game session if running; otherwise captures from the editor plugin's SubViewport.
    Call inspect_ui_scene or start_ui_session first."""
    if save_path:
        safe = safe_path(save_path)
        if safe is None:
            return "Error: path escapes project root"
    result = _bridge.screenshot(save_path, godot_project())
    if not result["ok"]:
        return f"Error: {result['error']}"
    return json.dumps({k: v for k, v in result.items() if k != "ok"})
```

- [ ] **Step 5: Add input tools to `server.py` (after `screenshot_ui`)**

```python
@mcp.tool()
def send_key(
    key: str,
    pressed: bool = True,
    shift: bool = False,
    ctrl: bool = False,
    alt: bool = False,
    echo: bool = False,
) -> str:
    """Send a keyboard event to the active game session.
    key is a Godot key name (e.g. 'Right', 'Left', 'Space', 'A', 'Escape').
    pressed controls key-down (True) vs key-up (False); default is True.
    shift, ctrl, alt are modifier keys. echo is for held-key repeat events.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command(
        "send_key", key=key, pressed=pressed, shift=shift, ctrl=ctrl, alt=alt, echo=echo
    )
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"


@mcp.tool()
def send_mouse(x: float, y: float) -> str:
    """Move the mouse cursor to viewport coordinates (x, y) in the active game session.
    Coordinates are pixels from the top-left of the viewport.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command("send_mouse_move", x=x, y=y)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"


@mcp.tool()
def click(x: float, y: float, button: int = 1) -> str:
    """Click at viewport coordinates (x, y) in the active game session.
    button: 1=left (default), 2=right, 3=middle.
    Sends mouse_move → button_down → button_up as one atomic operation.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command("click", x=x, y=y, button=button)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"


@mcp.tool()
def drag(
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
    button: int = 1,
    steps: int = 5,
) -> str:
    """Drag from (from_x, from_y) to (to_x, to_y) in the active game session.
    button: 1=left (default), 2=right, 3=middle.
    steps controls intermediate mouse move events for the drag path (default 5).
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command(
        "drag", from_x=from_x, from_y=from_y, to_x=to_x, to_y=to_y, button=button, steps=steps
    )
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
uv run pytest tests/test_ui_verification.py -v
```

Expected: all PASSED. The two old screenshot tests (`test_screenshot_ui_routes_to_bridge`, `test_screenshot_ui_error`) will now fail — replace them with the new ones from Step 1 (they're already written). Delete the two old tests from the file:

- `test_screenshot_ui_routes_to_bridge`
- `test_screenshot_ui_error`

These are superseded by `test_screenshot_ui_returns_json_with_metadata` and `test_screenshot_ui_error_still_returns_error_string`.

Run again:

```bash
uv run pytest -v
```

Expected: all PASSED.

- [ ] **Step 7: Commit**

```bash
git add server.py tests/test_ui_verification.py
git commit -m "feat: add socket_timeout, screenshot metadata, input tools (send_key/send_mouse/click/drag)"
```

---

## Task 5: `server.py` — inspection tools (`get_node`, `find_nodes`)

**Files:**
- Modify: `server.py`
- Test: `tests/test_ui_verification.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_ui_verification.py`:

```python
# ── inspection tools ───────────────────────────────────────────────────────────

def test_get_node_no_session(monkeypatch, tmp_path):
    """get_node returns error when no session is active."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)
    srv._bridge._session_conn = None
    result = srv.get_node("Player")
    assert "no active UI session" in result


def test_get_node_success_returns_json(monkeypatch, tmp_path):
    """get_node returns JSON node data on success."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)
    node_data = {"name": "Player", "type": "CharacterBody2D", "path": "/root/Player",
                 "position": [100.0, 200.0]}
    srv._bridge.send_session_command = MagicMock(return_value={"ok": True, "node": node_data})
    srv._bridge._session_conn = MagicMock()
    result = srv.get_node("Player")
    assert json.loads(result) == node_data
    srv._bridge.send_session_command.assert_called_once_with("get_node", node_path="Player")


def test_get_node_with_extra_properties(monkeypatch, tmp_path):
    """get_node passes properties list when provided."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
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
    import importlib
    importlib.reload(srv)
    srv._bridge._session_conn = None
    result = srv.find_nodes(type="Label")
    assert "no active UI session" in result


def test_find_nodes_returns_json_array(monkeypatch, tmp_path):
    """find_nodes returns JSON array of {path, type} dicts."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
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
    import importlib
    importlib.reload(srv)
    srv._bridge.send_session_command = MagicMock(return_value={"ok": True, "nodes": []})
    srv._bridge._session_conn = MagicMock()
    srv.find_nodes(name="Player")
    call_kwargs = srv._bridge.send_session_command.call_args.kwargs
    assert "name" in call_kwargs
    assert "type" not in call_kwargs
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_ui_verification.py::test_get_node_no_session tests/test_ui_verification.py::test_find_nodes_returns_json_array -v
```

Expected: FAILED — `get_node` and `find_nodes` not defined in server.py.

- [ ] **Step 3: Add inspection tools to `server.py`**

Add after the `drag` tool:

```python
@mcp.tool()
def get_node(node_path: str, properties: list[str] | None = None) -> str:
    """Return data for a single node from the active game session.
    node_path is relative to the current scene root (e.g. 'Player', 'HUD/HealthBar').
    properties: optional list of extra property names to include (e.g. ['health', 'speed']).
    Returns JSON with standard fields (position, velocity, text, etc.) plus requested extras.
    Use get_live_ui for the full scene tree; use get_node when you know the exact node.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    params: dict = {"node_path": node_path}
    if properties:
        params["properties"] = properties
    result = _bridge.send_session_command("get_node", **params)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return json.dumps(result["node"], indent=2)


@mcp.tool()
def find_nodes(name: str = "", type: str = "") -> str:
    """Search the current scene for nodes matching name and/or type.
    name: exact match on node.name (e.g. 'Player'). Omit to skip name filter.
    type: exact match on node class string (e.g. 'CharacterBody2D', 'Label'). Omit to skip.
    Returns JSON array of {path, type} for all matching nodes.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    params: dict = {}
    if name:
        params["name"] = name
    if type:
        params["type"] = type
    result = _bridge.send_session_command("find_nodes", **params)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return json.dumps(result["nodes"], indent=2)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest -v
```

Expected: all PASSED.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_ui_verification.py
git commit -m "feat: add get_node and find_nodes MCP tools"
```

---

## Task 6: `server.py` — await tools

**Files:**
- Modify: `server.py`
- Test: `tests/test_ui_verification.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_ui_verification.py`:

```python
# ── await tools ────────────────────────────────────────────────────────────────

def test_await_frames_no_session(monkeypatch, tmp_path):
    """await_frames returns error when no session is active."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)
    srv._bridge._session_conn = None
    result = srv.await_frames(5)
    assert "no active UI session" in result


def test_await_frames_passes_socket_timeout(monkeypatch, tmp_path):
    """await_frames passes a socket_timeout of at least 10s (buffer for slow machines)."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
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
    import importlib
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
    import importlib
    importlib.reload(srv)
    srv._bridge._session_conn = None
    result = srv.await_node_property("Player", "visible", True)
    assert "no active UI session" in result


def test_await_node_property_sends_correct_params(monkeypatch, tmp_path):
    """await_node_property sends node_path, property, value, timeout and passes socket_timeout."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
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
    import importlib
    importlib.reload(srv)
    srv._bridge._session_conn = None
    result = srv.await_signal("Player", "animation_finished")
    assert "no active UI session" in result


def test_await_signal_sends_correct_params(monkeypatch, tmp_path):
    """await_signal sends node_path, signal, timeout and passes socket_timeout."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_ui_verification.py::test_await_frames_no_session tests/test_ui_verification.py::test_await_node_property_sends_correct_params tests/test_ui_verification.py::test_await_signal_sends_correct_params -v
```

Expected: FAILED — tools not defined yet.

- [ ] **Step 3: Add `from typing import Any` to imports at top of `server.py`**

Add to the imports block:

```python
from typing import Any
```

- [ ] **Step 4: Add await tools to `server.py`**

Add after `find_nodes`:

```python
@mcp.tool()
def await_frames(n: int) -> str:
    """Wait for n game frames to pass in the active session before returning.
    Use after send_key, click, or drag to let the game process input before inspecting state.
    Blocks until Godot confirms n frames have elapsed.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    socket_timeout = max(n / 60.0 + 5.0, 10.0)
    result = _bridge.send_session_command("await_frames", socket_timeout=socket_timeout, n=n)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"


@mcp.tool()
def await_node_property(
    node_path: str, property: str, value: Any, timeout: float = 5.0
) -> str:
    """Wait until a node's property equals the given value, or until timeout seconds.
    node_path: path from current scene root (e.g. 'Player').
    property: property name to watch (e.g. 'visible', 'modulate').
    value: the expected value to wait for (bool, int, float, or string).
    Returns ok when matched; returns error with the actual value on timeout.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command(
        "await_node_property",
        socket_timeout=timeout + 2.0,
        node_path=node_path,
        property=property,
        value=value,
        timeout=timeout,
    )
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"


@mcp.tool()
def await_signal(node_path: str, signal: str, timeout: float = 5.0) -> str:
    """Wait for a signal to be emitted on a node, or until timeout seconds.
    node_path: path from current scene root (e.g. 'Player').
    signal: signal name (e.g. 'animation_finished', 'area_entered').
    Works for signals with 0, 1, or 2 arguments; best-effort for 3+ args.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command(
        "await_signal",
        socket_timeout=timeout + 2.0,
        node_path=node_path,
        signal=signal,
        timeout=timeout,
    )
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
uv run pytest -v
```

Expected: all PASSED.

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_ui_verification.py
git commit -m "feat: add await_frames, await_node_property, await_signal MCP tools"
```

---

## Task 7: `server.py` — `call_node_method` + docstring updates

**Files:**
- Modify: `server.py`
- Test: `tests/test_ui_verification.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_ui_verification.py`:

```python
# ── call_node_method ───────────────────────────────────────────────────────────

def test_call_node_method_no_session(monkeypatch, tmp_path):
    """call_node_method returns error when no session is active."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
    importlib.reload(srv)
    srv._bridge._session_conn = None
    result = srv.call_node_method("Player", "get_health")
    assert "no active UI session" in result


def test_call_node_method_returns_json_result(monkeypatch, tmp_path):
    """call_node_method returns JSON-encoded return value on success."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    import importlib
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
    import importlib
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
    import importlib
    importlib.reload(srv)
    srv._bridge.send_session_command = MagicMock(
        return_value={"ok": False, "error": "method not found: fly"}
    )
    srv._bridge._session_conn = MagicMock()
    result = srv.call_node_method("Player", "fly")
    assert "method not found" in result
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_ui_verification.py::test_call_node_method_no_session tests/test_ui_verification.py::test_call_node_method_returns_json_result -v
```

Expected: FAILED — `call_node_method` not defined.

- [ ] **Step 3: Add `call_node_method` tool to `server.py`**

Add after `await_signal`:

```python
@mcp.tool()
def call_node_method(node_path: str, method: str, args: list | None = None) -> str:
    """Call a method on a node in the active game session and return the result as JSON.
    node_path: path from current scene root (e.g. 'Player', 'SpellBook').
    method: method name (e.g. 'get_health', 'take_damage').
    args: optional list of arguments to pass to the method.
    Non-JSON-serializable return values (Vector2, Node references, etc.) are converted to strings.
    Use for debugging and verification — prefer send_key/click for normal gameplay interaction.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command(
        "call_node_method", node_path=node_path, method=method, args=args or []
    )
    if not result["ok"]:
        return f"Error: {result['error']}"
    return json.dumps(result["result"], indent=2)
```

- [ ] **Step 4: Update `navigate_ui` docstring in `server.py`**

Find the `navigate_ui` tool. Replace its docstring:

```python
    """Send a navigation or input command to the active UI session.
    Prefer send_key, click, and drag for new code — they are more direct.
    navigate_ui remains available for change_scene, press_button, and input_action.
    Requires an active session started by start_ui_session.

    action values:
      'change_scene' — params: {"path": "scenes/gameplay.tscn"}
      'press_button' — params: {"node_path": "MainMenu/StartButton"}
      'input_action' — params: {"action": "ui_accept"}
    """
```

- [ ] **Step 5: Update `get_live_ui` docstring in `server.py`**

Find the `get_live_ui` tool. Replace its docstring:

```python
    """Return the current UI node tree from the active game session as JSON.
    depth controls how many levels of children to include; default 1 = top-level only.
    For targeted inspection of a specific node, use get_node instead.
    To find nodes by name or type, use find_nodes.
    Requires an active session started by start_ui_session."""
```

- [ ] **Step 6: Run all tests**

```bash
uv run pytest -v
```

Expected: all PASSED.

- [ ] **Step 7: Commit**

```bash
git add server.py tests/test_ui_verification.py
git commit -m "feat: add call_node_method MCP tool, update navigate_ui and get_live_ui docstrings"
```
