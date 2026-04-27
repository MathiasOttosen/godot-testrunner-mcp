# agents.nano — never-on context
# ────────────────────────────────────────
# This MCP server is project-agnostic. Point it at any Godot 4 project by
# setting env vars. It does not belong to The Pattern or any single game.


## What this MCP is

Python FastMCP server that gives agents structured access to Godot 4 projects:
run tests, inspect scenes, capture screenshots, query runtime state,
compare visual output. Works headless or with the editor open.

Server path: `server.py` in this repo root.
Registered as `godot-mcp` in Claude Code.


## How to set up for any project

```bash
# Required: point at your target Godot project
export GODOT_PROJECT=/path/to/your/godot/project
export GODOT_BIN=/Applications/Godot.app/Contents/MacOS/Godot

# One-time: install test infrastructure into that project
# Run from your project root:
#   claude "scaffold_tests into this project"

# Verify it works
claude "preflight_project"
```

If `GODOT_PROJECT=/` or unset, the server falls back to searching upward from
cwd for `project.godot`. Running Claude Code from a project root often works
without manual env setup.


## What the MCP does NOT know

The MCP has no knowledge of your project's architecture, naming conventions,
or design docs. It is pure infrastructure — it runs Godot, returns structured
data, and trusts you to interpret results.

Ground truth for test interpretation: the test runner output or screenshot.
The MCP does not decide whether a test passed — it captures output and returns it.


## Quick reference

| Step | Tool | What it does | Cost |
|------|------|-------------|------|
| 1 | `preflight_project()` | Diagnostics, no launch | Free |
| 2 | `check_scaffold()` | Verify test infra installed | Free |
| 3 | `scaffold_tests()` | Install test runner (one-time) | Modifies project |
| 4 | `start_ui_session(headless=true)` | Launch Godot headless | Expensive: launches engine |
| 5 | `call_node_method(...)` | Run a test suite | Cheap: TCP message |
| 6 | `screenshot_ui()` or `capture_scene()` | Visual capture | Medium: needs rendering |
| 7 | `compare_ui_screenshot(name)` | Pixel diff against baseline | Medium: needs screenshot |
| 8 | `end_ui_session()` | Cleanup after work | Free |
