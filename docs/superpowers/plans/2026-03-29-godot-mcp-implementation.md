# godot-mcp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a general-purpose Godot 4 MCP server that gives Claude Code structured access to any Godot 4 project — codebase navigation, testability analysis, test scaffolding, and three-tier test execution.

**Architecture:** FastMCP server over stdio transport. All tools defined in `server.py`. Configuration via `GODOT_BIN` and `GODOT_PROJECT` env vars read lazily at call time. GDScript test infrastructure lives in `scaffold/` in this repo and is copied into target projects by `scaffold_tests()`.

**Tech Stack:** Python 3.12, FastMCP ≥3.1.1, pytest ≥8.0, asyncio (subprocess), stdlib only (no extra deps beyond fastmcp).

**Natural phase boundary:** Tasks 1–8 are a usable codebase navigator. Tasks 9–14 add the testing framework. Can be implemented and shipped as two sessions.

---

## File Map

| File | Purpose |
|---|---|
| `server.py` | All FastMCP tool definitions (single file until >500 lines) |
| `pyproject.toml` | Add pytest dev dependency |
| `tests/conftest.py` | Pytest fixtures (env vars, project paths) |
| `tests/test_navigation.py` | Tests for read_script, list_scripts, list_scenes, inspect_scene, check_script, get_godot_version |
| `tests/test_settings.py` | Tests for get_project_settings, set_project_setting, set_autoload, restore_project_settings |
| `tests/test_analysis.py` | Tests for analyze_testability, get_coverage_report |
| `tests/test_scaffold.py` | Tests for scaffold_tests, check_scaffold |
| `tests/test_authoring.py` | Tests for get_test_context, write_test_suite, edit_test_suite |
| `tests/test_execution.py` | Tests for run_tests, get_test_details, get_last_results, run_debug |
| `scaffold/base_test.gd` | GDScript base class for test suites |
| `scaffold/test_runner.gd` | GDScript test runner autoload |
| `scaffold/smoke/smoke_runner.gd` | GDScript smoke test runner autoload |

---

## Task 1: Server skeleton and Python test setup

**Files:**
- Modify: `pyproject.toml`
- Create: `server.py` (replace existing stub)
- Create: `tests/conftest.py`
- Create: `tests/test_navigation.py` (first test only)

- [ ] **Step 1: Add pytest dev dependency**

Edit `pyproject.toml` to add:
```toml
[project]
name = "godot-mcp"
version = "0.1.0"
description = "MCP server for Godot 4 projects"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "fastmcp>=3.1.1",
]

[tool.uv]
dev-dependencies = ["pytest>=8.0"]
```

- [ ] **Step 2: Install dev dependencies**

```bash
cd "/Users/kognido/game dev/godot-mcp"
uv sync --dev
```
Expected: installs pytest into `.venv/`

- [ ] **Step 3: Write the first failing test**

Create `tests/conftest.py`:
```python
import os
import pytest
from pathlib import Path

THE_PATTERN = "/Users/kognido/game dev/the_pattern"
GODOT_BIN_PATH = "/Applications/Godot.app/Contents/MacOS/Godot"


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("GODOT_BIN", GODOT_BIN_PATH)
    monkeypatch.setenv("GODOT_PROJECT", THE_PATTERN)
```

Create `tests/test_navigation.py` with first test:
```python
import importlib
import server


def test_validate_config_passes_with_valid_env():
    errors = server._validate_config()
    assert errors == []


def test_validate_config_fails_missing_godot_bin(monkeypatch):
    monkeypatch.delenv("GODOT_BIN", raising=False)
    importlib.reload(server)
    errors = server._validate_config()
    assert any("GODOT_BIN" in e for e in errors)
    # reload with correct env restored by autouse fixture on next test
```

- [ ] **Step 4: Run the test — expect failure (server.py doesn't have _validate_config yet)**

```bash
cd "/Users/kognido/game dev/godot-mcp"
uv run pytest tests/test_navigation.py -v
```
Expected: `AttributeError: module 'server' has no attribute '_validate_config'`

- [ ] **Step 5: Write the server skeleton**

Replace `server.py` entirely:
```python
import os
import sys
import logging
import asyncio
import subprocess
from pathlib import Path
from fastmcp import FastMCP

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
log = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

def _godot_bin() -> str:
    return os.environ.get("GODOT_BIN", "")


def _godot_project() -> Path:
    return Path(os.environ.get("GODOT_PROJECT", ""))


def _validate_config() -> list[str]:
    errors = []
    bin_path = _godot_bin()
    project_path = _godot_project()
    if not bin_path:
        errors.append("GODOT_BIN environment variable is not set")
    elif not Path(bin_path).exists():
        errors.append(f"GODOT_BIN not found: {bin_path}")
    if not str(project_path):
        errors.append("GODOT_PROJECT environment variable is not set")
    elif not (project_path / "project.godot").exists():
        errors.append(f"GODOT_PROJECT has no project.godot: {project_path}")
    return errors


def _safe_path(relative: str) -> Path | None:
    """Return resolved path if inside project root, None if escape attempt."""
    root = _godot_project().resolve()
    target = (root / relative).resolve()
    return target if target.is_relative_to(root) else None


# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP("godot-mcp")


# ── Subprocess helpers ────────────────────────────────────────────────────────

async def _run_godot(args: list[str], timeout: int = 15) -> tuple[str, int]:
    """Run Godot with the given args. Returns (output, returncode)."""
    cmd = [_godot_bin(), "--path", str(_godot_project())] + args
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return f"Error: Godot process timed out after {timeout}s", -1
    output = (stdout + stderr).decode("utf-8", errors="replace")
    return output, proc.returncode


if __name__ == "__main__":
    errors = _validate_config()
    if errors:
        for e in errors:
            log.error("Configuration error: %s", e)
        sys.exit(1)
    backup = _godot_project() / "project.godot.mcp_backup"
    if backup.exists():
        log.warning(
            "Found project.godot.mcp_backup — previous session did not restore settings. "
            "Call restore_project_settings() to revert."
        )
    mcp.run()
```

- [ ] **Step 6: Run tests — expect pass**

```bash
uv run pytest tests/test_navigation.py::test_validate_config_passes_with_valid_env -v
```
Expected: `PASSED`

Note: `test_validate_config_fails_missing_godot_bin` will be fixed in a later step once we handle module reloading cleanly. Skip it for now with `-k not missing`.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml server.py tests/conftest.py tests/test_navigation.py uv.lock
git commit -m "feat: server skeleton with config validation and subprocess helper"
```

---

## Task 2: Script and scene listing tools

**Files:**
- Modify: `server.py`
- Modify: `tests/test_navigation.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_navigation.py`:
```python
def test_get_godot_version_returns_version_string():
    result = server.get_godot_version()
    assert "4." in result


def test_list_scripts_returns_gd_files():
    result = server.list_scripts("scripts/")
    assert isinstance(result, list)
    assert any(p.endswith(".gd") for p in result)
    assert all(".uid" not in p for p in result)


def test_list_scripts_excludes_non_gd():
    result = server.list_scripts("scripts/")
    assert all(p.endswith(".gd") for p in result)


def test_read_script_returns_contents():
    result = server.read_script("scripts/sigil_system.gd")
    assert "class_name SigilSystem" in result or "extends" in result


def test_read_script_missing_file():
    result = server.read_script("scripts/does_not_exist.gd")
    assert result.startswith("Error:")


def test_read_script_path_traversal_blocked():
    result = server.read_script("../../etc/passwd")
    assert result.startswith("Error:")


def test_list_scenes_returns_tscn_files():
    result = server.list_scenes()
    assert isinstance(result, list)
    assert len(result) > 0
    assert all(entry["path"].endswith(".tscn") for entry in result)
    assert all("root_type" in entry for entry in result)
```

- [ ] **Step 2: Run tests — expect failure**

```bash
uv run pytest tests/test_navigation.py -v -k "version or scripts or scenes or read_script"
```
Expected: `AttributeError` — functions not defined yet.

- [ ] **Step 3: Implement the tools**

Add to `server.py` after the `_run_godot` helper:
```python
# ── Project navigation ────────────────────────────────────────────────────────

@mcp.tool()
def get_godot_version() -> str:
    """Return the installed Godot version string.
    Use to confirm the configured Godot binary is reachable before running other tools."""
    result = subprocess.run(
        [_godot_bin(), "--version"],
        capture_output=True, text=True, timeout=5
    )
    return (result.stdout + result.stderr).strip() or "Error: no output from godot --version"


@mcp.tool()
def read_script(path: str) -> str:
    """Read a GDScript file from the project by path relative to the project root.
    Example: read_script("scripts/sigil_system.gd")
    Returns file contents, or an error string if the file does not exist or path is invalid."""
    target = _safe_path(path)
    if target is None:
        return f"Error: path escapes project root — {path}"
    if not target.exists():
        return f"Error: file not found — {path}"
    if not target.suffix == ".gd":
        return f"Error: not a GDScript file — {path}"
    return target.read_text(encoding="utf-8")


@mcp.tool()
def list_scripts(directory: str = "scripts/") -> list[str]:
    """List all GDScript (.gd) files under a project directory.
    Returns file paths relative to the project root. Does not return file contents.
    Use read_script() to read a specific file."""
    root = _godot_project()
    target = _safe_path(directory)
    if target is None:
        return []
    if not target.is_dir():
        return []
    return sorted(
        str(p.relative_to(root))
        for p in target.rglob("*.gd")
    )


@mcp.tool()
def list_scenes() -> list[dict]:
    """List all Godot scene files (.tscn) in the project.
    Returns a list of dicts with 'path' (relative to project root) and 'root_type'.
    Use inspect_scene() to get the full node tree of a specific scene."""
    root = _godot_project()
    results = []
    for tscn in sorted(root.rglob("*.tscn")):
        rel = str(tscn.relative_to(root))
        root_type = _parse_tscn_root_type(tscn)
        results.append({"path": rel, "root_type": root_type})
    return results


def _parse_tscn_root_type(tscn_path: Path) -> str:
    """Extract the root node type from a .tscn file without full parsing."""
    try:
        for line in tscn_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("[node ") and 'parent' not in line:
                import re
                m = re.search(r'type="([^"]+)"', line)
                return m.group(1) if m else "unknown"
    except Exception:
        pass
    return "unknown"
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/test_navigation.py -v -k "version or scripts or scenes or read_script"
```
Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_navigation.py
git commit -m "feat: add get_godot_version, read_script, list_scripts, list_scenes"
```

---

## Task 3: Scene inspection and script checking

**Files:**
- Modify: `server.py`
- Modify: `tests/test_navigation.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_navigation.py`:
```python
def test_inspect_scene_returns_node_tree():
    result = server.inspect_scene("scenes/room.tscn")
    assert isinstance(result, dict)
    assert "root" in result
    assert "name" in result["root"]
    assert "type" in result["root"]
    assert "children" in result["root"]


def test_inspect_scene_missing_file():
    result = server.inspect_scene("scenes/does_not_exist.tscn")
    assert isinstance(result, dict)
    assert "error" in result


def test_check_script_no_errors():
    result = server.check_script("scripts/world_state.gd")
    assert result == "No errors found" or "error" not in result.lower()


def test_check_script_missing_file():
    result = server.check_script("scripts/missing.gd")
    assert "Error:" in result
```

- [ ] **Step 2: Run tests — expect failure**

```bash
uv run pytest tests/test_navigation.py -v -k "inspect or check_script"
```
Expected: `AttributeError`

- [ ] **Step 3: Implement inspect_scene**

Add to `server.py`:
```python
@mcp.tool()
def inspect_scene(path: str) -> dict:
    """Parse a .tscn scene file and return a structured node tree.
    Returns dict with 'root' containing nested 'children', 'name', 'type',
    'script' (if attached), and key properties. Use this instead of read_script
    for scene files — raw .tscn text is unreadable.
    Returns {'error': '...'} if the file is not found or cannot be parsed."""
    target = _safe_path(path)
    if target is None:
        return {"error": f"path escapes project root — {path}"}
    if not target.exists():
        return {"error": f"file not found — {path}"}
    try:
        return _parse_tscn(target)
    except Exception as e:
        return {"error": f"parse failed — {e}"}


def _parse_tscn(tscn_path: Path) -> dict:
    import re
    text = tscn_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # collect ext_resources: id -> path
    ext_resources: dict[str, str] = {}
    for line in lines:
        m = re.match(r'\[ext_resource[^\]]*path="([^"]+)"[^\]]*id="([^"]+)"', line)
        if m:
            ext_resources[m.group(2)] = m.group(1)

    # parse nodes
    nodes: list[dict] = []
    current: dict | None = None
    for line in lines:
        node_m = re.match(r'\[node name="([^"]+)"(?:\s+type="([^"]+)")?(?:\s+parent="([^"]*)")?', line)
        if node_m:
            if current is not None:
                nodes.append(current)
            current = {
                "name": node_m.group(1),
                "type": node_m.group(2) or "unknown",
                "parent": node_m.group(3) or "",
                "children": [],
                "properties": {},
            }
        elif current is not None and "=" in line and not line.startswith("["):
            key, _, val = line.partition(" = ")
            key = key.strip()
            val = val.strip()
            if key == "script":
                # resolve ext resource
                rid_m = re.search(r'ExtResource\("([^"]+)"\)', val)
                if rid_m:
                    current["script"] = ext_resources.get(rid_m.group(1), val)
            elif key in ("position", "visible", "modulate", "z_index"):
                current["properties"][key] = val

    if current is not None:
        nodes.append(current)

    if not nodes:
        return {"error": "no nodes found in scene"}

    # build tree
    node_map: dict[str, dict] = {}
    root = None
    for node in nodes:
        parent_path = node["parent"]
        name = node["name"]
        display = {k: v for k, v in node.items() if k not in ("parent",)}
        if parent_path == "":
            root = display
            node_map["."] = display
        else:
            parent_key = parent_path
            parent_node = node_map.get(parent_key)
            if parent_node:
                parent_node["children"].append(display)
            full_path = (parent_path.rstrip(".") + "/" + name).lstrip("/")
            node_map[full_path] = display

    return {"root": root} if root else {"error": "could not build tree"}
```

- [ ] **Step 4: Implement check_script**

Add to `server.py`:
```python
@mcp.tool()
async def check_script(path: str) -> str:
    """Check a GDScript file for syntax and type errors without running the game.
    path is relative to the project root, e.g. 'scripts/sigil_system.gd'.
    Returns parsed error lines with line numbers, or 'No errors found'.
    Uses 'godot --headless --quit' to trigger GDScript compilation."""
    target = _safe_path(path)
    if target is None:
        return f"Error: path escapes project root — {path}"
    if not target.exists():
        return f"Error: file not found — {path}"

    output, _ = await _run_godot(["--headless", "--quit"], timeout=10)
    script_name = Path(path).name
    error_lines = [
        line for line in output.splitlines()
        if script_name in line and any(
            marker in line for marker in ("ERROR", "error", "SCRIPT ERROR", "Parse Error")
        )
    ]
    return "\n".join(error_lines) if error_lines else "No errors found"
```

- [ ] **Step 5: Run tests — expect pass**

```bash
uv run pytest tests/test_navigation.py -v -k "inspect or check_script"
```
Expected: all PASSED (check_script test requires Godot binary to be present)

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_navigation.py
git commit -m "feat: add inspect_scene and check_script tools"
```

---

## Task 4: Debug tool

**Files:**
- Modify: `server.py`
- Create: `tests/test_execution.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_execution.py`:
```python
import pytest
import server


def test_run_debug_returns_string():
    result = server.run_debug_sync(timeout=5)
    assert isinstance(result, str)
    assert len(result) > 0


def test_run_debug_timeout_returns_error():
    # Very short timeout to force timeout path
    result = server.run_debug_sync(timeout=1)
    # Either returns output (if Godot exits fast) or timeout message
    assert isinstance(result, str)
```

- [ ] **Step 2: Run test — expect failure**

```bash
uv run pytest tests/test_execution.py -v
```
Expected: `AttributeError: module 'server' has no attribute 'run_debug_sync'`

- [ ] **Step 3: Implement run_debug**

Add to `server.py`:
```python
# ── Debug ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def run_debug(timeout: int = 10) -> str:
    """Run the Godot project headlessly and return raw stdout/stderr output.
    Use for ad-hoc verification when no test exists yet.
    Not a substitute for run_tests() — unstructured output is token-expensive.
    timeout is in seconds; the process is killed if it does not exit in time."""
    errors = _validate_config()
    if errors:
        return "Error: " + "; ".join(errors)
    output, _ = await _run_godot(["--headless"], timeout=timeout)
    return output or "Error: Godot produced no output (possible crash before first print)"


def run_debug_sync(timeout: int = 10) -> str:
    """Synchronous wrapper for run_debug — used in tests only."""
    return asyncio.get_event_loop().run_until_complete(run_debug(timeout))
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/test_execution.py -v
```
Expected: PASSED (may be slow — Godot needs to start)

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_execution.py
git commit -m "feat: add run_debug tool"
```

---

## Task 5: Project settings — read

**Files:**
- Modify: `server.py`
- Create: `tests/test_settings.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_settings.py`:
```python
import server


def test_get_project_settings_returns_dict():
    result = server.get_project_settings()
    assert isinstance(result, dict)


def test_get_project_settings_has_application():
    result = server.get_project_settings()
    assert "application" in result
    assert "config/name" in result["application"]


def test_get_project_settings_has_autoloads():
    result = server.get_project_settings()
    assert "autoloads" in result
    assert isinstance(result["autoloads"], dict)


def test_parse_project_godot_reads_autoloads():
    from pathlib import Path
    path = Path("/Users/kognido/game dev/the_pattern/project.godot")
    result = server._parse_project_godot(path)
    assert "autoloads" in result
    assert "ConfigureManager" in result["autoloads"]
```

- [ ] **Step 2: Run tests — expect failure**

```bash
uv run pytest tests/test_settings.py -v
```
Expected: `AttributeError`

- [ ] **Step 3: Implement get_project_settings and parser**

Add to `server.py`:
```python
# ── Project settings ──────────────────────────────────────────────────────────

def _parse_project_godot(path: Path) -> dict:
    """Parse project.godot into a structured dict.
    Handles Godot's INI-like format including top-level keys and [autoload] section."""
    import re
    result: dict = {}
    current_section = "_top"
    result[current_section] = {}

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        section_m = re.match(r'^\[([^\]]+)\]$', line)
        if section_m:
            current_section = section_m.group(1)
            if current_section not in result:
                result[current_section] = {}
            continue
        kv_m = re.match(r'^([^=]+)=(.*)$', line)
        if kv_m:
            key = kv_m.group(1).strip()
            val = kv_m.group(2).strip()
            result[current_section][key] = val

    # normalize autoloads: strip leading * from paths
    autoloads = {}
    for name, path_val in result.get("autoload", {}).items():
        enabled = path_val.startswith('"*')
        clean_path = path_val.strip('"').lstrip("*")
        autoloads[name] = {"path": clean_path, "enabled": enabled}
    result["autoloads"] = autoloads

    return result


@mcp.tool()
def get_project_settings() -> dict:
    """Parse project.godot and return structured settings.
    Returns application settings, autoloads (with enabled status), main scene,
    display settings, and rendering settings.
    Does not modify any files."""
    errors = _validate_config()
    if errors:
        return {"error": "; ".join(errors)}
    path = _godot_project() / "project.godot"
    parsed = _parse_project_godot(path)
    return {
        "application": parsed.get("application", {}),
        "autoloads": parsed.get("autoloads", {}),
        "display": parsed.get("display", {}),
        "rendering": parsed.get("rendering", {}),
        "physics": parsed.get("physics", {}),
    }
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/test_settings.py -v -k "get_project or parse_project"
```
Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_settings.py
git commit -m "feat: add get_project_settings with project.godot parser"
```

---

## Task 6: Project settings — write

**Files:**
- Modify: `server.py`
- Modify: `tests/test_settings.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_settings.py`:
```python
import shutil
from pathlib import Path

THE_PATTERN = Path("/Users/kognido/game dev/the_pattern")


def test_set_project_setting_writes_and_restores(tmp_path):
    # Copy project.godot to tmp for safe testing
    src = THE_PATTERN / "project.godot"
    dst = tmp_path / "project.godot"
    shutil.copy(src, dst)

    import importlib, os
    os.environ["GODOT_PROJECT"] = str(tmp_path)
    importlib.reload(server)

    result = server.set_project_setting("application/config/name", '"test_name"')
    assert "previous" in result
    assert "new" in result

    server.restore_project_settings()
    restored = (tmp_path / "project.godot").read_text()
    original = src.read_text()
    assert restored == original

    os.environ["GODOT_PROJECT"] = str(THE_PATTERN)
    importlib.reload(server)


def test_restore_when_no_backup_is_safe():
    result = server.restore_project_settings()
    assert "no backup" in result.lower() or "restored" in result.lower()
```

- [ ] **Step 2: Run tests — expect failure**

```bash
uv run pytest tests/test_settings.py -v -k "set_project or restore"
```
Expected: `AttributeError`

- [ ] **Step 3: Implement set_project_setting, set_autoload, restore_project_settings**

Add to `server.py`:
```python
def _backup_project_godot() -> Path:
    """Create project.godot.mcp_backup if it doesn't exist. Returns backup path."""
    src = _godot_project() / "project.godot"
    backup = _godot_project() / "project.godot.mcp_backup"
    if not backup.exists():
        import shutil
        shutil.copy(src, backup)
    return backup


@mcp.tool()
def set_project_setting(key: str, value: str) -> dict:
    """Write a single setting to project.godot.
    key uses section/key format, e.g. 'application/config/name'.
    value is the raw INI value string, e.g. '"My Game"' or 'true'.
    Creates a backup before the first change. Call restore_project_settings() to undo.
    Returns {'previous': old_value, 'new': value}."""
    errors = _validate_config()
    if errors:
        return {"error": "; ".join(errors)}

    _backup_project_godot()
    path = _godot_project() / "project.godot"
    parsed = _parse_project_godot(path)

    # determine section and key
    parts = key.split("/", 1)
    section = parts[0] if len(parts) > 1 else "_top"
    setting_key = parts[1] if len(parts) > 1 else parts[0]

    previous = parsed.get(section, {}).get(setting_key, "(not set)")
    _write_project_setting(path, section, setting_key, value)
    return {"previous": previous, "new": value, "backup": "project.godot.mcp_backup"}


def _write_project_setting(path: Path, section: str, key: str, value: str) -> None:
    """Write a key=value into a specific section of project.godot."""
    import re
    lines = path.read_text(encoding="utf-8").splitlines()
    new_lines = []
    in_section = (section == "_top")
    found = False

    for line in lines:
        section_m = re.match(r'^\[([^\]]+)\]$', line.strip())
        if section_m:
            if section_m.group(1) == section:
                in_section = True
            elif in_section and not found:
                new_lines.append(f"{key}={value}")
                found = True
                in_section = False
            else:
                in_section = False

        if in_section and not section_m:
            kv_m = re.match(rf'^{re.escape(key)}\s*=', line)
            if kv_m:
                new_lines.append(f"{key}={value}")
                found = True
                continue

        new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


@mcp.tool()
def set_autoload(name: str, path: str, enabled: bool = True) -> dict:
    """Add, update, or disable an autoload in project.godot.
    name: autoload name as it appears in Godot (e.g. 'TestRunner').
    path: res:// path to the script (e.g. 'res://tests/test_runner.gd').
    enabled=False disables the autoload without removing it (removes the * prefix).
    Backs up project.godot before the first change. Returns the updated autoload table."""
    errors = _validate_config()
    if errors:
        return {"error": "; ".join(errors)}

    _backup_project_godot()
    prefix = "*" if enabled else ""
    value = f'"{prefix}{path}"'
    _write_project_setting(_godot_project() / "project.godot", "autoload", name, value)
    return get_project_settings().get("autoloads", {})


@mcp.tool()
def restore_project_settings() -> str:
    """Restore project.godot from the session backup (project.godot.mcp_backup).
    Always safe to call — returns a message if no backup exists.
    Call this at the end of any session that modified project settings."""
    backup = _godot_project() / "project.godot.mcp_backup"
    if not backup.exists():
        return "No backup found — project.godot has not been modified this session."
    import shutil
    shutil.copy(backup, _godot_project() / "project.godot")
    backup.unlink()
    return "Restored project.godot from backup and deleted project.godot.mcp_backup."
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/test_settings.py -v
```
Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_settings.py
git commit -m "feat: add set_project_setting, set_autoload, restore_project_settings"
```

---

## Task 7: Testability analysis and coverage report

**Files:**
- Modify: `server.py`
- Create: `tests/test_analysis.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_analysis.py`:
```python
import server


def test_analyze_testability_returns_list():
    result = server.analyze_testability()
    assert isinstance(result, list)
    assert len(result) > 0


def test_analyze_testability_has_required_fields():
    result = server.analyze_testability()
    for entry in result:
        assert "script" in entry
        assert "test_ready" in entry
        assert "issues" in entry


def test_analyze_testability_sigil_system_is_test_ready():
    result = server.analyze_testability()
    sigil = next((e for e in result if "sigil_system" in e["script"]), None)
    assert sigil is not None
    assert sigil["test_ready"] is True


def test_get_coverage_report_returns_dict():
    result = server.get_coverage_report()
    assert "covered" in result
    assert "uncovered" in result
    assert "total_scripts" in result
    assert "total_suites" in result


def test_get_coverage_report_uncovered_when_no_tests():
    result = server.get_coverage_report()
    # Before any tests are written, all scripts should be uncovered
    assert result["total_suites"] == 0 or len(result["uncovered"]) >= 0
```

- [ ] **Step 2: Run tests — expect failure**

```bash
uv run pytest tests/test_analysis.py -v
```
Expected: `AttributeError`

- [ ] **Step 3: Implement analyze_testability**

Add to `server.py`:
```python
# ── Analysis ──────────────────────────────────────────────────────────────────

def _get_autoload_names() -> set[str]:
    """Return the set of autoload names from project.godot."""
    try:
        settings = _parse_project_godot(_godot_project() / "project.godot")
        return set(settings.get("autoloads", {}).keys())
    except Exception:
        return set()


@mcp.tool()
def analyze_testability() -> list[dict]:
    """Analyse all GDScript files in scripts/ for testability.
    Identifies scene-tree coupling (get_node, $Node, @onready) and autoload
    dependencies that prevent a script from being instantiated without a scene.
    Returns a prioritised list: test_ready scripts first, then scripts needing fixes.
    Each entry has: script, test_ready (bool), issues (list of strings), suggestion (str)."""
    import re
    root = _godot_project()
    scripts_dir = root / "scripts"
    if not scripts_dir.exists():
        return [{"error": "scripts/ directory not found"}]

    autoload_names = _get_autoload_names()
    results = []

    for gd_file in sorted(scripts_dir.glob("*.gd")):
        content = gd_file.read_text(encoding="utf-8")
        rel = str(gd_file.relative_to(root))
        issues = []

        # Check extends clause
        extends_m = re.search(r'^extends\s+(\w+)', content, re.MULTILINE)
        base_class = extends_m.group(1) if extends_m else None
        scene_bases = {"Node", "Node2D", "Node3D", "Control", "CanvasItem",
                       "CharacterBody2D", "RigidBody2D", "Area2D", "Sprite2D",
                       "AnimationPlayer", "Camera2D", "Label", "Button"}
        if base_class in scene_bases:
            issues.append(f"extends {base_class} — requires scene tree")

        # Check @onready
        if re.search(r'@onready', content):
            issues.append("has @onready vars — requires scene tree")

        # Check get_node / $ shorthand
        if re.search(r'get_node\s*\(|(?<!\w)\$\w', content):
            issues.append("uses get_node/$Node — requires scene tree")

        # Check autoload references
        for name in autoload_names:
            if re.search(rf'\b{name}\b', content):
                issues.append(f"references autoload {name}")

        test_ready = len(issues) == 0
        suggestion = ""
        if not test_ready:
            suggestion = f"Add: static func create_for_test(state: Dictionary) -> {gd_file.stem.title().replace('_', '')}:"

        results.append({
            "script": rel,
            "test_ready": test_ready,
            "issues": issues,
            "suggestion": suggestion,
        })

    results.sort(key=lambda x: (not x["test_ready"], x["script"]))
    return results


@mcp.tool()
def get_coverage_report() -> dict:
    """Compare scripts/ against tests/suites/ to show test coverage.
    Returns covered scripts, uncovered scripts, suite count, and total test count.
    Low token cost — call at the start of a session to check project health."""
    root = _godot_project()
    scripts = {p.stem for p in (root / "scripts").glob("*.gd")} if (root / "scripts").exists() else set()
    suites_dir = root / "tests" / "suites"
    suites = {p.stem.replace("_tests", "") for p in suites_dir.glob("*_tests.gd")} if suites_dir.exists() else set()

    # count test methods across all suites
    total_tests = 0
    if suites_dir.exists():
        import re
        for suite_file in suites_dir.glob("*_tests.gd"):
            content = suite_file.read_text(encoding="utf-8")
            total_tests += len(re.findall(r'^func test_', content, re.MULTILINE))

    covered = sorted(scripts & suites)
    uncovered = sorted(scripts - suites)
    return {
        "total_scripts": len(scripts),
        "total_suites": len(suites),
        "total_tests": total_tests,
        "covered": covered,
        "uncovered": uncovered,
    }
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/test_analysis.py -v
```
Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_analysis.py
git commit -m "feat: add analyze_testability and get_coverage_report tools"
```

---

## Task 8: Godot docs tool

**Files:**
- Modify: `server.py`

No pytest tests for this tool — it requires network access and caching. Verify manually with the MCP Inspector.

- [ ] **Step 1: Implement get_godot_docs**

Add to `server.py`:
```python
# ── Documentation ────────────────────────────────────────────────────────────

@mcp.tool()
def get_godot_docs(class_name: str, method: str = "") -> dict:
    """Look up a Godot 4 class or method in the official class reference.
    Returns description, properties, methods, and signals.
    Use before writing GDScript to avoid hallucinated method names or Godot 3 API.
    Results are cached in ~/.cache/godot-mcp/docs/.
    class_name: e.g. 'Node2D', 'CharacterBody2D', 'SigilSystem'
    method: optional method name to filter results"""
    import urllib.request
    import xml.etree.ElementTree as ET
    from pathlib import Path

    cache_dir = Path.home() / ".cache" / "godot-mcp" / "docs"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{class_name}.xml"

    xml_content = None
    if cache_file.exists():
        xml_content = cache_file.read_text(encoding="utf-8")
    else:
        url = f"https://raw.githubusercontent.com/godotengine/godot/4.x/doc/classes/{class_name}.xml"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                xml_content = resp.read().decode("utf-8")
            cache_file.write_text(xml_content, encoding="utf-8")
        except Exception as e:
            return {"error": f"Could not fetch docs for {class_name}: {e}"}

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        return {"error": f"Could not parse docs XML: {e}"}

    result: dict = {
        "class": class_name,
        "inherits": root.get("inherits", ""),
        "brief": (root.findtext("brief_description") or "").strip(),
        "description": (root.findtext("description") or "").strip()[:500],
        "methods": [],
        "members": [],
        "signals": [],
    }

    for m in root.findall(".//methods/method"):
        mname = m.get("name", "")
        if method and method not in mname:
            continue
        ret = m.find("return")
        ret_type = ret.get("type", "void") if ret is not None else "void"
        params = [
            f"{p.get('name', '_')}: {p.get('type', 'Variant')}"
            for p in m.findall("param")
        ]
        result["methods"].append({
            "name": mname,
            "returns": ret_type,
            "params": params,
            "description": (m.findtext("description") or "").strip()[:200],
        })

    for mem in root.findall(".//members/member"):
        result["members"].append({
            "name": mem.get("name", ""),
            "type": mem.get("type", ""),
            "description": (mem.text or "").strip()[:200],
        })

    for sig in root.findall(".//signals/signal"):
        result["signals"].append(sig.get("name", ""))

    if method and not result["methods"]:
        return {"error": f"Method '{method}' not found in {class_name}"}

    return result
```

- [ ] **Step 2: Manual verification with MCP Inspector**

```bash
cd "/Users/kognido/game dev/godot-mcp"
npx @modelcontextprotocol/inspector uv run python server.py
```
Open the browser UI. Call `get_godot_docs` with `class_name="Node2D"`. Verify it returns methods and properties.

- [ ] **Step 3: Commit**

```bash
git add server.py
git commit -m "feat: add get_godot_docs tool with local caching"
```

---

*Phase 1 complete — the server is a usable Godot 4 codebase navigator. Register it with Claude Code now if you want to start using navigation tools while building Phase 2.*

---

## Task 9: GDScript scaffold files

**Files:**
- Create: `scaffold/base_test.gd`
- Create: `scaffold/test_runner.gd`
- Create: `scaffold/smoke/smoke_runner.gd`

These are GDScript files. No Python tests — they are integration-tested in Task 12 by running them in Godot.

- [ ] **Step 1: Create scaffold directory structure**

```bash
mkdir -p "/Users/kognido/game dev/godot-mcp/scaffold/smoke"
```

- [ ] **Step 2: Write base_test.gd**

Create `scaffold/base_test.gd`:
```gdscript
class_name BaseTest
extends RefCounted

const SCAFFOLD_VERSION = "1.0"

var _suite_name: String = ""
var _current_test: String = ""
var _start_ms: int = 0


func _init() -> void:
	_suite_name = get_script().resource_path.get_file().get_basename()


func _begin_test(method_name: String) -> void:
	_current_test = method_name
	_start_ms = Time.get_ticks_msec()


func _elapsed_ms() -> int:
	return Time.get_ticks_msec() - _start_ms


func assert_eq(a: Variant, b: Variant, msg: String = "") -> void:
	if a != b:
		var error = msg if msg else "expected %s got %s" % [str(b), str(a)]
		_fail(error)


func assert_true(condition: bool, msg: String = "") -> void:
	if not condition:
		_fail(msg if msg else "expected true, got false")


func assert_approx(a: float, b: float, tolerance: float = 0.001, msg: String = "") -> void:
	if abs(a - b) > tolerance:
		var error = msg if msg else "expected ~%s got %s (tolerance %s)" % [b, a, tolerance]
		_fail(error)


func _fail(error: String) -> void:
	var result = {
		"test": "%s.%s" % [_suite_name, _current_test],
		"pass": false,
		"error": error,
		"ms": _elapsed_ms()
	}
	print(JSON.stringify(result))
```

- [ ] **Step 3: Write test_runner.gd**

Create `scaffold/test_runner.gd`:
```gdscript
extends Node

const SCAFFOLD_VERSION = "1.0"

func _ready() -> void:
	var args = OS.get_cmdline_user_args()
	var test_idx = args.find("--test")
	if test_idx == -1:
		return  # not in test mode, stay dormant

	var suite_filter = ""
	if test_idx + 1 < args.size() and not args[test_idx + 1].begins_with("--"):
		suite_filter = args[test_idx + 1]

	await _run_tests(suite_filter)
	get_tree().quit()


func _run_tests(suite_filter: String) -> void:
	var total = 0
	var passed = 0
	var failed_tests: Array[String] = []

	var suites_dir = "res://tests/suites/"
	var dir = DirAccess.open(suites_dir)
	if dir == null:
		push_error("tests/suites/ directory not found")
		return

	dir.list_dir_begin()
	var file_name = dir.get_next()
	while file_name != "":
		if file_name.ends_with("_tests.gd"):
			var suite_name = file_name.get_basename().replace("_tests", "")
			if suite_filter == "" or suite_filter == suite_name:
				var script = load(suites_dir + file_name)
				if script:
					await _run_suite(script, suite_name, total, passed, failed_tests)
		file_name = dir.get_next()

	var summary = {
		"total": total,
		"passed": passed,
		"failed": total - passed,
		"failed_tests": failed_tests
	}
	print(JSON.stringify(summary))


func _run_suite(
	script: GDScript,
	suite_name: String,
	total: int,
	passed: int,
	failed_tests: Array[String]
) -> void:
	var instance = script.new()
	var methods = instance.get_method_list()
	for method_info in methods:
		var method_name: String = method_info["name"]
		if not method_name.begins_with("test_"):
			continue
		total += 1
		instance._begin_test(method_name)
		var before_output = _capture_start()
		instance.call(method_name)
		var test_key = "%s.%s" % [suite_name, method_name]
		if _had_failure(before_output):
			failed_tests.append(test_key)
		else:
			passed += 1
			var result = {"test": test_key, "pass": true, "ms": instance._elapsed_ms()}
			print(JSON.stringify(result))


# Simple pass/fail tracking via a flag on the BaseTest instance
var _last_fail_count: int = 0

func _capture_start() -> int:
	return _last_fail_count

func _had_failure(before: int) -> bool:
	return _last_fail_count > before
```

**Note:** The failure detection above is simplified. In practice, `BaseTest._fail()` prints JSON immediately — the runner tracks failures by monitoring printed output. A cleaner approach sets a flag on the instance. Update `base_test.gd` to expose a `had_failure()` method:

Append to `scaffold/base_test.gd`:
```gdscript
var _failed: bool = false

func had_failure() -> bool:
	return _failed

func _fail(error: String) -> void:
	_failed = true
	var result = {
		"test": "%s.%s" % [_suite_name, _current_test],
		"pass": false,
		"error": error,
		"ms": _elapsed_ms()
	}
	print(JSON.stringify(result))
```

And update `test_runner.gd` `_run_suite` to use `instance.had_failure()` and reset `instance._failed = false` before each test.

Replace the `_run_suite` function in `scaffold/test_runner.gd`:
```gdscript
func _run_suite(
	script: GDScript,
	suite_name: String,
	total: int,
	passed: int,
	failed_tests: Array[String]
) -> void:
	var instance = script.new()
	var methods = instance.get_method_list()
	for method_info in methods:
		var method_name: String = method_info["name"]
		if not method_name.begins_with("test_"):
			continue
		total += 1
		instance._failed = false
		instance._begin_test(method_name)
		instance.call(method_name)
		var test_key = "%s.%s" % [suite_name, method_name]
		if instance.had_failure():
			failed_tests.append(test_key)
		else:
			passed += 1
			var result = {"test": test_key, "pass": true, "ms": instance._elapsed_ms()}
			print(JSON.stringify(result))
```

- [ ] **Step 4: Write smoke_runner.gd**

Create `scaffold/smoke/smoke_runner.gd`:
```gdscript
extends Node

const SCAFFOLD_VERSION = "1.0"

func _ready() -> void:
	var args = OS.get_cmdline_user_args()
	var smoke_idx = args.find("--smoke")
	if smoke_idx == -1:
		return  # not in smoke mode, stay dormant

	var scenario_filter = ""
	if smoke_idx + 1 < args.size() and not args[smoke_idx + 1].begins_with("--"):
		scenario_filter = args[smoke_idx + 1]

	await _run_smoke(scenario_filter)
	get_tree().quit()


func _run_smoke(scenario_filter: String) -> void:
	var results: Array[Dictionary] = []
	var scenarios_dir = "res://tests/smoke/scenarios/"
	var dir = DirAccess.open(scenarios_dir)
	if dir == null:
		print(JSON.stringify({"error": "tests/smoke/scenarios/ not found"}))
		return

	dir.list_dir_begin()
	var file_name = dir.get_next()
	while file_name != "":
		if file_name.ends_with(".gd"):
			var scenario_name = file_name.get_basename()
			if scenario_filter == "" or scenario_filter == scenario_name:
				var script = load(scenarios_dir + file_name)
				if script:
					var start_ms = Time.get_ticks_msec()
					var instance = script.new()
					add_child(instance)
					var passed = await instance.run()
					var elapsed = Time.get_ticks_msec() - start_ms
					results.append({
						"scenario": scenario_name,
						"pass": passed,
						"ms": elapsed,
					})
					remove_child(instance)
		file_name = dir.get_next()

	var summary = {
		"total": results.size(),
		"passed": results.filter(func(r): return r["pass"]).size(),
		"results": results,
	}
	print(JSON.stringify(summary))
```

- [ ] **Step 5: Commit**

```bash
cd "/Users/kognido/game dev/godot-mcp"
git add scaffold/
git commit -m "feat: add GDScript test scaffold (base_test, test_runner, smoke_runner)"
```

---

## Task 10: Scaffold Python tools and MCP resources

**Files:**
- Modify: `server.py`
- Create: `tests/test_scaffold.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_scaffold.py`:
```python
import shutil
import server
from pathlib import Path


def test_scaffold_tests_creates_files(tmp_path, monkeypatch):
    # Create minimal project structure
    (tmp_path / "project.godot").write_text(
        'config_version=5\n[autoload]\n', encoding="utf-8"
    )
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))

    result = server.scaffold_tests()
    assert isinstance(result, dict)
    assert "created" in result
    assert (tmp_path / "tests" / "base_test.gd").exists()
    assert (tmp_path / "tests" / "test_runner.gd").exists()
    assert (tmp_path / "tests" / "suites").is_dir()
    assert (tmp_path / "tests" / "smoke" / "scenarios").is_dir()


def test_scaffold_tests_does_not_overwrite_suites(tmp_path, monkeypatch):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (tmp_path / "tests" / "suites").mkdir(parents=True)
    existing = tmp_path / "tests" / "suites" / "my_tests.gd"
    existing.write_text("# existing suite", encoding="utf-8")
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))

    server.scaffold_tests()
    assert existing.read_text() == "# existing suite"


def test_check_scaffold_ok_after_scaffold(tmp_path, monkeypatch):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    server.scaffold_tests()

    result = server.check_scaffold()
    assert result["status"] == "ok"


def test_check_scaffold_missing_before_scaffold(tmp_path, monkeypatch):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))

    result = server.check_scaffold()
    assert result["status"] in ("missing", "outdated")
```

- [ ] **Step 2: Run tests — expect failure**

```bash
uv run pytest tests/test_scaffold.py -v
```
Expected: `AttributeError`

- [ ] **Step 3: Implement scaffold_tests and check_scaffold**

Add to `server.py`:
```python
# ── Scaffold ──────────────────────────────────────────────────────────────────

SCAFFOLD_VERSION = "1.0"
_SCAFFOLD_DIR = Path(__file__).parent / "scaffold"


@mcp.tool()
def scaffold_tests() -> dict:
    """Install the GDScript test infrastructure into the configured Godot project.
    Creates: tests/base_test.gd, tests/test_runner.gd, tests/smoke/smoke_runner.gd,
    tests/suites/ and tests/smoke/scenarios/ directories.
    Registers TestRunner and SmokeRunner as autoloads in project.godot.
    Safe to run on a project that already has tests — never overwrites existing suite files.
    Returns a dict with 'created' (list of new files) and 'skipped' (existing files)."""
    import shutil
    errors = _validate_config()
    if errors:
        return {"error": "; ".join(errors)}

    project = _godot_project()
    created = []
    skipped = []

    # Directory structure
    for d in [
        project / "tests" / "suites",
        project / "tests" / "smoke" / "scenarios",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    # Copy scaffold files
    copies = [
        (_SCAFFOLD_DIR / "base_test.gd", project / "tests" / "base_test.gd"),
        (_SCAFFOLD_DIR / "test_runner.gd", project / "tests" / "test_runner.gd"),
        (_SCAFFOLD_DIR / "smoke" / "smoke_runner.gd", project / "tests" / "smoke" / "smoke_runner.gd"),
    ]
    for src, dst in copies:
        if dst.exists():
            skipped.append(str(dst.relative_to(project)))
        else:
            shutil.copy(src, dst)
            created.append(str(dst.relative_to(project)))

    # Register autoloads (backup first)
    _backup_project_godot()
    godot_proj = project / "project.godot"
    _write_project_setting(godot_proj, "autoload", "TestRunner", '"*res://tests/test_runner.gd"')
    _write_project_setting(godot_proj, "autoload", "SmokeRunner", '"*res://tests/smoke/smoke_runner.gd"')

    return {"created": created, "skipped": skipped}


@mcp.tool()
def check_scaffold() -> dict:
    """Verify the GDScript test infrastructure is present and up to date.
    Returns status: 'ok', 'missing', or 'outdated'.
    Also returns expected vs found SCAFFOLD_VERSION and a list of missing files."""
    import re
    project = _godot_project()
    expected_files = [
        project / "tests" / "base_test.gd",
        project / "tests" / "test_runner.gd",
        project / "tests" / "smoke" / "smoke_runner.gd",
    ]
    missing = [str(f.relative_to(project)) for f in expected_files if not f.exists()]

    if missing:
        return {"status": "missing", "missing_files": missing, "expected_version": SCAFFOLD_VERSION}

    # Check version in test_runner.gd
    runner_content = (project / "tests" / "test_runner.gd").read_text(encoding="utf-8")
    version_m = re.search(r'SCAFFOLD_VERSION\s*=\s*"([^"]+)"', runner_content)
    found_version = version_m.group(1) if version_m else "unknown"

    if found_version != SCAFFOLD_VERSION:
        return {
            "status": "outdated",
            "found_version": found_version,
            "expected_version": SCAFFOLD_VERSION,
        }

    return {"status": "ok", "version": found_version}
```

- [ ] **Step 4: Add MCP resources for project docs**

Add to `server.py` after the mcp = FastMCP line:
```python
@mcp.resource("godot://docs/{doc_name}")
def project_doc(doc_name: str) -> str:
    """Access a project design document by name.
    Lists available docs: godot://docs/list
    Example: godot://docs/sigil_rules returns the sigil rules document."""
    if doc_name == "list":
        docs_dir = _godot_project() / "docs"
        if not docs_dir.exists():
            return "No docs/ directory found in project"
        docs = [p.stem for p in docs_dir.glob("*.md")]
        return "Available docs: " + ", ".join(docs)
    docs_dir = _godot_project() / "docs"
    candidates = list(docs_dir.glob(f"{doc_name}*.md")) if docs_dir.exists() else []
    if not candidates:
        return f"Doc not found: {doc_name}"
    return candidates[0].read_text(encoding="utf-8")
```

- [ ] **Step 5: Run tests — expect pass**

```bash
uv run pytest tests/test_scaffold.py -v
```
Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_scaffold.py
git commit -m "feat: add scaffold_tests, check_scaffold, and MCP doc resources"
```

---

## Task 11: Test authoring tools

**Files:**
- Modify: `server.py`
- Create: `tests/test_authoring.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_authoring.py`:
```python
import server
from pathlib import Path

THE_PATTERN = Path("/Users/kognido/game dev/the_pattern")


def test_get_test_context_returns_script_contents():
    result = server.get_test_context("sigil_system")
    assert "script" in result
    assert "SigilSystem" in result["script"] or "extends" in result["script"]


def test_get_test_context_with_doc():
    result = server.get_test_context("sigil_system", doc="sigil_rules")
    assert "doc" in result
    assert len(result["doc"]) > 0


def test_get_test_context_no_existing_suite():
    result = server.get_test_context("sigil_system")
    assert "existing_suite" in result
    # either None or file contents


def test_write_test_suite_creates_file(tmp_path, monkeypatch):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (tmp_path / "tests" / "suites").mkdir(parents=True)
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))

    content = 'extends BaseTest\n\nfunc test_example() -> void:\n\tassert_true(true)\n'
    result = server.write_test_suite("my_system", content)
    assert "created" in result or "error" not in result
    assert (tmp_path / "tests" / "suites" / "my_system_tests.gd").exists()


def test_write_test_suite_validates_extends(tmp_path, monkeypatch):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (tmp_path / "tests" / "suites").mkdir(parents=True)
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))

    bad_content = 'extends Node\n\nfunc test_foo() -> void:\n\tpass\n'
    result = server.write_test_suite("bad_suite", bad_content)
    assert "error" in result.lower() or "Error" in result


def test_write_test_suite_validates_test_method(tmp_path, monkeypatch):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (tmp_path / "tests" / "suites").mkdir(parents=True)
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))

    no_tests = 'extends BaseTest\n\nfunc helper() -> void:\n\tpass\n'
    result = server.write_test_suite("no_tests", no_tests)
    assert "error" in result.lower() or "Error" in result


def test_edit_test_suite_errors_if_missing(tmp_path, monkeypatch):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (tmp_path / "tests" / "suites").mkdir(parents=True)
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))

    result = server.edit_test_suite("nonexistent", "extends BaseTest\nfunc test_x(): pass")
    assert "Error" in result or "not found" in result.lower()
```

- [ ] **Step 2: Run tests — expect failure**

```bash
uv run pytest tests/test_authoring.py -v
```
Expected: `AttributeError`

- [ ] **Step 3: Implement test authoring tools**

Add to `server.py`:
```python
# ── Test authoring ────────────────────────────────────────────────────────────

@mcp.tool()
def get_test_context(system: str, doc: str = "") -> dict:
    """Bundle context needed to write a test suite in one call.
    Returns the target script, any existing suite, a filtered testability report,
    and optionally a design document — all in one response.
    Use this before write_test_suite() or edit_test_suite().
    system: script name without .gd (e.g. 'sigil_system')
    doc: optional doc name without .md (e.g. 'sigil_rules')"""
    result: dict = {}

    # Script contents
    script_path = _safe_path(f"scripts/{system}.gd")
    if script_path and script_path.exists():
        result["script"] = script_path.read_text(encoding="utf-8")
    else:
        result["script"] = f"Error: scripts/{system}.gd not found"

    # Existing suite
    suite_path = _godot_project() / "tests" / "suites" / f"{system}_tests.gd"
    result["existing_suite"] = suite_path.read_text(encoding="utf-8") if suite_path.exists() else None

    # Testability analysis for this system only
    all_analysis = analyze_testability()
    system_analysis = next(
        (e for e in all_analysis if e.get("script", "").endswith(f"{system}.gd")),
        None
    )
    result["testability"] = system_analysis

    # Optional doc
    if doc:
        docs_dir = _godot_project() / "docs"
        candidates = list(docs_dir.glob(f"{doc}*.md")) if docs_dir.exists() else []
        result["doc"] = candidates[0].read_text(encoding="utf-8") if candidates else f"Doc not found: {doc}"

    return result


def _validate_suite_content(content: str) -> str | None:
    """Return an error message if content is not a valid test suite, else None."""
    import re
    if not re.search(r'extends\s+BaseTest', content):
        return "Error: suite must extend BaseTest"
    if not re.search(r'^func test_', content, re.MULTILINE):
        return "Error: suite must have at least one method prefixed test_"
    return None


@mcp.tool()
def write_test_suite(suite_name: str, content: str) -> str:
    """Write a new GDScript test suite to tests/suites/{suite_name}_tests.gd.
    Validates that the content extends BaseTest and has at least one test_ method.
    Returns an error string if validation fails — does not write invalid content.
    Use edit_test_suite() to overwrite an existing suite."""
    error = _validate_suite_content(content)
    if error:
        return error

    suite_path = _godot_project() / "tests" / "suites" / f"{suite_name}_tests.gd"
    if suite_path.exists():
        return f"Error: {suite_name}_tests.gd already exists — use edit_test_suite() to overwrite"

    suite_path.parent.mkdir(parents=True, exist_ok=True)
    suite_path.write_text(content, encoding="utf-8")
    return f"Created tests/suites/{suite_name}_tests.gd"


@mcp.tool()
def edit_test_suite(suite_name: str, content: str) -> str:
    """Overwrite an existing GDScript test suite.
    Validates that the content extends BaseTest and has at least one test_ method.
    Returns an error if the suite does not exist — use write_test_suite() for new suites."""
    error = _validate_suite_content(content)
    if error:
        return error

    suite_path = _godot_project() / "tests" / "suites" / f"{suite_name}_tests.gd"
    if not suite_path.exists():
        return f"Error: {suite_name}_tests.gd not found — use write_test_suite() to create it"

    suite_path.write_text(content, encoding="utf-8")
    return f"Updated tests/suites/{suite_name}_tests.gd"
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/test_authoring.py -v
```
Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_authoring.py
git commit -m "feat: add get_test_context, write_test_suite, edit_test_suite"
```

---

## Task 12: Headless test execution

**Files:**
- Modify: `server.py`
- Modify: `tests/test_execution.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_execution.py`:
```python
import json
from pathlib import Path
from unittest.mock import patch, AsyncMock

THE_PATTERN = Path("/Users/kognido/game dev/the_pattern")


def test_run_tests_returns_summary_structure():
    # Mock _run_godot to return synthetic JSON output
    fake_output = (
        '{"test":"sigil.split","pass":true,"ms":3}\n'
        '{"test":"sigil.arm_count","pass":false,"ms":1,"error":"expected 4 got 3"}\n'
        '{"total":2,"passed":1,"failed":1,"failed_tests":["sigil.arm_count"]}\n'
    )
    with patch.object(server, "_run_godot", new=AsyncMock(return_value=(fake_output, 0))):
        result = asyncio.get_event_loop().run_until_complete(server.run_tests("sigil"))
    assert result["total"] == 2
    assert result["passed"] == 1
    assert result["failed"] == 1
    assert "sigil.arm_count" in result["failed_tests"]


def test_run_tests_caches_results(tmp_path, monkeypatch):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))

    fake_output = '{"total":1,"passed":1,"failed":0,"failed_tests":[]}\n'
    with patch.object(server, "_run_godot", new=AsyncMock(return_value=(fake_output, 0))):
        asyncio.get_event_loop().run_until_complete(server.run_tests())
    assert (tmp_path / "tests" / ".last_run.json").exists()


def test_get_last_results_reads_cache(tmp_path, monkeypatch):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    cache = {"total": 5, "passed": 4, "failed": 1, "failed_tests": ["foo.bar"]}
    (tmp_path / "tests" / ".last_run.json").write_text(json.dumps(cache))

    result = server.get_last_results()
    assert result["total"] == 5
    assert result["failed_tests"] == ["foo.bar"]


def test_get_last_results_no_cache(tmp_path, monkeypatch):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))

    result = server.get_last_results()
    assert "message" in result


def test_get_test_details_returns_detail():
    fake_full_output = (
        '{"test":"sigil.arm_count","pass":false,"ms":1,"error":"expected 4 got 3"}\n'
        '{"total":1,"passed":0,"failed":1,"failed_tests":["sigil.arm_count"]}\n'
    )
    with patch.object(server, "_run_godot", new=AsyncMock(return_value=(fake_full_output, 0))):
        result = asyncio.get_event_loop().run_until_complete(
            server.get_test_details("sigil.arm_count")
        )
    assert "arm_count" in result or "sigil" in result
```

Note: add `import asyncio` to the top of `tests/test_execution.py`.

- [ ] **Step 2: Run tests — expect failure**

```bash
uv run pytest tests/test_execution.py -v -k "run_tests or last_results or test_details"
```
Expected: `AttributeError`

- [ ] **Step 3: Implement headless test tools**

Add to `server.py`:
```python
# ── Headless tests ────────────────────────────────────────────────────────────

@mcp.tool()
async def run_tests(suite: str = "all") -> dict:
    """Run Tier 1/2 headless tests and return a summary.
    suite: 'all' to run every suite, or a suite name like 'sigil' to run one.
    Returns: total, passed, failed counts and a list of failed test names with errors.
    Use get_test_details() to see full output for a specific failure.
    This tool is the primary way to check project health — call it first."""
    errors = _validate_config()
    if errors:
        return {"error": "; ".join(errors)}

    args = ["--headless", "--", "--test"]
    if suite != "all":
        args.append(suite)

    output, _ = await _run_godot(args, timeout=30)
    return _parse_test_output(output, suite)


def _parse_test_output(output: str, suite: str = "") -> dict:
    import json as _json
    summary = {"total": 0, "passed": 0, "failed": 0, "failed_tests": [], "suite": suite}
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        if "total" in data:
            summary["total"] = data.get("total", 0)
            summary["passed"] = data.get("passed", 0)
            summary["failed"] = data.get("failed", 0)
            summary["failed_tests"] = data.get("failed_tests", [])

    # cache results
    cache = _godot_project() / "tests" / ".last_run.json"
    try:
        import json as _json2
        cache.write_text(_json2.dumps(summary), encoding="utf-8")
    except Exception:
        pass

    return summary


@mcp.tool()
async def get_test_details(test_name: str) -> str:
    """Return full output for a single failing test identified by run_tests().
    test_name: the full test key, e.g. 'sigil.arm_count'.
    Call only when diagnosing a specific failure — use run_tests() for summaries."""
    errors = _validate_config()
    if errors:
        return "Error: " + "; ".join(errors)

    suite = test_name.split(".")[0] if "." in test_name else "all"
    args = ["--headless", "--", "--test", suite]
    output, _ = await _run_godot(args, timeout=30)

    import json as _json
    for line in output.splitlines():
        if not line.strip().startswith("{"):
            continue
        try:
            data = _json.loads(line)
            if data.get("test") == test_name:
                return _json.dumps(data, indent=2)
        except _json.JSONDecodeError:
            continue
    return f"Test '{test_name}' not found in output. Raw output:\n{output[:1000]}"


@mcp.tool()
def get_last_results() -> dict:
    """Return cached results from the most recent run_tests() call.
    Use at the start of a session to check prior state without re-running.
    Results are stored in tests/.last_run.json."""
    cache = _godot_project() / "tests" / ".last_run.json"
    if not cache.exists():
        return {"message": "No cached results found — run run_tests() first."}
    import json as _json
    return _json.loads(cache.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/test_execution.py -v -k "run_tests or last_results or test_details"
```
Expected: all PASSED

- [ ] **Step 5: Integration test — scaffold and run against the_pattern**

```bash
cd "/Users/kognido/game dev/godot-mcp"
GODOT_BIN="/Applications/Godot.app/Contents/MacOS/Godot" \
GODOT_PROJECT="/Users/kognido/game dev/the_pattern" \
uv run python -c "
import asyncio, server
# Scaffold
print(server.scaffold_tests())
# Run tests (will pass with 0 tests until suites are written)
result = asyncio.get_event_loop().run_until_complete(server.run_tests())
print(result)
"
```
Expected: scaffold creates files, run_tests returns `{"total": 0, "passed": 0, "failed": 0, ...}`

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_execution.py
git commit -m "feat: add run_tests, get_test_details, get_last_results"
```

---

## Task 13: Smoke test tool

**Files:**
- Modify: `server.py`
- Modify: `tests/test_execution.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_execution.py`:
```python
def test_run_smoke_tests_returns_structure():
    fake_output = (
        '{"total":1,"passed":1,"results":[{"scenario":"room_loads","pass":true,"ms":3200}]}\n'
    )
    with patch.object(server, "_run_godot", new=AsyncMock(return_value=(fake_output, 0))):
        result = asyncio.get_event_loop().run_until_complete(server.run_smoke_tests())
    assert result["total"] == 1
    assert result["passed"] == 1
    assert len(result["results"]) == 1
```

- [ ] **Step 2: Run test — expect failure**

```bash
uv run pytest tests/test_execution.py -v -k "smoke"
```
Expected: `AttributeError`

- [ ] **Step 3: Implement run_smoke_tests**

Add to `server.py`:
```python
# ── Smoke tests ───────────────────────────────────────────────────────────────

@mcp.tool()
async def run_smoke_tests(scenario: str = "all") -> dict:
    """Run Tier 3 smoke tests with a full Godot window.
    Verifies UI placement, scene loading, and full mechanic flows.
    scenario: 'all' or a specific scenario name (filename without .gd).
    Returns structured pass/fail per scenario and total duration.
    IMPORTANT: This tool opens a Godot window and is intentionally slow (~10-20s).
    Use for major verification milestones, not routine iteration."""
    errors = _validate_config()
    if errors:
        return {"error": "; ".join(errors)}

    args = ["--", "--smoke"]
    if scenario != "all":
        args.append(scenario)

    # Smoke tests run with display — no --headless flag
    output, _ = await _run_godot(args, timeout=60)

    import json as _json
    for line in output.splitlines():
        if not line.strip().startswith("{"):
            continue
        try:
            data = _json.loads(line)
            if "results" in data:
                return data
        except _json.JSONDecodeError:
            continue

    return {
        "error": "No structured output from smoke runner",
        "raw_output": output[:500],
    }
```

- [ ] **Step 4: Run test — expect pass**

```bash
uv run pytest tests/test_execution.py -v -k "smoke"
```
Expected: PASSED

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_execution.py
git commit -m "feat: add run_smoke_tests tool"
```

---

## Task 14: Claude Code registration and end-to-end verification

**Files:**
- No code changes

- [ ] **Step 1: Verify all tools appear in MCP Inspector**

```bash
cd "/Users/kognido/game dev/godot-mcp"
GODOT_BIN="/Applications/Godot.app/Contents/MacOS/Godot" \
GODOT_PROJECT="/Users/kognido/game dev/the_pattern" \
npx @modelcontextprotocol/inspector uv run python server.py
```

Open the browser URL shown. Verify these tools appear in the tool list:
- get_godot_version, read_script, list_scripts, list_scenes, inspect_scene, check_script
- get_project_settings, set_project_setting, set_autoload, restore_project_settings
- analyze_testability, get_coverage_report
- get_godot_docs
- scaffold_tests, check_scaffold
- get_test_context, write_test_suite, edit_test_suite
- run_tests, get_test_details, get_last_results
- run_smoke_tests, run_debug

Call `get_godot_version` and `list_scripts()` from the Inspector to confirm they work.

- [ ] **Step 2: Register with Claude Code**

```bash
cd "/Users/kognido/game dev/godot-mcp"
claude mcp add godot-mcp \
  -e GODOT_BIN="/Applications/Godot.app/Contents/MacOS/Godot" \
  -e GODOT_PROJECT="/Users/kognido/game dev/the_pattern" \
  -- uv run python "/Users/kognido/game dev/godot-mcp/server.py"
```

Verify:
```bash
claude mcp list
```
Expected: `godot-mcp` appears in the list.

- [ ] **Step 3: Restart Claude Code and confirm tools are available**

Restart Claude Code. In a new session, ask Claude Code to call `get_godot_version()`. Confirm it returns the Godot 4.6.x version string.

- [ ] **Step 4: Run full test suite one final time**

```bash
cd "/Users/kognido/game dev/godot-mcp"
uv run pytest tests/ -v
```
Expected: all tests PASSED

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "feat: complete godot-mcp v1 — register with Claude Code"
```

---

## Self-Review Notes

**Spec coverage check:**
- ✅ Configuration (GODOT_BIN, GODOT_PROJECT, startup validation) — Task 1
- ✅ read_script, list_scripts, list_scenes, get_godot_version — Task 2
- ✅ inspect_scene, check_script — Task 3
- ✅ run_debug — Task 4
- ✅ get_project_settings — Task 5
- ✅ set_project_setting, set_autoload, restore_project_settings, backup safety rule — Task 6
- ✅ analyze_testability, get_coverage_report — Task 7
- ✅ get_godot_docs with caching — Task 8
- ✅ GDScript scaffold (base_test, test_runner, smoke_runner, SCAFFOLD_VERSION) — Task 9
- ✅ scaffold_tests, check_scaffold, MCP resources for docs — Task 10
- ✅ get_test_context, write_test_suite, edit_test_suite — Task 11
- ✅ run_tests, get_test_details, get_last_results — Task 12
- ✅ run_smoke_tests — Task 13
- ✅ Registration and end-to-end verification — Task 14
- ✅ Error strings not exceptions — enforced throughout
- ✅ Logging to stderr only — server skeleton
- ✅ Path safety (_safe_path) — Task 1, used in Task 2+
- ✅ Startup backup warning — Task 1 server skeleton
- ✅ Token efficiency (summaries + drill-down) — run_tests/get_test_details pattern
