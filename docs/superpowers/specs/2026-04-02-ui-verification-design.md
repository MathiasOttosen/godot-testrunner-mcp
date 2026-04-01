# UI Verification — Design Spec
*v1.0 · 2026-04-02 · godot-mcp · Editor Bridge (v2 fast-track)*

---

## Purpose

Enable Claude Code to verify its own UI edits against a spec by capturing live runtime UI state from a Godot 4 project. Covers two cases:

1. **Scene-direct inspection** — load a specific scene and capture its UI tree after `_ready` runs (~0.5s, no game launch)
2. **Game-flow inspection** — launch the full game, drive it via input events and scene transitions, capture UI state at any point

This is not pixel-diff regression testing. The output is structured JSON (node names, types, visibility, position, size, text) that Claude Code can reason about against a written spec.

---

## Architecture

Two runtime components, each with its own role:

```
Claude Code
    │
    ▼
godot-mcp server.py (EditorBridge)
    │
    ├─ localhost:6789 ──────────────► addons/godot_mcp/plugin.gd  (EditorPlugin)
    │                                  SubViewport scene inspection
    │                                  Requires editor to be open
    │
    └─ localhost:6790 ──────────────► addons/godot_mcp/remote_control.gd  (Autoload)
                                       Live game session
                                       Activated with --mcp flag
                                       Editor NOT required
```

**`addons/godot_mcp/plugin.gd`** — EditorPlugin. Starts a TCP server on `localhost:6789` when the editor opens. Loads scenes into a managed SubViewport, advances 3 frames so `_ready` runs, captures node state. Stops the TCP server on editor close.

**`addons/godot_mcp/remote_control.gd`** — Autoload. Activates only when the game is launched with the `--mcp` flag. Starts a TCP server on `localhost:6790`. Handles live game state: receives input events, scene transitions, and UI state queries. Does not activate in normal gameplay.

**`EditorBridge` (Python class in `server.py`)** — wraps both TCP connections. Routes commands to the appropriate component. Connection is opened per-call for the editor plugin (stateless); held open for the duration of a game session.

---

## Protocol

Newline-delimited JSON over TCP. Each message is one JSON object followed by `\n`. Synchronous: one request, one response.

**Request:**
```json
{"cmd": "get_ui", "depth": 2}
```

**Response (success):**
```json
{"ok": true, "tree": {...}}
```

**Response (error):**
```json
{"ok": false, "error": "scene not loaded"}
```

### EditorPlugin commands (port 6789)

| Command | Params | Response key |
|---|---|---|
| `load_scene` | `path: str` | `ok` |
| `get_ui` | `depth: int` | `tree` |
| `screenshot` | `save_path: str?` | `path` |
| `unload` | — | `ok` |

### RemoteControl commands (port 6790)

| Command | Params | Response key |
|---|---|---|
| `get_ui` | `depth: int` | `tree` |
| `change_scene` | `path: str` | `ok` |
| `send_input` | `type: str`, `params: dict` | `ok` |
| `screenshot` | `save_path: str?` | `path` |
| `quit` | — | `ok` |

### UI tree node structure

```json
{
  "name": "ScoreLabel",
  "type": "Label",
  "visible": true,
  "text": "Score: 0",
  "position": [120, 40],
  "size": [200, 32],
  "children": []
}
```

Only `CanvasItem` descendants are included (Control, Node2D subtypes). Pure logic nodes (`Node`, `Timer`, etc.) are excluded. `children` is populated up to the requested depth; beyond that it is an empty array.

---

## MCP Tools

Six new tools added to `server.py`.

### `inspect_ui_scene(path: str, depth: int = 1) → str`
Load a scene into the EditorPlugin's SubViewport, advance 3 frames so `_ready` runs, return the UI tree as JSON. Fast (~0.5s). Requires the Godot editor to be open with the project loaded. Each call is a full load/unload cycle — any previously loaded scene is unloaded first. Use after editing a `.tscn` or a script that populates UI in `_ready`.

### `start_ui_session(scene_path: str = "", timeout: int = 15) → str`
Launch the game subprocess with `--mcp` flag. Waits for the RemoteControl autoload to connect on `:6790`. If `scene_path` is given, the game changes to that scene immediately after the connection is established. Returns confirmation when the session is ready. Editor does not need to be open.

### `navigate_ui(action: str, params: dict = {}) → str`
Send a navigation or input command to the active session. `action` values:
- `"change_scene"` + `params={"path": "scenes/gameplay.tscn"}`
- `"press_button"` + `params={"node_path": "MainMenu/StartButton"}`
- `"input_action"` + `params={"action": "ui_accept"}`

Requires an active session started by `start_ui_session`.

### `get_live_ui(depth: int = 1) → str`
Return the current UI tree from the active session. Call after navigation to verify state. Returns the same JSON structure as `inspect_ui_scene`.

### `screenshot_ui(save_path: str = "") → str`
Capture the current viewport. If `save_path` is empty, saves to `tests/ui_screenshots/<timestamp>.png` in the project root. Returns the absolute path to the saved file. If a live game session is active, captures from it; otherwise falls back to the EditorPlugin's SubViewport.

### `end_ui_session() → str`
Send `quit` to the running game and close the TCP connection. Safe to call if the session has already ended.

---

## GDScript Components

### `addons/godot_mcp/plugin.gd`

```
class_name GodotMCPPlugin
extends EditorPlugin

- _enter_tree(): start TCP server on :6789
- _exit_tree(): stop TCP server, kill SubViewport
- _handle_command(cmd): dispatch to load_scene / get_ui / screenshot / unload
- load_scene(path): ResourceLoader.load + SubViewport.add_child, advance 3 frames
- get_ui(root, depth): recursive CanvasItem walker, returns Dictionary
- screenshot(save_path): SubViewport.get_texture().get_image().save_png()
```

Advancing frames uses `await get_tree().process_frame` three times so `_ready` and one `_process` tick complete before capturing.

### `addons/godot_mcp/remote_control.gd`

```
extends Node

- _ready(): check for --mcp in OS.get_cmdline_args(), start TCP server on :6790 if present
- _handle_command(cmd): dispatch to change_scene / send_input / get_ui / screenshot / quit
- get_ui(root, depth): same walker as plugin, operates on get_tree().current_scene
- send_input(type, params): Input.parse_input_event() or get_tree().root.propagate_input_event()
```

The autoload is registered in `project.godot` by `scaffold_tests()` (alongside the existing test runner autoloads). It is always present in the autoload table but dormant unless `--mcp` is in the command-line args.

---

## Error Handling

All tools return error strings, never raise exceptions.

| Situation | Return value |
|---|---|
| `inspect_ui_scene` with editor not running | `"Error: editor bridge not available — is the Godot editor open?"` |
| `navigate_ui` / `get_live_ui` / `screenshot_ui` with no active session | `"Error: no active UI session — call start_ui_session first"` |
| `start_ui_session` timeout | Kills subprocess, returns `"Error: game did not connect within {timeout}s — check for autoload errors"` |
| TCP connection drops mid-session | `"Error: session disconnected — call start_ui_session to reconnect"` |
| `load_scene` with missing resources | Godot's error string returned as-is |
| Path outside project root | `"Error: path escapes project root"` |

---

## Scaffold Changes

`scaffold_tests()` is extended to install the addon files. New behaviour:

- Creates `addons/godot_mcp/` directory in the target project
- Copies `plugin.gd` and `remote_control.gd` from the `scaffold/` directory in this repo
- Creates `addons/godot_mcp/plugin.cfg` (required for EditorPlugins)
- Registers `remote_control.gd` as an autoload in `project.godot`
- Does NOT enable the EditorPlugin automatically — user must enable it once in the editor (Project → Project Settings → Plugins)
- Creates `tests/ui_screenshots/` directory with a `.gitkeep`

`check_scaffold()` gains awareness of these new files and reports them as missing if absent.

---

## Typical Workflow

```
# After editing scenes/hud.tscn:
inspect_ui_scene("scenes/hud.tscn")
→ {"name": "HUD", "type": "CanvasLayer", "children": [...]}

# After editing scripts that affect the main menu:
start_ui_session()
get_live_ui(depth=2)
screenshot_ui()
end_ui_session()

# To verify a flow (main menu → gameplay HUD):
start_ui_session()
navigate_ui("press_button", {"node_path": "MainMenu/StartButton"})
get_live_ui(depth=2)
screenshot_ui()
end_ui_session()
```

---

## Out of Scope

- Pixel-diff regression testing (screenshots are evidence, not assertions)
- Automated CI/CD UI testing (local only)
- Godot 3.x support
- Multi-window or split-screen UI inspection
- Audio or animation state capture
