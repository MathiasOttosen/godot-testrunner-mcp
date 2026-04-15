extends Node
## Base class for all godot-mcp test suites.

const SCAFFOLD_VERSION = "1.1"

var _results: Array[Dictionary] = []


func _run_tests() -> Array[Dictionary]:
	_results = []
	for method in get_method_list():
		var name: String = method["name"]
		if not name.begins_with("test_"):
			continue
		var start := Time.get_ticks_msec()
		call(name)
		var ms := Time.get_ticks_msec() - start
	return _results


func assert_eq(a, b, msg: String = "") -> void:
	var label := msg if msg != "" else "expected %s got %s" % [b, a]
	var passed := a == b
	var result := {"test": get_script().resource_path + "::" + _current_test, "pass": passed, "ms": 0}
	if not passed:
		result["error"] = label
	_results.append(result)
	print(JSON.stringify(result))


func assert_true(condition: bool, msg: String = "") -> void:
	assert_eq(condition, true, msg if msg != "" else "expected true")


func assert_approx(a: float, b: float, tolerance: float, msg: String = "") -> void:
	assert_true(abs(a - b) <= tolerance, msg if msg != "" else "expected %f ≈ %f (±%f)" % [a, b, tolerance])


var _current_test: String = ""
