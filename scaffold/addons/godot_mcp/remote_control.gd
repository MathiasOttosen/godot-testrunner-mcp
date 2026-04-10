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
	var root := get_tree().current_scene
	if root == null:
		_respond({"ok": false, "error": "no current scene"})
		return
	match action:
		"press_button":
			var node_path: String = p.get("node_path", "")
			var node := root.get_node_or_null(node_path)
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
	var keycode := OS.find_keycode_from_string(key_str)
	if keycode == KEY_NONE:
		_respond({"ok": false, "error": "unknown key: " + key_str})
		return
	var event := InputEventKey.new()
	event.keycode = keycode
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
	_await_deadline_ms = Time.get_ticks_msec() + int(timeout * 1000.0)
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
	_await_deadline_ms = Time.get_ticks_msec() + int(timeout * 1000.0)

	match arg_count:
		0:
			node.connect(signal_name, Callable(self, "_on_signal_0"), CONNECT_ONE_SHOT)
		1:
			node.connect(signal_name, Callable(self, "_on_signal_1"), CONNECT_ONE_SHOT)
		_:
			node.connect(signal_name, Callable(self, "_on_signal_2"), CONNECT_ONE_SHOT)


func _on_signal_0() -> void:
	_finish_signal_await()


func _on_signal_1(_a) -> void:
	_finish_signal_await()


func _on_signal_2(_a, _b) -> void:
	_finish_signal_await()


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
	if result == null or result is bool or result is int or result is float or result is String:
		serializable = result
	elif result is Array:
		serializable = []
		for item in result:
			serializable.append(MCPTree._json_safe(item))
	elif result is Dictionary:
		serializable = {}
		for key in result.keys():
			serializable[str(key)] = MCPTree._json_safe(result[key])
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
