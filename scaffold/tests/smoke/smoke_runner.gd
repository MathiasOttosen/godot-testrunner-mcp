extends Node
## Smoke test runner autoload. Activated when --smoke arg is present.

const SCAFFOLD_VERSION = "1.0"


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	if "--smoke" not in args:
		return
	var scenario_filter := ""
	var idx := args.find("--smoke")
	if idx != -1 and idx + 1 < args.size() and not args[idx + 1].begins_with("--"):
		scenario_filter = args[idx + 1]
	_run(scenario_filter)


func _run(scenario_filter: String) -> void:
	var results: Array[Dictionary] = []
	var scenario_dir := "res://tests/smoke/scenarios/"
	var dir := DirAccess.open(scenario_dir)
	if dir != null:
		dir.list_dir_begin()
		var name := dir.get_next()
		while name != "":
			if name.ends_with(".gd") and (scenario_filter == "" or name.begins_with(scenario_filter)):
				var script = load(scenario_dir + name)
				if script:
					var scenario = script.new()
					add_child(scenario)
					await scenario.run()
					results.append({"scenario": name, "pass": true})
					scenario.queue_free()
			name = dir.get_next()
	print(JSON.stringify({"results": results, "total": results.size()}))
	get_tree().quit()
