# Pause & Time Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pause/time-scale control and step-frame advancement to the godot-mcp runtime so verifiers can freeze the game, inspect state, and advance exactly N frames before re-pausing.

**Architecture:** Three new commands in `remote_control.gd` (`set_tree_paused`, `get_tree_paused`, `set_engine_time_scale`) plus a `step_frames` command that uses a new `STEP_FRAMES` await state to unpause for N frames then re-pause. `RemoteControl` gets `process_mode = PROCESS_MODE_ALWAYS` so it can receive commands while the tree is paused. Matching MCP tools go in `server.py` with tests in `tests/test_ui_verification.py`.

**Tech Stack:** GDScript 4 / Godot 4, Python 3.12, pytest, FastMCP

---

## File Map

| File | Change |
|---|---|
| `scaffold/addons/godot_mcp/remote_control.gd` | Add `PROCESS_MODE_ALWAYS` in `_ready`; add `_cmd_set_tree_paused`, `_cmd_get_tree_paused`, `_cmd_set_engine_time_scale`; add `STEP_FRAMES` await state + `_cmd_step_frames` + `_await_step_paused` flag |
| `server.py` | Add `set_tree_paused`, `get_tree_paused`, `set_engine_time_scale`, `step_frames` MCP tools |
| `tests/test_ui_verification.py` | Add tests for all four new tools |

---

## Task 1: Fix process_mode + add pause/time-scale commands in `remote_control.gd`

**Files:**
- Modify: `scaffold/addons/godot_mcp/remote_control.gd`

Without `PROCESS_MODE_ALWAYS`, RemoteControl's `_process` does not run while the tree is paused — commands sent during pause are never read. This fix is required before pause control is useful.

- [ ] **Step 1: Add `process_mode` assignment in `_ready`**

In `remote_control.gd`, inside `_ready()`, after the `if "--mcp" not in args: return` block and before `_server = TCPServer.new()`, add:

```gdscript
func _ready() -> void:
    var args := OS.get_cmdline_user_args()
    if "--mcp" not in args:
        return

    process_mode = Node.PROCESS_MODE_ALWAYS   # ← add this line

    _server = TCPServer.new()
    # ... rest unchanged
```

- [ ] **Step 2: Add three new command handlers to `_handle_command`**

In the `match parsed.get("cmd", ""):` block of `_handle_command`, add after `"call_node_method":`:

```gdscript
            "set_tree_paused":
                _cmd_set_tree_paused(parsed)
            "get_tree_paused":
                _cmd_get_tree_paused()
            "set_engine_time_scale":
                _cmd_set_engine_time_scale(parsed)
```

- [ ] **Step 3: Implement the three command functions**

Add these three functions to the file (after `_cmd_call_node_method`):

```gdscript
func _cmd_set_tree_paused(params: Dictionary) -> void:
    var paused: bool = bool(params.get("paused", false))
    get_tree().paused = paused
    _respond({"ok": true, "paused": get_tree().paused})


func _cmd_get_tree_paused() -> void:
    _respond({"ok": true, "paused": get_tree().paused})


func _cmd_set_engine_time_scale(params: Dictionary) -> void:
    var scale: float = float(params.get("scale", 1.0))
    if scale < 0.0:
        _respond({"ok": false, "error": "scale must be >= 0.0"})
        return
    Engine.time_scale = scale
    _respond({"ok": true, "scale": Engine.time_scale})
```

- [ ] **Step 4: Commit**

```bash
git add scaffold/addons/godot_mcp/remote_control.gd
git commit -m "feat: add process_mode_always and pause/time-scale commands to RemoteControl"
```

---

## Task 2: Add `step_frames` command to `remote_control.gd`

**Files:**
- Modify: `scaffold/addons/godot_mcp/remote_control.gd`

`step_frames` temporarily unpauses the tree, counts N frames, then re-pauses. A `_await_step_paused` flag tracks whether to re-pause when done.

- [ ] **Step 1: Extend the `_AwaitState` enum with `STEP_FRAMES`**

Change:
```gdscript
enum _AwaitState { NONE, FRAMES, NODE_PROP, SIGNAL }
```
to:
```gdscript
enum _AwaitState { NONE, FRAMES, STEP_FRAMES, NODE_PROP, SIGNAL }
```

- [ ] **Step 2: Add `_await_step_paused` instance variable**

After `var _await_deadline_ms := 0`, add:
```gdscript
var _await_step_paused := false
```

- [ ] **Step 3: Add `step_frames` to `_handle_command`**

In the `match` block after `"await_frames":`, add:
```gdscript
            "step_frames":
                _cmd_step_frames(parsed)
```

- [ ] **Step 4: Implement `_cmd_step_frames`**

Add after `_cmd_await_frames`:

```gdscript
func _cmd_step_frames(params: Dictionary) -> void:
    var n := int(params.get("n", 1))
    if n <= 0:
        _respond({"ok": true})
        return
    _await_step_paused = get_tree().paused
    get_tree().paused = false
    _await_frames_left = n
    _await_state = _AwaitState.STEP_FRAMES
```

- [ ] **Step 5: Handle `STEP_FRAMES` in `_tick_await`**

In `_tick_await`, inside the `match _await_state:` block, add after the `_AwaitState.FRAMES:` case:

```gdscript
        _AwaitState.STEP_FRAMES:
            _await_frames_left -= 1
            if _await_frames_left <= 0:
                _await_state = _AwaitState.NONE
                get_tree().paused = _await_step_paused
                _respond({"ok": true})
```

- [ ] **Step 6: Commit**

```bash
git add scaffold/addons/godot_mcp/remote_control.gd
git commit -m "feat: add step_frames command with re-pause support to RemoteControl"
```

---

## Task 3: Add four MCP tools to `server.py`

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Write the failing tests first**

Add to `tests/test_ui_verification.py`:

```python
def test_set_tree_paused_no_session(monkeypatch, tmp_path):
    """set_tree_paused returns error when no session is active."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge._session_conn = None
    result = srv.set_tree_paused(True)
    assert "no active UI session" in result


def test_set_tree_paused_sends_command(monkeypatch, tmp_path):
    """set_tree_paused sends set_tree_paused command with paused param."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(
        return_value={"ok": True, "paused": True}
    )
    srv._bridge._session_conn = MagicMock()
    result = srv.set_tree_paused(True)
    srv._bridge.send_session_command.assert_called_once_with("set_tree_paused", paused=True)
    assert result == "ok"


def test_get_tree_paused_no_session(monkeypatch, tmp_path):
    """get_tree_paused returns error when no session is active."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge._session_conn = None
    result = srv.get_tree_paused()
    assert "no active UI session" in result


def test_get_tree_paused_returns_state(monkeypatch, tmp_path):
    """get_tree_paused returns JSON with paused field."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(
        return_value={"ok": True, "paused": False}
    )
    srv._bridge._session_conn = MagicMock()
    result = srv.get_tree_paused()
    assert json.loads(result) == {"paused": False}


def test_set_engine_time_scale_no_session(monkeypatch, tmp_path):
    """set_engine_time_scale returns error when no session is active."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge._session_conn = None
    result = srv.set_engine_time_scale(0.5)
    assert "no active UI session" in result


def test_set_engine_time_scale_sends_command(monkeypatch, tmp_path):
    """set_engine_time_scale sends set_engine_time_scale command with scale param."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(
        return_value={"ok": True, "scale": 0.5}
    )
    srv._bridge._session_conn = MagicMock()
    result = srv.set_engine_time_scale(0.5)
    srv._bridge.send_session_command.assert_called_once_with("set_engine_time_scale", scale=0.5)
    assert result == "ok"


def test_step_frames_no_session(monkeypatch, tmp_path):
    """step_frames returns error when no session is active."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge._session_conn = None
    result = srv.step_frames(3)
    assert "no active UI session" in result


def test_step_frames_sends_correct_command(monkeypatch, tmp_path):
    """step_frames sends step_frames command with n and socket_timeout."""
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/bin/false")
    importlib.reload(srv)

    srv._bridge.send_session_command = MagicMock(return_value={"ok": True})
    srv._bridge._session_conn = MagicMock()
    srv.step_frames(10)
    call_kwargs = srv._bridge.send_session_command.call_args.kwargs
    assert call_kwargs.get("n") == 10
    assert "socket_timeout" in call_kwargs
    assert call_kwargs["socket_timeout"] >= 10.0
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
cd /Users/kognido/game-dev/godot-mcp && .venv/bin/pytest tests/test_ui_verification.py -k "set_tree_paused or get_tree_paused or set_engine_time_scale or step_frames" -v 2>&1 | tail -20
```

Expected: ERRORS — `AttributeError: module 'server' has no attribute 'set_tree_paused'` (and similarly for the other three).

- [ ] **Step 3: Add the four MCP tools to `server.py`**

Add after the `call_node_method` tool definition (before `if __name__ == "__main__":`):

```python
@mcp.tool()
def set_tree_paused(paused: bool) -> str:
    """Pause or unpause the SceneTree in the active game session.
    paused=True freezes all nodes that do not have process_mode=PROCESS_MODE_ALWAYS.
    Use step_frames to advance exactly N frames while paused.
    Use set_engine_time_scale(0.0) as an alternative that keeps physics running.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command("set_tree_paused", paused=paused)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"


@mcp.tool()
def get_tree_paused() -> str:
    """Return the current SceneTree pause state as JSON: {"paused": bool}.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command("get_tree_paused")
    if not result["ok"]:
        return f"Error: {result['error']}"
    return json.dumps({"paused": result["paused"]})


@mcp.tool()
def set_engine_time_scale(scale: float) -> str:
    """Set Engine.time_scale in the active game session.
    scale=1.0 is normal speed. scale=0.0 stops _process and _physics_process
    (unlike tree pause, which respects process_mode). scale must be >= 0.0.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command("set_engine_time_scale", scale=scale)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"


@mcp.tool()
def step_frames(n: int) -> str:
    """Advance exactly n game frames, then re-pause to the previous pause state.
    If the tree was paused before calling this, it unpauses for n frames and re-pauses.
    If the tree was running, it just waits for n frames (equivalent to await_frames).
    Use after set_tree_paused(True) to advance one step at a time during inspection.
    Blocks until Godot confirms n frames have elapsed.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    socket_timeout = max(n / 60.0 + 5.0, 10.0)
    result = _bridge.send_session_command(
        "step_frames", socket_timeout=socket_timeout, n=n
    )
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /Users/kognido/game-dev/godot-mcp && .venv/bin/pytest tests/test_ui_verification.py -k "set_tree_paused or get_tree_paused or set_engine_time_scale or step_frames" -v 2>&1 | tail -30
```

Expected: all 10 new tests PASS.

- [ ] **Step 5: Run full test suite to confirm no regressions**

```bash
cd /Users/kognido/game-dev/godot-mcp && .venv/bin/pytest tests/ -v 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_ui_verification.py
git commit -m "feat: add set_tree_paused, get_tree_paused, set_engine_time_scale, step_frames MCP tools"
```

---

## Self-Review

**Spec coverage:**

| Requirement | Task |
|---|---|
| `set_tree_paused(paused: bool)` | Task 1 (GDScript) + Task 3 (server.py) |
| `get_tree_paused()` | Task 1 (GDScript) + Task 3 (server.py) |
| `set_engine_time_scale(scale: float)` | Task 1 (GDScript) + Task 3 (server.py) |
| `step_frames(n)` — advance while paused | Task 2 (GDScript) + Task 3 (server.py) |
| `process_mode = PROCESS_MODE_ALWAYS` | Task 1 |

**Not in this plan (separate concerns):**
- `snapshot_nodes` batch inspection — not yet specced
- Scene bootstrap hooks — not yet specced
- Screenshot default path — current behavior (absolute via `globalize_path`) is already correct

**Placeholder scan:** No TBD/TODO/placeholder patterns found.

**Type consistency:**
- `_await_step_paused: bool` used in `_cmd_step_frames` and `_tick_await` — consistent.
- `_AwaitState.STEP_FRAMES` added to enum and referenced in both `_cmd_step_frames` and `_tick_await` — consistent.
- `socket_timeout` in `step_frames` tool uses same pattern as `await_frames` — consistent.
