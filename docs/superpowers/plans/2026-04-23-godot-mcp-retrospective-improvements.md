# Godot MCP Retrospective Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce repeated Godot development friction seen in the 2026-04-22 and 2026-04-23 retrospectives by making godot-mcp faster to diagnose, more reliable for visual capture, and more explicit about project/runtime readiness.

**Architecture:** Add a thin reliability layer around the existing MCP runtime rather than replacing it. The Python server owns project preflight, launch/capture routing, structured diagnostics, and command ergonomics; the Godot scaffold owns reusable runtime helpers for screenshots, scene settling, and UI metadata; documentation owns the recommended workflow so agents switch paths quickly when the editor bridge or headless mode is unsuitable.

**Tech Stack:** Python 3.12, FastMCP, pytest, Pillow, Godot 4 GDScript scaffold, local Godot project `/Users/kognido/game-dev/the_pattern`.

---

## Retrospective Findings

Source retrospectives:
- `/Users/kognido/game-dev/the_pattern/.Codex/2026-04-22-room-journal-redesign-retrospective.md`
- `/Users/kognido/game-dev/the_pattern/.Codex/2026-04-23-night0-sigil-system-retrospective.md`
- `/Users/kognido/game-dev/the_pattern/.Codex/ui_critical_scripts.json`

Repeated issues:
- The editor bridge is useful when available, but visual validation stalls when `inspect_ui_scene` is unavailable or the editor/plugin is not reachable.
- Runtime launch can use the wrong project path or launch mode, especially when headless mode triggers project test autoloads instead of a controllable MCP session.
- Screenshot validation works best through direct runtime capture, but the current workflow still encourages ad hoc temporary scripts when MCP capture is flaky.
- Long-running filtered Godot commands can wait silently due to process buffering, causing wasted polling and unclear progress.
- Agents need focused structural verification early, then visual verification as a separate explicit phase, especially for UI-critical scripts.
- The project maintains a list of UI-critical scripts, but godot-mcp does not consume or operationalize that list.

Existing capabilities to preserve:
- `start_ui_session()` already returns structured launch classifications.
- `screenshot_ui()`, `compare_ui_screenshot()`, and `update_baseline()` already exist.
- Runtime control supports input events, node queries, frame stepping, pause control, and method calls.
- The scaffolded `RemoteControl` already advertises commands and stays active while paused.

---

## Priority Roadmap

### P0: Project Preflight and Self-Diagnosis

**Problem:** Sessions lose time when MCP is pointed at the wrong project, the scaffold is stale, the editor bridge is unavailable, or the runtime mode is incompatible.

**Outcome:** A single `preflight_project()` tool tells the agent whether it should use editor inspection, runtime MCP, direct screenshots, or plain Godot tests before spending time on a failing path.

**Files:**
- Modify: `/Users/kognido/game-dev/godot-mcp/server.py`
- Create: `/Users/kognido/game-dev/godot-mcp/tests/test_preflight.py`
- Modify: `/Users/kognido/game-dev/godot-mcp/README.md`

**Implementation tasks:**
- [ ] Add a private `_project_preflight()` helper that returns JSON-safe diagnostics:
  - `project_path`
  - `project_exists`
  - `project_godot_exists`
  - `godot_bin`
  - `godot_bin_exists`
  - `scaffold_status`
  - `editor_bridge_available`
  - `remote_port_busy`
  - `recommended_path`
  - `warnings`
- [ ] Add an MCP tool `preflight_project()` that serializes `_project_preflight()` with indentation.
- [ ] Reuse existing `check_scaffold()` logic rather than duplicating file checks.
- [ ] Detect editor bridge availability by attempting a short TCP connection to port `6789`.
- [ ] Detect remote port conflicts by attempting a short TCP connection to port `6790`; report it as "busy" rather than assuming it is a valid session.
- [ ] Recommend `runtime_session` when the editor bridge is unavailable but scaffold files exist.
- [ ] Recommend `scaffold_tests` when scaffold files are missing.
- [ ] Recommend `fix_environment` when `GODOT_PROJECT`, `GODOT_BIN`, or `project.godot` is invalid.
- [ ] Write pytest coverage for valid project, missing project file, missing scaffold, editor bridge unavailable, and remote port busy.

**Acceptance criteria:**
- `uv run pytest tests/test_preflight.py -q` passes.
- `preflight_project()` never launches Godot.
- The return shape is stable and machine-readable.
- The recommendation is specific enough for an agent to choose the next tool without guessing.

---

### P1: Direct Runtime Capture as a First-Class Fallback

**Problem:** When the editor bridge fails, agents currently rediscover that direct runtime screenshots are faster and more reliable. In one session, a temporary SceneTree script was created and removed to get visual evidence.

**Outcome:** MCP offers an explicit "capture this scene directly" tool that starts a runtime session, settles frames, captures a screenshot, and tears down cleanly.

**Files:**
- Modify: `/Users/kognido/game-dev/godot-mcp/server.py`
- Modify: `/Users/kognido/game-dev/godot-mcp/scaffold/addons/godot_mcp/remote_control.gd`
- Create: `/Users/kognido/game-dev/godot-mcp/tests/test_direct_capture.py`

**Implementation tasks:**
- [ ] Add an MCP tool `capture_scene(scene_path: str, save_path: str = "", settle_frames: int = 3, headless: bool = false)`.
- [ ] Validate `scene_path` and `save_path` with `safe_path()`.
- [ ] Internally call the same launch path as `start_ui_session()` with `launch_mode="ui"` by default.
- [ ] After handshake, call `await_frames(settle_frames)` before screenshot.
- [ ] Capture with `_bridge.screenshot()`.
- [ ] Always attempt `end_session()` in a `finally` block so failed screenshots do not leave processes open.
- [ ] Return structured JSON containing `status`, `scene_path`, `screenshot_path`, `viewport_size`, `frame`, `launch`, and `warnings`.
- [ ] Add tests that mock `_bridge.start_session`, `_bridge.send_session_command`, `_bridge.screenshot`, and `_bridge.end_session`.
- [ ] Make failure tests prove that `end_session()` is called after launch success even when frame wait or screenshot fails.

**Acceptance criteria:**
- `capture_scene()` gives agents one command for the successful workaround discovered in the retrospective.
- The tool defaults to normal display mode, not headless, because headless can trigger test autoload exits in projects like `/Users/kognido/game-dev/the_pattern`.
- Failure responses include launch metadata when startup fails.
- `uv run pytest tests/test_direct_capture.py -q` passes.

---

### P2: Verification Route Planner

**Problem:** Agents waste time choosing between `inspect_ui_scene`, `start_ui_session`, screenshot comparison, full Godot tests, and direct capture. The project has UI-critical script metadata, but MCP does not help interpret it.

**Outcome:** A `plan_verification()` tool converts changed file paths into recommended verification steps.

**Files:**
- Modify: `/Users/kognido/game-dev/godot-mcp/server.py`
- Create: `/Users/kognido/game-dev/godot-mcp/tests/test_verification_planner.py`
- Modify: `/Users/kognido/game-dev/godot-mcp/README.md`

**Implementation tasks:**
- [ ] Add a helper `_load_ui_critical_scripts(project_path: str)` that reads `.Codex/ui_critical_scripts.json` when present.
- [ ] Add an MCP tool `plan_verification(changed_files: list[str] | None = None)`.
- [ ] If `changed_files` is omitted, optionally inspect `git diff --name-only` in `GODOT_PROJECT`; if git is unavailable, return a clear warning and an empty file list.
- [ ] Mark files listed in `.Codex/ui_critical_scripts.json` as requiring visual validation.
- [ ] Mark `.tscn` files as requiring structural scene inspection or runtime capture.
- [ ] Mark `tests/**/*.gd` and non-visual scripts as requiring targeted Godot tests first.
- [ ] Include recommended commands/tool calls in the response:
  - `preflight_project()`
  - `inspect_ui_scene(...)` when editor bridge is available and scene-direct inspection is appropriate
  - `capture_scene(...)` when editor bridge is unavailable or scripts build UI procedurally
  - `compare_ui_screenshot(...)` when a baseline name can be inferred
  - project test command guidance when visual validation is not required
- [ ] Add tests for UI-critical scripts, scene files, unknown files, missing metadata, and dirty git fallback.

**Acceptance criteria:**
- A changed file like `scripts/night_zero_room.gd` produces a visual-validation recommendation.
- A changed file like `scripts/sigil_renderer.gd` recommends screenshot or pixel-diff validation.
- Missing `.Codex/ui_critical_scripts.json` is a warning, not a failure.
- `uv run pytest tests/test_verification_planner.py -q` passes.

---

### P3: Better Runtime Observability and Non-Silent Waits

**Problem:** Long filtered Godot commands and runtime launches sometimes wait silently. MCP currently returns launch logs at the end, but agents need clearer progress and post-failure evidence.

**Outcome:** Session startup and frame waits expose bounded evidence without forcing agents to poll silent processes.

**Files:**
- Modify: `/Users/kognido/game-dev/godot-mcp/server.py`
- Modify: `/Users/kognido/game-dev/godot-mcp/scaffold/addons/godot_mcp/remote_control.gd`
- Create: `/Users/kognido/game-dev/godot-mcp/tests/test_runtime_observability.py`

**Implementation tasks:**
- [ ] Add `get_session_status()` MCP tool returning whether a session process exists, whether the socket is connected, the last launch command, and recent captured lines.
- [ ] Store the most recent `_LaunchObservation` summary on `EditorBridge` after successful and failed launches.
- [ ] Add `timeout` and `actual_frames` details to failed `await_frames` and `step_frames` responses from the Godot scaffold.
- [ ] Include elapsed time in `start_ui_session()` results for both success and failure.
- [ ] Add pytest coverage for launch observation storage and `get_session_status()` with no session, live session mock, and failed launch mock.

**Acceptance criteria:**
- Agents can ask for status after a failed or slow session without re-launching Godot.
- Launch output evidence is bounded to avoid huge token dumps.
- Existing startup classification tests continue passing.

---

### P4: Safer Scene and Node Introspection

**Problem:** Retrospectives favored focused fake-node tests and targeted controller-state checks. MCP helps with `get_node()` and `call_node_method()`, but inspecting scripted state still requires knowing exact paths and properties.

**Outcome:** MCP provides safer discovery and state snapshots for focused runtime verification.

**Files:**
- Modify: `/Users/kognido/game-dev/godot-mcp/scaffold/addons/godot_mcp/mcp_tree.gd`
- Modify: `/Users/kognido/game-dev/godot-mcp/scaffold/addons/godot_mcp/remote_control.gd`
- Modify: `/Users/kognido/game-dev/godot-mcp/server.py`
- Create: `/Users/kognido/game-dev/godot-mcp/tests/test_node_introspection.py`

**Implementation tasks:**
- [ ] Extend `find_nodes` to support partial name matching with a boolean `contains` parameter while preserving exact-match default behavior.
- [ ] Add `get_node_snapshot(node_path, properties, include_children=false, depth=1)` as a clearer alias around targeted node data.
- [ ] Include script path in node data when `node.get_script()` is available.
- [ ] Return property-not-found errors as structured entries rather than string placeholders where possible.
- [ ] Add tests that verify Python command payloads and GDScript command advertisement.

**Acceptance criteria:**
- Existing `find_nodes()` behavior remains backwards compatible.
- Agents can discover nodes by partial name without dumping the entire tree.
- State verification can cite script-backed nodes and selected properties.

---

### P5: Documentation and Agent Workflow

**Problem:** The retrospectives contain useful local lessons, but godot-mcp does not yet encode them as a repeatable workflow.

**Outcome:** README and docs explain the intended fast path and fallback path.

**Files:**
- Modify: `/Users/kognido/game-dev/godot-mcp/README.md`
- Create: `/Users/kognido/game-dev/godot-mcp/docs/superpowers/specs/2026-04-23-retrospective-improvements-design.md`

**Implementation tasks:**
- [ ] Document the recommended verification sequence:
  - Run `preflight_project()`.
  - Use targeted tests or focused node inspection first.
  - Use `inspect_ui_scene()` only when the editor bridge is healthy and scene-direct loading is appropriate.
  - Use `capture_scene()` quickly after editor bridge failure.
  - Use `compare_ui_screenshot()` for UI-critical changes with baselines.
- [ ] Document launch mode guidance:
  - Default to UI runtime for visual capture.
  - Use `headless=true` only when the project is known not to auto-run tests in headless mode.
  - Treat `launch_failed_autoload_exit` as a mode mismatch unless the goal was tests.
- [ ] Document how `.Codex/ui_critical_scripts.json` influences verification planning.
- [ ] Add one worked example based on `scripts/night_zero_room.gd`.
- [ ] Add one worked example based on `scripts/sigil_renderer.gd`.

**Acceptance criteria:**
- A future agent can read the README and avoid the exact visual-bridge retry loop described in the retrospectives.
- Documentation distinguishes structural checks, runtime state checks, screenshot evidence, and pixel-diff validation.

---

## Suggested Implementation Order

1. P0 `preflight_project()` first, because it prevents wasted work across all later tasks.
2. P1 `capture_scene()` second, because it directly addresses the repeated visual validation bottleneck.
3. P2 `plan_verification()` third, because it depends on the direct-capture fallback being available.
4. P3 observability fourth, because it improves diagnosis after the core workflow is in place.
5. P4 introspection fifth, because it is valuable but less urgent than visual capture reliability.
6. P5 documentation throughout, with final examples after tools are implemented.

---

## Verification Strategy

Run unit tests after each task:

```bash
uv run pytest tests/test_preflight.py -q
uv run pytest tests/test_direct_capture.py -q
uv run pytest tests/test_verification_planner.py -q
uv run pytest tests/test_runtime_observability.py -q
uv run pytest tests/test_node_introspection.py -q
```

Run the existing suite before considering the plan complete:

```bash
uv run pytest -q
```

Manual smoke checks against `/Users/kognido/game-dev/the_pattern`:

```text
preflight_project()
plan_verification(["scripts/night_zero_room.gd"])
capture_scene("scenes/night_zero.tscn", save_path="tests/ui_screenshots/night_zero_capture.png")
compare_ui_screenshot("night_zero", threshold=0.02)
end_ui_session()
```

Expected smoke-check behavior:
- Preflight reports the configured project and whether the editor bridge is available.
- Verification planning marks `scripts/night_zero_room.gd` as visual-critical if the project metadata is present.
- Direct capture produces a screenshot without creating temporary project scripts.
- Pixel diff either passes against an existing baseline or returns `baseline_not_found` with the captured screenshot path.

---

## Risks and Tradeoffs

- A direct-capture tool can accidentally hide editor-bridge regressions if agents always bypass the editor. Mitigation: `preflight_project()` should still report editor bridge health, and docs should preserve the distinction between editor scene inspection and runtime capture.
- Reading `.Codex/ui_critical_scripts.json` introduces project-specific convention into a generic MCP. Mitigation: treat the file as optional metadata and never fail when it is absent.
- `capture_scene()` launching a visible UI can be slower than headless mode. Mitigation: default to correctness and reliability; allow `headless=true` only as an explicit opt-in.
- `plan_verification()` recommendations can be wrong for unknown projects. Mitigation: include warnings and confidence rather than presenting the plan as authoritative.

---

## Definition of Done

- All new unit tests pass with `uv run pytest -q`.
- The new tools return structured JSON rather than prose-only strings.
- The direct visual fallback no longer requires ad hoc temporary capture scripts.
- The workflow explicitly handles editor bridge failure, headless autoload exits, and UI-critical script changes.
- README examples cover the retrospective failure modes and the recommended fast path.
