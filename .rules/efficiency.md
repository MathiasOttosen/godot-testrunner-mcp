# MCP Efficiency Rules
# Cost-efficient usage patterns for godot-testrunner-mcp.
# Loaded with min+ context.


## Cost hierarchy (cheapest first)

| Cost | Tool | Why |
|------|------|-----|
| $0 | preflight_project, check_scaffold, get_session_status | File reads + port checks, no Godot launch |
| $1 | plan_verification | Git diff + file reads |
| $2 | inspect_ui_scene | TCP to editor bridge (already running), no new process |
| $$$ | start_ui_session (headless) | Launches Godot subprocess, 15s timeout |
| $$$$ | start_ui_session (UI mode) | Launches Godot with rendering |
| $$$$$ | capture_scene | Full session lifecycle per scene (start → settle → screenshot → end) |


## Rule 1: Preflight always

Every session starts with `preflight_project()`. It costs nothing and tells you:
- Is the editor bridge available? (free inspection path)
- Is scaffold installed? (one-time fix needed)
- Are env vars correct? (saves a wasted launch)

If preflight shows `editor_bridge_available: true`, use `inspect_ui_scene` instead of a runtime session.

## Rule 2: Batch or die

Do not start/stop Godot per assertion.
- Bad: `capture_scene` → inspect output → end → `capture_scene` again → inspect → end
- Good: `start_ui_session` → `call_node_method` (x5) → `screenshot_ui` → `end_ui_session`

One session launch, many operations.

## Rule 3: Headless for logic

For test suites, condition evaluation, resolver routing — use `headless=true`.
The `--headless` flag skips rendering, which is faster and uses less memory.
Only use UI mode when you need to verify something visual.

## Rule 4: Screenshots are expensive

Only capture screenshots when the change is visual-critical:
- Scene file edits (.tscn)
- UI layout scripts
- Rendering changes

For everything else (condition logic, data flow, API shape), use `call_node_method`
on the test runner and read the output. Screenshots add a full render + save + diff
that costs 5-10x more than a headless test run.

## Rule 5: One-time scaffolding

`scaffold_tests()` runs once per project. After that, `check_scaffold()` is the
cheap verifier. Do not re-scaffold unless `check_scaffold()` reports `outdated`.

## Rule 6: Session failure = diagnose before retry

If `start_ui_session` fails, call `get_session_status()` to see the launch result
classification (engine failure, project failure, timeout). Launching Godot again
without understanding why the first attempt failed just wastes another 15s timeout.

## Rule 7: No screenshots for editor bridge inspection

`inspect_ui_scene` returns the node tree as JSON. It does not need rendering.
Using `capture_scene` when `inspect_ui_scene` would suffice is wasting a launch.

## Final checklist before any MCP session

- [ ] Ran preflight_project?
- [ ] Scaffold installed?
- [ ] Editor bridge available? (prefer over runtime session)
- [ ] If runtime needed: headless? Batched work?
- [ ] If screenshot needed: is this visual-critical?
