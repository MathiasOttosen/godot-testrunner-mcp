# agents.min — on-demand MCP tool reference
# ────────────────────────────────────────
# Load this file when actively using MCP tools to run tests, inspect scenes,
# or validate changes. User says "[min] run the test suite for core/".


## When to load

User uses `[min]` or `[full]` prefix, or the task involves running Godot tests,
inspecting runtime state, capturing screenshots, or any MCP tool usage.


## Tool reference by use case

### Diagnostics (always safe, no launch cost)

| Tool | Parameters | Returns |
|------|-----------|---------|
| `preflight_project()` | none | Project path, scaffold status, bridge availability, warnings. First call every session. |
| `get_session_status()` | none | Active session state, last launch result. Check after failed/slow launch. |
| `check_scaffold()` | none | ok/missing/outdated with files list. |

### Test infrastructure (one-time per project)

| Tool | Parameters | Returns |
|------|-----------|---------|
| `scaffold_tests()` | none | List of created files. Never overwrites existing suite files. Run once. |
| `plan_verification(changed_files)` | optional file list | Verification steps per file. Uses .Codex/ui_critical_scripts.json if present. |

### Editor inspection (requires Godot editor open, port 6789)

| Tool | Parameters | Returns |
|------|-----------|---------|
| `inspect_ui_scene(path, depth)` | scene path, depth (default 1) | UI node tree JSON. One load/unload cycle per call. |

### Runtime sessions (launches Godot, expensive — batch work)

Session lifecycle: `start_ui_session()` → tools → `end_ui_session()`

| Tool | Parameters | Returns |
|------|-----------|---------|
| `start_ui_session(scene_path, timeout, headless)` | optional scene, 15s default, bool | Launch status with classification on failure |
| `end_ui_session()` | none | Cleanup. Safe to call without active session. |

While session is active:

| Tool | Parameters | Returns |
|------|-----------|---------|
| `get_live_ui(depth)` | depth (default 1) | UI node tree JSON |
| `get_node(node_path, properties)` | path + optional property list | Node data JSON |
| `find_nodes(name, type, contains)` | filters | Matching node paths |
| `get_node_snapshot(path, properties, children, depth)` | detailed filters | Targeted node data |
| `call_node_method(path, method, args)` | node, method, optional args | Return value JSON |
| `send_key(key, pressed, shift, ctrl, alt)` | key name + modifiers | ok or error |
| `click(x, y, button)` | coordinates, button (1=left) | ok or error |
| `screenshot_ui(save_path)` | optional path | Screenshot path + metadata |
| `capture_scene(scene_path, save_path, settle_frames, timeout, headless)` | full params | Full session lifecycle per scene (start → settle → capture → end) |
| `await_frames(n)` | frame count | Blocks until n frames pass |
| `set_tree_paused(paused)` | bool | ok or error |
| `set_engine_time_scale(scale)` | float multiplier | ok or error |
| `step_frames(n)` | frame count | Advance n frames atomically |

### Visual validation

| Tool | Parameters | Returns |
|------|-----------|---------|
| `compare_ui_screenshot(name, threshold)` | baseline name, 0.02 default | Diff result JSON with ratio, pass/fail, diff image path |
| `update_baseline(name)` | baseline name | Promotes last screenshot to baseline + git add |


## Common session workflow for testing

```text
1. preflight_project()                           # cheap diagnostics
2. start_ui_session(headless=true)              # launch (15s timeout)
3. call_node_method("GodotMCPTestRunner",       # run test suite
     "run_suite", ["test_condition_evaluator"])
4. end_ui_session()                              # cleanup
```

For multiple test suites, batch them in one session:
```text
1. start_ui_session(headless=true)
2. call_node_method("GodotMCPTestRunner", "run_suite", ["test_condition_evaluator"])
3. call_node_method("GodotMCPTestRunner", "run_suite", ["test_content_resolver"])
4. call_node_method("GodotMCPTestRunner", "run_suite", ["test_delivery_session"])
5. end_ui_session()
```


## Execution rules

1. Always run `preflight_project()` first — cheapest diagnostic, avoids wasted launches.
2. Prefer editor bridge (port 6789) over runtime session when editor is open.
3. Batch all verifications in one session instead of starting/stopping per assertion.
4. For logic tests, use headless mode. Screenshots are for visual validation only.
5. If a session launch fails, call `get_session_status()` before retrying to understand why.
