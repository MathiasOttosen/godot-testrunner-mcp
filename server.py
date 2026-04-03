import json
import os
import shutil
import socket
import time
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP("godot-mcp")


# ── Configuration ──────────────────────────────────────────────────────────────

def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Environment variable {name} is required but not set")
    return val


def GODOT_BIN() -> str:  # noqa: N802
    return _require_env("GODOT_BIN")


def GODOT_PROJECT() -> str:  # noqa: N802
    return _require_env("GODOT_PROJECT")


def safe_path(relative: str) -> Path | None:
    """Return resolved path if inside project root, None if path escapes."""
    root = Path(GODOT_PROJECT()).resolve()
    target = (root / relative).resolve()
    return target if target.is_relative_to(root) else None


# ── Scaffold ───────────────────────────────────────────────────────────────────

SCAFFOLD_VERSION = "1.0"

_SCAFFOLD_FILES = [
    "tests/base_test.gd",
    "tests/test_runner.gd",
    "tests/smoke/smoke_runner.gd",
]


@mcp.tool()
def scaffold_tests() -> str:
    """Install GDScript test infrastructure into the configured Godot project.
    Creates tests/ directory structure with base_test.gd, test_runner.gd, and
    smoke_runner.gd. Registers test runner autoloads in project.godot.
    Safe to run on a project that already has tests — never overwrites existing suite files.
    Returns a list of files created."""
    project = GODOT_PROJECT()
    scaffold_src = Path(__file__).parent / "scaffold"
    created: list[str] = []

    # Core GDScript test infrastructure
    for rel in _SCAFFOLD_FILES:
        src = scaffold_src / rel
        dst = Path(project) / rel
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shutil.copy(src, dst)
            created.append(rel)

    # Create suites and smoke/scenarios directories
    for d in ["tests/suites", "tests/smoke/scenarios"]:
        p = Path(project) / d
        p.mkdir(parents=True, exist_ok=True)

    # Register autoloads in project.godot
    project_godot = Path(project) / "project.godot"
    if project_godot.exists():
        content = project_godot.read_text(encoding="utf-8")
        autoloads_to_add = {
            "GodotMCPTestRunner": "*res://tests/test_runner.gd",
            "GodotMCPSmokeRunner": "*res://tests/smoke/smoke_runner.gd",
        }
        changed = False
        for name, path in autoloads_to_add.items():
            if name not in content:
                if "[autoload]" in content:
                    content = content.replace("[autoload]", f"[autoload]\n{name}=\"{path}\"")
                else:
                    content += f"\n[autoload]\n{name}=\"{path}\"\n"
                changed = True
                created.append(f"project.godot ({name} autoload)")
        if changed:
            project_godot.write_text(content, encoding="utf-8")

    if not created:
        return "Scaffold already up to date — no files created."
    return "Created:\n" + "\n".join(f"  {f}" for f in created)


@mcp.tool()
def check_scaffold() -> str:
    """Verify the GDScript test infrastructure is present and matches the expected
    SCAFFOLD_VERSION. Returns status (ok / missing / outdated), version found vs
    expected, and list of missing files if any."""
    project = GODOT_PROJECT()
    missing: list[str] = []

    for rel in _SCAFFOLD_FILES:
        if not (Path(project) / rel).exists():
            missing.append(rel)

    if missing:
        return f"Status: missing\nMissing files:\n" + "\n".join(f"  {f}" for f in missing)

    # Check scaffold version in base_test.gd
    base_test = Path(project) / "tests" / "base_test.gd"
    content = base_test.read_text(encoding="utf-8")
    if f'SCAFFOLD_VERSION = "{SCAFFOLD_VERSION}"' not in content:
        return f"Status: outdated\nExpected version: {SCAFFOLD_VERSION}"

    return f"Status: ok\nVersion: {SCAFFOLD_VERSION}"


# ── EditorBridge placeholder (filled in Task 1) ────────────────────────────────

# (EditorBridge class and _bridge singleton will be added here in Task 1)


# ── Tools (stubs — filled in subsequent tasks) ─────────────────────────────────

@mcp.tool()
def inspect_ui_scene(path: str, depth: int = 1) -> str:
    """Load a Godot scene into the editor's SubViewport and return its UI node tree as JSON.
    Stub — implemented in Task 2."""
    raise NotImplementedError("inspect_ui_scene not yet implemented")


@mcp.tool()
def start_ui_session(scene_path: str = "", timeout: int = 15) -> str:
    """Launch the Godot game with --mcp flag and open a RemoteControl session.
    Stub — implemented in Task 4."""
    raise NotImplementedError("start_ui_session not yet implemented")


@mcp.tool()
def end_ui_session() -> str:
    """End the active UI session and quit the game.
    Stub — implemented in Task 4."""
    raise NotImplementedError("end_ui_session not yet implemented")


@mcp.tool()
def navigate_ui(action: str, params: dict = {}) -> str:
    """Send a navigation or input command to the active UI session.
    Stub — implemented in Task 4."""
    raise NotImplementedError("navigate_ui not yet implemented")


@mcp.tool()
def get_live_ui(depth: int = 1) -> str:
    """Return the current UI tree from the active game session.
    Stub — implemented in Task 4."""
    raise NotImplementedError("get_live_ui not yet implemented")


@mcp.tool()
def screenshot_ui(save_path: str = "") -> str:
    """Capture the current viewport as a PNG.
    Stub — implemented in Task 4."""
    raise NotImplementedError("screenshot_ui not yet implemented")


if __name__ == "__main__":
    mcp.run()
