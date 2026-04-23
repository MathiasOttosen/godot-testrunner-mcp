# MCP Server — FastMCP + Godot
*Python · FastMCP 3.x · stdio transport · Claude Code*

---

## What This Is

A local MCP server written in Python with FastMCP that exposes custom tools to Claude Code via stdio transport. The server runs as a subprocess — Claude Code spawns it, communicates over stdin/stdout, and calls its tools like any other MCP tool.

The goal is to give Claude Code structured access to the Godot project: read debug output, query project state, run the game, and receive structured error messages — without Claude Code having to parse raw file output or guess at GDScript API behaviour.

---

## Project Structure

```
mcp/
├── server.py          # FastMCP server — all tools defined here
├── requirements.txt   # fastmcp and any other deps
├── .venv/             # virtual environment (not committed)
└── README.md          # setup steps for yourself later
```

---

## Environment Setup

```bash
# From the mcp/ directory
python3 -m venv .venv
source .venv/bin/activate
pip install fastmcp
```

Use the venv Python as the command in the Claude Code config (see Registration below). This avoids system Python conflicts.

---

## Server Skeleton

```python
from fastmcp import FastMCP

mcp = FastMCP("the-pattern")

@mcp.tool
def tool_name(param: str) -> str:
    """Docstring is what Claude Code reads to decide when to use this tool.
    Be specific. Bad docstrings = tool never gets called."""
    return result

if __name__ == "__main__":
    mcp.run()  # stdio transport by default
```

**Rules:**
- `mcp.run()` with no arguments = stdio. Do not pass `transport="http"` for local use.
- Every tool needs a docstring. The docstring is the tool's description in the MCP schema — Claude Code reads it to decide when and how to call the tool.
- Type hints on all parameters. FastMCP generates the JSON schema from them automatically. Missing type hints = broken schema.
- `@mcp.tool` (no parentheses) for simple tools. `@mcp.tool()` (with parentheses) also works — both are valid in FastMCP 3.x.
- Return plain Python types: `str`, `int`, `dict`, `list`. FastMCP handles serialisation.
- Async tools are supported: `async def tool_name(...) -> str:`. Use for subprocess calls or anything that blocks.

---

## Critical: Logging Must Go to stderr

**Never write to stdout.** The stdio transport uses stdout exclusively for JSON-RPC protocol messages. Any `print()` or logging to stdout corrupts the message stream and disconnects the client silently.

```python
import sys
import logging

# Correct: log to stderr
logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)
log = logging.getLogger(__name__)

@mcp.tool
def my_tool() -> str:
    log.debug("this goes to stderr, safe")   # OK
    print("this goes to stdout, CORRUPTS STREAM")  # NEVER DO THIS
    return "result"
```

---

## Registering with Claude Code

**Option A — fastmcp CLI (recommended):**
```bash
fastmcp install claude-code mcp/server.py
```
This runs `claude mcp add` automatically. If your server object is not named `mcp`, use `server.py:my_object`.

**Option B — manual:**
```bash
claude mcp add the-pattern \
  /Users/kognido/game_dev/the_pattern/mcp/.venv/bin/python \
  /Users/kognido/game_dev/the_pattern/mcp/server.py
```

**Verify registration:**
```bash
claude mcp list
```

**Remove and re-add** if you change the server path or venv:
```bash
claude mcp remove the-pattern
claude mcp add the-pattern ...
```

Claude Code must be restarted after any registration change.

---

## Debugging Before Connecting to Claude Code

Use the MCP Inspector to test tools before wiring them in:

```bash
npx @modelcontextprotocol/inspector \
  /Users/kognido/game_dev/the_pattern/mcp/.venv/bin/python \
  /Users/kognido/game_dev/the_pattern/mcp/server.py
```

This opens a browser UI. You can see the tool list, call tools with test inputs, and read the raw JSON-RPC messages. Use this to confirm tools appear correctly before touching Claude Code config.

If a tool doesn't appear in the Inspector: check the docstring exists, check type hints are present, check for import errors by running `python server.py` directly (it will just sit there — that's correct, press Ctrl+C to stop).

---

## Godot Integration Pattern

The cleanest way to give the MCP server access to Godot is via subprocess calls to the Godot CLI and stdout capture. No plugin or GDScript addon required for basic operations.

```python
import subprocess
import asyncio

GODOT_PATH = "/Applications/Godot.app/Contents/MacOS/Godot"
PROJECT_PATH = "/Users/kognido/game_dev/the_pattern"

@mcp.tool
async def get_debug_output(timeout: int = 10) -> str:
    """Run the Godot project in headless mode and return stdout/stderr output.
    Use this to check for GDScript errors, print output, or verify a change works.
    timeout is in seconds."""
    result = await asyncio.create_subprocess_exec(
        GODOT_PATH, "--headless", "--path", PROJECT_PATH,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        result.kill()
        return "Timed out — game may be running normally (no quit call)"
    return (stdout + stderr).decode("utf-8", errors="replace")

@mcp.tool
def get_godot_version() -> str:
    """Return the installed Godot version string."""
    result = subprocess.run(
        [GODOT_PATH, "--version"],
        capture_output=True, text=True, timeout=5
    )
    return result.stdout.strip() or result.stderr.strip()
```

**For reading project files** (scenes, scripts, configs) — just read them directly from the filesystem. No subprocess needed:

```python
from pathlib import Path

@mcp.tool
def read_script(relative_path: str) -> str:
    """Read a GDScript file from the project. relative_path is from the project root,
    e.g. 'scripts/sigil_system.gd'. Returns the file contents as a string."""
    full = Path(PROJECT_PATH) / relative_path
    if not full.exists():
        return f"File not found: {relative_path}"
    return full.read_text(encoding="utf-8")
```

**Path safety** — if any tool accepts a path argument, validate it stays inside the project root:

```python
def safe_path(relative: str) -> Path | None:
    """Returns resolved path if inside project root, None if escape attempt."""
    root = Path(PROJECT_PATH).resolve()
    target = (root / relative).resolve()
    return target if target.is_relative_to(root) else None
```

---

## Tool Design Guidelines

**Write tools for Claude Code's decision-making, not for human use.**

Good tool: `get_debug_output()` — returns structured, parseable output that Claude Code can act on.
Bad tool: `open_godot_editor()` — opens a GUI window, returns nothing useful to an agent.

**Name tools as verbs:** `get_`, `run_`, `read_`, `list_`, `check_`. The name plus docstring is the entire API contract.

**Return errors as strings, not exceptions:**
```python
@mcp.tool
def read_script(relative_path: str) -> str:
    path = safe_path(relative_path)
    if path is None:
        return "Error: path escapes project root"
    if not path.exists():
        return f"Error: file not found — {relative_path}"
    return path.read_text(encoding="utf-8")
```
Raising exceptions crashes the tool call. Returning an error string lets Claude Code read the problem and decide what to do next.

**Keep tools focused.** One tool, one job. `get_scene_tree()` and `get_script_errors()` are two tools, not one.

---

## Useful Starting Tools for This Project

Suggested initial toolset — implement in order of usefulness:

| Tool | What it does |
|---|---|
| `get_debug_output(timeout)` | Run headless, capture stdout/stderr |
| `read_script(path)` | Read a .gd file from the project |
| `list_scripts()` | List all .gd files under scripts/ |
| `get_godot_version()` | Confirm Godot binary is reachable |
| `read_scene(path)` | Read a .tscn file as text |
| `list_scenes()` | List all .tscn files in the project |
| `get_project_info()` | Parse and return project.godot contents |
| `check_script_errors(path)` | Run `--check-only` on a specific script |

---

## Dependencies

Keep `requirements.txt` minimal:

```
fastmcp
```

Add others only when a tool actually needs them. Install into the venv:
```bash
source mcp/.venv/bin/activate
pip install -r mcp/requirements.txt
```

If you add a dependency, update `requirements.txt` and document why in a comment next to the tool that needs it.

---

## Ignored Paths

The `mcp/` directory is implementation infrastructure. It should not be loaded as game design context.

Add to `.claudeignore`:
```
mcp/.venv/
```

The server source (`mcp/server.py`) is fine to read — Claude Code may need to understand the tool surface when implementing features that use MCP tools.

---

## Common Failures

**Tools not appearing in Claude Code:**
1. Check `claude mcp list` — is the server registered?
2. Run `python server.py` directly — any import error?
3. Run the MCP Inspector — do tools appear there?
4. Restart Claude Code after any registration change

**Silent disconnect / no tools available after they worked before:**
Something is writing to stdout. Add `import sys; print("test", file=sys.stderr)` and remove all `print()` calls.

**Godot binary not found:**
Set `GODOT_PATH` explicitly. On macOS, the binary inside the .app is at `/Applications/Godot.app/Contents/MacOS/Godot`. Confirm with `which godot` or locate the .app.

**Timeout on `get_debug_output`:**
The game is running normally and not quitting. Either add a `quit()` call to a test autoload, or increase the timeout. The tool should not hang Claude Code — always set a timeout on subprocess calls.
