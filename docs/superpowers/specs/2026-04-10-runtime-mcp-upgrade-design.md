# Runtime MCP Upgrade Design

**Date:** 2026-04-10
**Status:** Approved

## Background

A post-verification report identified that godot-mcp's runtime surface was too narrow for non-`Control` gameplay scenes. The core gaps were:

- Input support limited to `press_button` and `input_action` — raw key/mouse injection required OS automation
- `get_ui` only exposed `Control` geometry — gameplay nodes (Node2D, CharacterBody2D, Camera2D) invisible
- No synchronization primitives — verification required `sleep` polling
- `--mcp-scene` startup used wrong lifecycle point, producing "parent busy" warnings
- `_get_ui_tree` duplicated between `plugin.gd` and `remote_control.gd`, drifting over time

This design addresses all seven identified improvement areas.

---

## Approach

**Approach B: Shared helper + in-place expansion.**

- New `mcp_tree.gd` static class owns all node serialization logic
- `plugin.gd` and `remote_control.gd` both preload it
- New commands added in-place to each file
- `remote_control.gd` gets a formal state machine for `await_*` primitives
- `server.py` gets new MCP tools wrapping each new command

---

## File Changes

```
scaffold/addons/godot_mcp/
├── mcp_tree.gd          ← NEW
├── plugin.gd            ← updated
└── remote_control.gd    ← updated
server.py                ← updated
```

`scaffold_tests()` in `server.py` updated to copy `mcp_tree.gd` alongside the other addon files.

---

## Section 1: `mcp_tree.gd` (new)

`class_name MCPTree` — all static functions, no instances.

### `get_ui_tree(node: Node, depth: int) -> Dictionary`

Unified node serializer. Fields emitted by node type:

| Applies to | Fields |
|---|---|
| All nodes | `name`, `type`, `path` (node path string) |
| `CanvasItem` | `visible` |
| `Control` | `position [x,y]`, `size [x,y]` |
| `Node2D` | `position [x,y]`, `global_position [x,y]`, `rotation`, `scale [x,y]` |
| `Camera2D` | `zoom [x,y]` (plus Node2D fields) |
| `CharacterBody2D` | `velocity [x,y]` |
| `RigidBody2D` | `linear_velocity [x,y]` |
| `Label`, `Button`, `LineEdit`, `RichTextLabel` | `text` |

Children filtered to `CanvasItem` (Node2D is a CanvasItem — no change to filter). Depth works as today.

### `get_node_data(node: Node, extra_properties: Array) -> Dictionary`

Single-node snapshot (no children). Same fields as above, plus any caller-requested property names pulled via `node.get(prop)`. For a missing or unreadable property, the key's value is set to `"<error: property not found>"` rather than failing the whole call.

---

## Section 2: `remote_control.gd` changes

### Startup fix

Replace in `_ready()`:
```gdscript
get_tree().change_scene_to_file(scene_path)
```
with:
```gdscript
get_tree().change_scene_to_file.call_deferred(scene_path)
```
Eliminates the "parent busy adding/removing children" warning.

### New input commands

| Command | Params | Behavior |
|---|---|---|
| `send_key` | `key` (string e.g. `"Right"`), `pressed` (bool, default true), `shift`/`ctrl`/`alt` (bool), `echo` (bool) | `OS.find_keycode_from_string()` → `InputEventKey` → `Input.parse_input_event()` |
| `send_mouse_move` | `x`, `y` (viewport coords) | `InputEventMouseMotion` → `Input.parse_input_event()` |
| `send_mouse_button` | `x`, `y`, `button` (1=left 2=right 3=middle), `pressed` | `InputEventMouseButton` → `Input.parse_input_event()` |
| `click` | `x`, `y`, `button` (default 1) | Convenience: mouse_move → button_down → button_up, single response |
| `drag` | `from_x`, `from_y`, `to_x`, `to_y`, `button` (default 1), `steps` (default 5) | Move to start → press → interpolated motion steps → release |

### New inspection commands

| Command | Params | Behavior |
|---|---|---|
| `get_node` | `node_path`, `properties` (optional string array) | `MCPTree.get_node_data()` for the node + extra props |
| `find_nodes` | `name` (optional), `type` (optional) | Walks current scene, returns `[{path, type}, ...]` for matches. `name` is an exact match on `node.name`; `type` is an exact match on `node.get_class()` (e.g. `"CharacterBody2D"`). Both params optional; omitting one skips that filter. |

### Await state machine

New enum:
```gdscript
enum _AwaitState { NONE, FRAMES, NODE_PROP, SIGNAL }
```

While state is not `NONE`, `_process` calls `_tick_await()` instead of reading new commands (same single-command-at-a-time model as today).

| Command | Params | Behavior |
|---|---|---|
| `await_frames` | `n` | Decrements counter each `_process` tick; responds when zero |
| `await_node_property` | `node_path`, `property`, `value`, `timeout` (seconds, default 5) | Polls property each frame; responds on match or timeout |
| `await_signal` | `node_path`, `signal`, `timeout` (seconds, default 5) | Introspects arg count via `get_signal_list()`, connects 0/1/2-arg callback accordingly; responds on fire or timeout |

**`await_signal` arity handling:** Godot's `connect()` requires callback arity to match signal parameter count. We introspect via `get_signal_list()` and route to one of three pre-defined helper methods (`_on_signal_0`, `_on_signal_1`, `_on_signal_2`) each of which discards args and calls `_finish_signal_await()`. Signals with 3+ args get best-effort 2-arg connection.

### `call_node_method`

Params: `node_path`, `method`, `args` (array, optional, default `[]`).

Implementation: `node.callv(method, args)`. Response: `{"ok": true, "result": <return value>}` or error. If the return value is not JSON-serializable (e.g. a Vector2 or Node reference), it is converted to string via `str()` before inclusion in the response. No allowlist — the `--mcp` flag is the gate.

### Enhanced `screenshot`

Response gains:
- `viewport_size`: `[width, height]`
- `scene`: current scene file path string (`get_tree().current_scene.scene_file_path`)
- `frame`: `Engine.get_process_frames()`

### `get_ui` update

Replace local `_get_ui_tree` call with `MCPTree.get_ui_tree(root, depth)`. Remove local `_get_ui_tree` function.

---

## Section 3: `plugin.gd` changes

No input commands or await primitives — those require a live game loop.

### Shared tree serialization

Preload `mcp_tree.gd`. Replace `_cmd_get_ui` to call `MCPTree.get_ui_tree(_scene_root, depth)`. Remove local `_get_ui_tree`.

### New inspection commands

| Command | Params | Behavior |
|---|---|---|
| `get_node` | `node_path`, `properties` (optional string array) | `_scene_root.get_node_or_null(node_path)` → `MCPTree.get_node_data()` |
| `find_nodes` | `name` (optional), `type` (optional) | Walks `_scene_root`, returns `[{path, type}, ...]` |

### Enhanced `screenshot`

Same metadata additions: `viewport_size`, `scene` (the loaded scene path), `frame` (hardcoded 0 — editor has no process frame counter).

---

## Section 4: `server.py` changes

### New MCP tools

All session-only (require active session from `start_ui_session`):

| Tool | Signature |
|---|---|
| `send_key` | `key: str, pressed: bool = True, shift: bool = False, ctrl: bool = False, alt: bool = False, echo: bool = False` |
| `send_mouse` | `x: float, y: float` |
| `click` | `x: float, y: float, button: int = 1` |
| `drag` | `from_x: float, from_y: float, to_x: float, to_y: float, button: int = 1, steps: int = 5` |
| `get_node` | `node_path: str, properties: list[str] \| None = None` |
| `find_nodes` | `name: str = "", type: str = ""` |
| `await_frames` | `n: int` |
| `await_node_property` | `node_path: str, property: str, value: Any, timeout: float = 5.0` |
| `await_signal` | `node_path: str, signal: str, timeout: float = 5.0` |
| `call_node_method` | `node_path: str, method: str, args: list \| None = None` |

### Socket timeout for `await_*` tools

`_transact()` currently uses `CONNECT_TIMEOUT = 2.0` on the session socket. `await_*` calls block until Godot responds. `send_session_command` gets an optional `socket_timeout` parameter (default `None` → use existing timeout). Each `await_*` tool passes `timeout + 2.0` seconds as the socket timeout to avoid a Python-side timeout racing the Godot-side one.

### Docstring updates

- `navigate_ui`: note that `send_key`, `click`, `drag` are now preferred for input
- `get_live_ui`: note that `get_node` and `find_nodes` exist for targeted single-node inspection

### `scaffold_tests` and `check_scaffold` updates

Add `mcp_tree.gd` to the list of addon files copied by `scaffold_tests` alongside `plugin.gd` and `remote_control.gd`. Add the same file to the presence check in `check_scaffold`.

---

## What is not in scope

- OS-level screenshot automation (AppleScript, CoreGraphics)
- Project-specific persistence helpers
- Port collision recovery (existing manual cleanup process unchanged)
- Input drag with acceleration curves (linear interpolation only)
