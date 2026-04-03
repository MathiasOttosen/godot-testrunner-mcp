extends Node
## Test runner autoload. Activated when --test arg is present.

const SCAFFOLD_VERSION = "1.0"


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	if "--test" not in args:
		return
	var suite_filter := ""
	var idx := args.find("--test")
	if idx != -1 and idx + 1 < args.size() and not args[idx + 1].begins_with("--"):
		suite_filter = args[idx + 1]
	_run(suite_filter)


func _run(suite_filter: String) -> void:
	var total := 0
	var passed := 0
	var failed: Array[String] = []
	var suite_dir := "res://tests/suites/"
	var files := _list_gd_files(suite_dir, suite_filter)
	for path in files:
		var script = load(path)
		if script == null:
			continue
		var suite = script.new()
		add_child(suite)
		var results: Array = suite._run_tests()
		for r in results:
			total += 1
			if r.get("pass", false):
				passed += 1
			else:
				failed.append(r.get("test", "unknown"))
		suite.queue_free()
	var summary := {"total": total, "passed": passed, "failed": failed.size(), "failed_tests": failed}
	print(JSON.stringify(summary))
	get_tree().quit()


func _list_gd_files(dir_path: String, filter: String) -> Array[String]:
	var result: Array[String] = []
	var dir := DirAccess.open(dir_path)
	if dir == null:
		return result
	dir.list_dir_begin()
	var name := dir.get_next()
	while name != "":
		if name.ends_with(".gd") and (filter == "" or name.begins_with(filter)):
			result.append(dir_path + name)
		name = dir.get_next()
	return result
