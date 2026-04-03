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
