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
