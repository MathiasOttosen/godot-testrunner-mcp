extends Node
## RemoteControl: activated by --mcp CLI flag.
## Starts a TCP server on localhost:6790 for MCP session commands.
## Registered as an autoload by scaffold_tests() — dormant unless --mcp is present.

const PORT := 6790

var _server: TCPServer
var _peer: StreamPeerTCP


func _ready() -> void:
	# Use get_cmdline_user_args() not get_cmdline_args() — args after "--" are user args in Godot 4.
	# The Python server passes "--mcp" after "--", so it only appears in user args.
	var args := OS.get_cmdline_user_args()
	if "--mcp" not in args:
		return  # dormant in normal gameplay

	_server = TCPServer.new()
	var err := _server.listen(PORT)
	if err != OK:
		push_error("godot-mcp remote_control: failed to listen on port %d" % PORT)
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
