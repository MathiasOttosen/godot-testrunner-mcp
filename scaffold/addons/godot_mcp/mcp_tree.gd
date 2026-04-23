class_name MCPTree


static func get_ui_tree(node: Node, depth: int) -> Dictionary:
	var data: Dictionary = {
		"name": node.name,
		"type": node.get_class(),
		"path": str(node.get_path()),
		"children": [],
	}
	var script := node.get_script()
	if script != null and script.resource_path != "":
		data["script_path"] = script.resource_path
	if node is CanvasItem:
		data["visible"] = (node as CanvasItem).visible
	if node is Control:
		var control := node as Control
		data["position"] = [control.position.x, control.position.y]
		data["size"] = [control.size.x, control.size.y]
	if node is Node2D:
		var node_2d := node as Node2D
		data["position"] = [node_2d.position.x, node_2d.position.y]
		data["global_position"] = [node_2d.global_position.x, node_2d.global_position.y]
		data["rotation"] = node_2d.rotation
		data["scale"] = [node_2d.scale.x, node_2d.scale.y]
	if node is Camera2D:
		var camera := node as Camera2D
		data["zoom"] = [camera.zoom.x, camera.zoom.y]
	if node is CharacterBody2D:
		var character_body := node as CharacterBody2D
		data["velocity"] = [character_body.velocity.x, character_body.velocity.y]
	elif node is RigidBody2D:
		var rigid_body := node as RigidBody2D
		data["linear_velocity"] = [rigid_body.linear_velocity.x, rigid_body.linear_velocity.y]
	if node is Label:
		data["text"] = (node as Label).text
	elif node is Button:
		data["text"] = (node as Button).text
	elif node is LineEdit:
		data["text"] = (node as LineEdit).text
	elif node is RichTextLabel:
		data["text"] = (node as RichTextLabel).text
	if depth > 0:
		for child in node.get_children():
			if child is CanvasItem:
				data["children"].append(get_ui_tree(child, depth - 1))
	return data


static func get_node_data(
	node: Node,
	extra_properties: Array,
	include_children: bool = false,
	depth: int = 1
) -> Dictionary:
	var data := get_ui_tree(node, depth if include_children else 0)
	if not include_children:
		data.erase("children")
	var known_props: Dictionary = {}
	var property_errors: Dictionary = {}
	for prop in node.get_property_list():
		known_props[prop["name"]] = true
	for prop in extra_properties:
		if prop in known_props:
			data[prop] = _json_safe(node.get(prop))
		else:
			property_errors[prop] = "property not found"
	if not property_errors.is_empty():
		data["property_errors"] = property_errors
	return data


static func _json_safe(value):
	if value == null or value is bool or value is int or value is float or value is String:
		return value
	if value is Array:
		var array_value: Array = []
		for item in value:
			array_value.append(_json_safe(item))
		return array_value
	if value is Dictionary:
		var dict_value: Dictionary = {}
		for key in value.keys():
			dict_value[str(key)] = _json_safe(value[key])
		return dict_value
	return str(value)
