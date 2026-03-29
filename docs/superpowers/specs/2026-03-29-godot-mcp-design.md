# godot-mcp — Design Spec
*v1.0 · 2026-03-29 · FastMCP 3.x · Python 3.12 · Godot 4*

---

## Purpose

`godot-mcp` is a general-purpose MCP server that gives Claude Code structured access to any Godot 4 project. Its primary goals are:

1. **Verify changes work** — run headless tests and full-game smoke tests, get structured results with minimal token cost
2. **Navigate the codebase** — read scripts, inspect scenes, check syntax errors without pasting files manually
3. **Author and maintain tests** — scaffold test infrastructure, write test suites informed by design docs, track coverage
4. **Analyse testability** — identify systems that can't be tested in isolation and suggest minimal fixes
5. **Manage project settings** — safely read and modify `project.godot` for test setup and teardown

`the_pattern` (Godot 4.6.1 game project at `/Users/kognido/game dev/the_pattern`) is the development testbed and first client. It is not special-cased in the server code.

---

## Configuration

Two environment variables, both required. The server validates them on startup and exits loudly if missing.

| Variable | Description | Example |
|---|---|---|
| `GODOT_BIN` | Absolute path to the Godot binary | `/Applications/Godot.app/Contents/MacOS/Godot` |
| `GODOT_PROJECT` | Absolute path to the Godot project root | `/Users/kognido/game dev/the_pattern` |

---

## Architecture

```
Claude Code
    │
    ▼
godot-mcp  (server.py — FastMCP stdio transport)
    │
    │  Reads config from environment (GODOT_BIN, GODOT_PROJECT)
    │  Registers design docs as MCP resources on startup
    │
    ├─ Project navigation tools
    ├─ Project settings tools
    ├─ Analysis tools
    ├─ Test authoring tools
    ├─ Headless test tools        ← v1: subprocess, no editor required
    ├─ Smoke test tools           ← v1: subprocess, windowed Godot
    ├─ Debug tools
    ├─ Scaffold tool
    └─ [Editor bridge tools]      ← v2: requires EditorPlugin (see below)
            │
            ▼ subprocess (headless or windowed Godot)
    Godot project
            │
            ├─ tests/
            │   ├─ test_runner.gd      ← autoload, activates on --test arg
            │   ├─ base_test.gd        ← base class for all suites
            │   ├─ suites/             ← one file per system under test
            │   └─ smoke/
            │       ├─ smoke_runner.gd ← autoload, activates on --smoke arg
            │       └─ scenarios/      ← one file per scenario
            │
            └─ docs/                   ← registered as MCP resources on startup
```

**Key principle:** The MCP server never parses GDScript logic. It runs Godot and reads structured output. Tests are authored in GDScript, close to the game code.

---

## Three-Tier Test System

### Tier 1 — Unit Tests (headless, ~1–3s, cheap)
Instantiate systems without a scene tree. Pure logic: calculations, data structures, state transitions. No autoloads, no nodes.

### Tier 2 — Integration Tests (headless, ~3–8s, cheap)
Compose multiple systems together. Same runner as Tier 1 — distinction is in how the test author writes it, not in how the server invokes it.

### Tier 3 — Smoke Tests (full game, ~10–20s, expensive)
Run with a display. Drive the game via a scripted autoload. Verify scene loading, UI layout, full mechanic flows. Save screenshots. Used intentionally, not on every iteration.

**Invocation:**
- Tiers 1+2: `godot --headless --path $PROJECT -- --test [suite]`
- Tier 3: `godot --path $PROJECT -- --smoke [scenario]`

Test runner autoloads are always registered in `project.godot` but dormant unless their arg is present. No project settings changes required to run tests.

---

## GDScript Test Infrastructure

Installed by `scaffold_tests()`. Never overwritten once suites exist.

### `tests/base_test.gd`
Base class all suites extend. Provides:
- `assert_eq(a, b, msg?)` — equality check
- `assert_true(condition, msg?)` — boolean check
- `assert_approx(a, b, tolerance, msg?)` — float comparison
- Each failed assertion prints a JSON line immediately:
  `{"test":"suite.method","pass":false,"error":"expected 3 got 2","ms":2}`

### `tests/test_runner.gd`
Autoload. On `--test [suite]` arg:
1. Discovers all scripts in `tests/suites/` (or the named suite)
2. Instantiates each, calls every method prefixed `test_`
3. Collects results
4. Prints a final summary JSON line: `{"total":12,"passed":10,"failed":2,"failed_tests":["sigil.split","attunement.base"]}`
5. Calls `quit()`

### `tests/smoke/smoke_runner.gd`
Autoload. On `--smoke [scenario]` arg:
1. Loads and runs named scenario scripts from `tests/smoke/scenarios/`
2. Each scenario is a script with a `run()` coroutine
3. Scenarios assert visible state (node existence, position, visibility)
4. Optionally saves screenshots via `get_viewport().get_texture().get_image()`
5. Prints structured JSON results, calls `quit()`

### Scaffold version tracking
All scaffold files contain `const SCAFFOLD_VERSION = "1.0"`. `check_scaffold()` verifies this matches the server's expected version.

### Testability fix pattern
For systems that need it (identified by `analyze_testability()`), add one static factory method to the existing script:
```gdscript
static func create_for_test(state: Dictionary) -> SystemName:
    # initialise without scene tree or autoloads
```
No other changes to existing scripts.

---

## MCP Resources

Design docs in `docs/` are registered as MCP resources on server startup. Discovery is dynamic — any `.md` file in `docs/` is registered. This allows Claude Code to pull them as context without a tool call.

Example URIs:
- `godot://docs/artifact-room-gdd`
- `godot://docs/artifact-room-spec`
- `godot://docs/sigil_rules`

---

## Tool Reference

### Setup & Scaffold

**`scaffold_tests()`**
Install the test infrastructure (`test_runner.gd`, `base_test.gd`, `tests/` directory structure) into the configured project. Safe to run on a project that already has tests — never overwrites existing suite files. Registers the test runner autoloads in `project.godot`. Returns a list of files created.

**`check_scaffold()`**
Verify the GDScript test infrastructure is present and matches the server's expected `SCAFFOLD_VERSION`. Returns: status (ok / missing / outdated), version found vs. expected, list of missing files if any.

---

### Analysis

**`analyze_testability()`**
Statically reads all `.gd` files in `scripts/`. Identifies:
- Autoload dependencies (references to singleton names)
- Scene-tree coupling (`get_node`, `$Node`, `@onready`)
- Systems that cannot be instantiated in isolation

Returns a prioritised list: which systems are test-ready, which need a `create_for_test()` factory, and a one-line suggested change for each. Does not modify any files.

**`get_coverage_report()`**
Cross-references scripts in `scripts/` against suites in `tests/suites/`. Returns: covered scripts, uncovered scripts, suite count, total test count. Low token cost — designed to be called at the start of a session.

---

### Project Navigation

**`read_script(path: str)`**
Read any `.gd` file by path relative to the project root. Validates path stays within project root (no traversal). Returns file contents as a string, or a structured error if the file does not exist.

**`list_scripts(directory: str = "scripts/")`**
List all `.gd` files under a directory, relative to the project root. Returns file paths only — not contents. Use `read_script` for contents.

**`list_scenes()`**
List all `.tscn` files in the project. Returns: path, root node name, root node type for each scene.

**`inspect_scene(path: str)`**
Parse a `.tscn` file and return a structured node tree: node names, types, key properties (script attached, visible, position). Raw `.tscn` text is unreadable; this tool is the correct way to understand scene structure. Returns a structured dict, not raw text.

**`check_script(path: str)`**
Run `godot --check-only` on a single script. Returns parsed errors with file path, line number, and message. Fast syntax and type validation without running the game. Returns "no errors" if the script is clean.

**`get_godot_version()`**
Return the version string of the configured Godot binary. Use to confirm the binary is reachable and correct before running other tools.

---

### Project Settings

**`get_project_settings()`**
Parse `project.godot` and return structured output: application settings, autoloads, main scene, display settings, input map, rendering settings. Does not modify any files.

**`set_project_setting(key: str, value: str)`**
Write a single setting to `project.godot`. Creates a backup at `project.godot.mcp_backup` before the first modification in a session. Validates the file parses correctly after writing. Returns the previous value and the new value. Call `restore_project_settings()` to undo.

**`set_autoload(name: str, path: str, enabled: bool = True)`**
Add, update, or remove an autoload entry in `project.godot`. Backs up before first change. Use `enabled=False` to disable an autoload in place (removes the `*` prefix from its path entry in `project.godot`) without deleting it. Returns the resulting autoload table.

**`restore_project_settings()`**
Restore `project.godot` from the session backup (`project.godot.mcp_backup`). Always safe to call. Returns a message indicating whether a backup existed and was restored, or whether no changes had been made.

> **Safety rule:** The server tracks whether a backup exists for the current session. On startup, if a backup file is found (indicating a prior session did not restore), the server logs a warning to stderr and surfaces it in the first tool call response.

---

### Documentation

**`get_godot_docs(class_name: str, method: str = "")`**
Look up a Godot 4 class or method in the official class reference. Returns: description, properties, methods, signals. Use before writing GDScript that uses an unfamiliar API to avoid hallucinated method names or Godot 3 signatures. Fetches from the Godot docs XML source and caches locally at `~/.cache/godot-mcp/docs/`. Cache is invalidated when the Godot version string changes.

---

### Test Authoring

**`get_test_context(system: str, doc: str = "")`**
Bundle context for writing a test suite in one call. Returns:
- Contents of `scripts/{system}.gd`
- Contents of `tests/suites/{system}_tests.gd` if it exists
- Contents of `docs/{doc}.md` if `doc` is specified
- Testability analysis filtered to that system only (subset of what `analyze_testability()` returns for the full project)

Use this before writing or editing a test suite. Cheaper than calling `read_script`, `analyze_testability`, and reading docs separately.

**`write_test_suite(suite_name: str, content: str)`**
Write a new test suite to `tests/suites/{suite_name}_tests.gd`. Validates before writing:
- File extends `BaseTest`
- At least one method prefixed `test_`
Returns an error string if validation fails; does not write.

**`edit_test_suite(suite_name: str, content: str)`**
Overwrite an existing test suite. Same validation as `write_test_suite`. Errors if the suite does not exist — use `write_test_suite` for new suites.

---

### Headless Tests

**`run_tests(suite: str = "all")`**
Run Tier 1/2 tests headlessly. `suite` is either `"all"` or the name of a specific suite file (e.g. `"sigil"`). Returns summary only: pass count, fail count, list of failed test names with one-line errors. Designed to be the first tool called to check project health. Does not return full test output — use `get_test_details` for that.

**`get_test_details(test_name: str)`**
Return the full output for a single failing test: the assertion that failed, the values compared, any print output from that test. Call only when diagnosing a specific failure identified by `run_tests`.

**`get_last_results()`**
Read the cached results from the most recent `run_tests` call (stored in `tests/.last_run.json`). Returns the same structure as `run_tests`. Use at the start of a session to see prior state without re-running. Returns a message if no cached results exist.

---

### Smoke Tests

**`run_smoke_tests(scenario: str = "all")`**
Run Tier 3 smoke tests with a full Godot window. `scenario` is either `"all"` or a specific scenario name. Returns: structured pass/fail per scenario, absolute paths to any screenshots saved, total duration. This tool is intentionally slow and expensive — use it to verify UI and full mechanic flows, not for routine iteration.

---

### Debug

**`run_debug(timeout: int = 10)`**
Run the project headlessly and return raw stdout/stderr output. Use for ad-hoc verification when no test exists yet. Not a substitute for `run_tests` — unstructured output costs more tokens and is harder for Claude Code to act on. `timeout` is in seconds; the process is killed if it does not exit in time.

---

## Data Flow — Headless Test Run

```
Claude Code calls run_tests("sigil")
    │
    ▼
MCP server spawns:
  godot --headless --path $PROJECT -- --test sigil
    │
    ▼
test_runner.gd detects --test arg, runs sigil_tests.gd
    │
    ├─ {"test":"sigil.split_threshold","pass":true,"ms":3}
    ├─ {"test":"sigil.arm_count","pass":false,"ms":1,"error":"expected 4 got 3"}
    └─ {"total":8,"passed":7,"failed":1,"failed_tests":["sigil.arm_count"]}
    │
    ▼
MCP server parses JSON lines, discards passing tests
Returns to Claude Code:
  "7/8 passed. Failed: sigil.arm_count — expected 4 got 3"
```

---

## Error Handling Rules

- All tools return error strings, never raise exceptions. Exceptions crash the tool call silently from Claude Code's perspective.
- Every subprocess call has an explicit timeout. Timed-out processes are killed before returning.
- Path arguments are validated to stay within `GODOT_PROJECT` before any file operation.
- `project.godot` is never written without a backup existing first.
- If Godot outputs nothing (crash before first print), the tool returns a descriptive error, not an empty string.

---

## Token Efficiency Rules

- Summary tools (`run_tests`, `get_coverage_report`, `get_last_results`) return minimal structured output by default.
- Drill-down tools (`get_test_details`, `run_debug`) return full output only when explicitly called.
- `get_test_context` bundles multiple reads into one call to avoid round-trips.
- `inspect_scene` returns structured output, not raw `.tscn` text.
- Passing test results are discarded before returning to Claude Code.

---

## Implementation Notes

- `server.py` is the single file containing all tool definitions. No sub-modules until the file exceeds ~500 lines.
- GDScript scaffold files live in a `scaffold/` directory within the `godot-mcp` repo and are copied into the target project by `scaffold_tests()`.
- Logging goes to `stderr` only. No `print()` calls anywhere in `server.py`.

---

## v2 — Editor Integration

Editor integration is out of scope for v1 but is the natural next layer. It is worth designing the seam now so v2 does not require rearchitecting the server.

**What headless cannot do that editor integration unlocks:**
- Inspect live scene state while editing (not just file-based `.tscn` parsing)
- Trigger test runs from within a running editor session without spawning a separate process
- Real-time error output from the editor's output panel as you make changes
- Manipulate nodes and properties in a live scene

**v2 architecture:**
A GDScript `EditorPlugin` installed in the project listens on a local TCP socket (e.g. `localhost:6789`). The MCP server connects to it when the editor is running and falls back to file-based tools when it is not. Claude Code does not need to know which mode is active — tools behave identically, editor mode just returns richer or more current data.

```
godot-mcp
    │
    ├─ [existing tools]           ← always available
    │
    └─ EditorBridge               ← connects when editor is running
            │  TCP localhost:6789
            ▼
    addons/godot_mcp/plugin.gd    ← EditorPlugin, installed by scaffold_tests()
```

**v2 tools (editor-only):**
- `get_live_scene_tree()` — current scene tree from the running editor
- `get_editor_errors()` — errors currently shown in the editor Output panel
- `set_node_property(path, property, value)` — live property edit in the editor
- `run_editor_tests()` — trigger test run from within the editor context

**Seam to preserve in v1:** `inspect_scene` and project navigation tools should return data in the same shape that editor bridge tools will return. This avoids Claude Code needing to learn a new response format in v2.

---

## Out of Scope (v1)

- Godot editor plugin or live editor connection (v2 — see above)
- Remote/networked MCP transport (stdio only)
- Support for Godot 3.x
- Multiplayer or networked game testing
- Asset pipeline tools (import, export, conversion)
- CI/CD integration (the server is local only)
