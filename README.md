# godot-mcp

MCP server and Godot 4 scaffold for test, runtime, UI, and screenshot verification workflows.

## Retrospective-Driven Workflow

Use this sequence when working on Godot UI or runtime changes:

1. Run `preflight_project()` before choosing a verification path.
2. Run focused Godot tests or targeted node/state inspection for logic/controller changes.
3. Use `inspect_ui_scene()` only when the Godot editor bridge is healthy and scene-direct loading fits the change.
4. Switch quickly to `capture_scene()` when the editor bridge is unavailable, flaky, or the screen is built procedurally.
5. Use `compare_ui_screenshot()` for visual-critical files with baselines.

The key lesson from recent Godot development sessions is to separate structural/runtime checks from visual validation. Avoid spending multiple attempts on an unavailable editor bridge; use direct runtime capture instead.

## Environment Tools

### `preflight_project()`

Returns JSON diagnostics without launching Godot:

- Project path and `project.godot` presence
- Configured project path when it differs from the resolved project path
- `GODOT_BIN` presence
- Scaffold status
- Editor bridge availability on port `6789`
- Remote-control port status on port `6790`
- Recommended next path

If `GODOT_PROJECT` is unset, points at `/`, or points at a directory without `project.godot`, godot-mcp searches upward from the MCP process working directory for the nearest `project.godot`. This lets agents launched from a Godot project recover from a bad inherited `GODOT_PROJECT=/` setting.

Recommended paths:

- `fix_environment`: project or Godot binary configuration is invalid.
- `scaffold_tests`: MCP scaffold files are missing or outdated.
- `runtime_session`: use runtime MCP tools because scaffold is available but editor bridge is not.
- `editor_bridge_or_runtime_session`: both editor and runtime paths may be available.

`check_scaffold()` also detects stale MCP addon protocol files. Running `scaffold_tests()` refreshes the MCP-owned addon scripts while preserving existing project test-suite files.

### `plan_verification(changed_files)`

Converts changed project paths into recommended verification steps. If the target project contains `.Codex/ui_critical_scripts.json`, files listed there are treated as visual-critical and routed toward screenshot validation.

Example:

```text
plan_verification(["scripts/night_zero_room.gd"])
```

For visual-critical procedural UI, prefer:

```text
capture_scene("scenes/night_zero.tscn")
compare_ui_screenshot("night_zero")
```

For scene files, use editor inspection when available and runtime capture as the fallback:

```text
inspect_ui_scene("scenes/room.tscn", depth=3)
capture_scene("scenes/room.tscn")
```

## Runtime Capture

### `capture_scene(scene_path, save_path="", settle_frames=3, timeout=15, headless=false)`

Launches a short MCP runtime session, waits a few frames, captures a screenshot, and quits. It defaults to normal UI mode rather than headless mode because some projects run test autoloads and exit in headless launches.

Use `headless=true` only when the project is known to keep the MCP remote control alive in headless mode.

## Session Observability

### `get_session_status()`

Returns whether a runtime session socket is active, whether the Godot process is still running, and the most recent launch result. Use it after a failed or slow launch before starting another runtime session.

`start_ui_session()` results include `elapsed_seconds` so agents can distinguish quick launch failures from slow startup timeouts.

## Targeted Introspection

### `find_nodes(name="", type="", contains=false)`

Searches the live scene tree by exact name/type, or by partial name when `contains=true`.

### `get_node_snapshot(node_path, properties=[], include_children=false, depth=1)`

Returns a focused node snapshot with optional properties and optional child context. Scaffolded node data includes `script_path` when available and structured `property_errors` for missing requested properties.

## Visual Validation Examples

For `scripts/night_zero_room.gd`, which builds the Night Zero scene procedurally:

```text
preflight_project()
plan_verification(["scripts/night_zero_room.gd"])
capture_scene("scenes/night_zero.tscn", save_path="tests/ui_screenshots/night_zero_capture.png")
compare_ui_screenshot("night_zero")
```

For `scripts/sigil_renderer.gd`, which draws journal sigil geometry:

```text
preflight_project()
plan_verification(["scripts/sigil_renderer.gd"])
start_ui_session("scenes/room.tscn")
get_node_snapshot("Journal", ["visible"], include_children=true, depth=2)
compare_ui_screenshot("journal_open")
end_ui_session()
```
