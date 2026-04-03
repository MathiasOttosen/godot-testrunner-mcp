import json
import os
import shutil
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP("godot-mcp")


# ── Configuration ──────────────────────────────────────────────────────────────

def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Environment variable {name} is required but not set")
    return val


def godot_bin() -> str:
    return _require_env("GODOT_BIN")


def godot_project() -> str:
    return _require_env("GODOT_PROJECT")


def safe_path(relative: str) -> Path | None:
    """Return resolved path if inside project root, None if path escapes."""
    root = Path(godot_project()).resolve()
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
    project = godot_project()
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

    # Install UI verification addon files
    addon_src = Path(__file__).parent / "scaffold" / "addons" / "godot_mcp"
    addon_dst = Path(project) / "addons" / "godot_mcp"
    addon_dst.mkdir(parents=True, exist_ok=True)
    for fname in ("plugin.cfg", "plugin.gd", "remote_control.gd"):
        src = addon_src / fname
        dst = addon_dst / fname
        if src.exists() and not dst.exists():
            shutil.copy(src, dst)
            created.append(f"addons/godot_mcp/{fname}")

    # Create screenshots directory
    screenshots_dir = Path(project) / "tests" / "ui_screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    gitkeep = screenshots_dir / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()
        created.append("tests/ui_screenshots/.gitkeep")

    # Register RemoteControl autoload
    if project_godot.exists():
        content = project_godot.read_text(encoding="utf-8")
        if "GodotMCPRemoteControl" not in content:
            autoload_line = 'GodotMCPRemoteControl="*res://addons/godot_mcp/remote_control.gd"'
            if "[autoload]" in content:
                content = content.replace("[autoload]", f"[autoload]\n{autoload_line}", 1)
            else:
                content += f"\n[autoload]\n{autoload_line}\n"
            project_godot.write_text(content, encoding="utf-8")
            created.append("project.godot (GodotMCPRemoteControl autoload)")

    if not created:
        return "Scaffold already up to date — no files created."
    return "Created:\n" + "\n".join(f"  {f}" for f in created)


@mcp.tool()
def check_scaffold() -> str:
    """Verify the GDScript test infrastructure is present and matches the expected
    SCAFFOLD_VERSION. Returns status (ok / missing / outdated), version found vs
    expected, and list of missing files if any."""
    project = godot_project()
    missing: list[str] = []

    for rel in _SCAFFOLD_FILES:
        if not (Path(project) / rel).exists():
            missing.append(rel)

    # Check UI verification addon files
    addon_files = [
        Path(project) / "addons" / "godot_mcp" / "plugin.cfg",
        Path(project) / "addons" / "godot_mcp" / "plugin.gd",
        Path(project) / "addons" / "godot_mcp" / "remote_control.gd",
    ]
    for f in addon_files:
        if not f.exists():
            missing.append(str(f.relative_to(project)))

    if missing:
        return f"Status: missing\nMissing files:\n" + "\n".join(f"  {f}" for f in missing)

    # Check scaffold version in base_test.gd
    base_test = Path(project) / "tests" / "base_test.gd"
    content = base_test.read_text(encoding="utf-8")
    if f'SCAFFOLD_VERSION = "{SCAFFOLD_VERSION}"' not in content:
        return f"Status: outdated\nExpected version: {SCAFFOLD_VERSION}"

    return f"Status: ok\nVersion: {SCAFFOLD_VERSION}"


# ── EditorBridge ──────────────────────────────────────────────────────────────

class EditorBridge:
    """Manages TCP connections to the Godot EditorPlugin (:6789) and
    the in-game RemoteControl autoload (:6790)."""

    EDITOR_PORT: int = 6789
    REMOTE_PORT: int = 6790
    CONNECT_TIMEOUT: float = 2.0

    def __init__(self) -> None:
        self._session_conn: socket.socket | None = None
        self._session_proc: subprocess.Popen | None = None

    # ── Editor (stateless, per-call connection) ────────────────────────────

    def send_editor_command(self, cmd: str, **params) -> dict:
        """Open a connection to the EditorPlugin, send one command, return response."""
        try:
            with socket.create_connection(
                ("localhost", self.EDITOR_PORT), timeout=self.CONNECT_TIMEOUT
            ) as conn:
                return self._transact(conn, cmd, params)
        except ConnectionRefusedError:
            return {
                "ok": False,
                "error": "editor bridge not available — is the Godot editor open?",
            }
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    def inspect_ui_scene_full(self, path: str, depth: int) -> dict:
        """Load scene, capture UI tree, unload — all in one connection."""
        try:
            with socket.create_connection(
                ("localhost", self.EDITOR_PORT), timeout=self.CONNECT_TIMEOUT
            ) as conn:
                r = self._transact(conn, "load_scene", {"path": path})
                if not r["ok"]:
                    return r
                r = self._transact(conn, "get_ui", {"depth": depth})
                if not r["ok"]:
                    self._transact(conn, "unload", {})  # clean up even on failure
                    return r
                tree = r["tree"]
                self._transact(conn, "unload", {})
                return {"ok": True, "tree": tree}
        except ConnectionRefusedError:
            return {
                "ok": False,
                "error": "editor bridge not available — is the Godot editor open?",
            }
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    # ── Session (persistent connection to running game) ────────────────────

    def start_session(
        self, godot_bin: str, project_path: str, scene_path: str, timeout: int
    ) -> dict:
        """Launch game with --mcp flag, wait for RemoteControl to connect."""
        args = [godot_bin, "--path", project_path, "--", "--mcp"]
        if scene_path:
            args += ["--mcp-scene", scene_path]
        self._session_proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                conn = socket.create_connection(
                    ("localhost", self.REMOTE_PORT), timeout=1.0
                )
                self._session_conn = conn
                return {"ok": True}
            except (ConnectionRefusedError, OSError):
                time.sleep(0.5)
        self._session_proc.kill()
        self._session_proc = None
        return {
            "ok": False,
            "error": f"game did not connect within {timeout}s — check for autoload errors",
        }

    def send_session_command(self, cmd: str, **params) -> dict:
        """Send a command to the active game session."""
        if self._session_conn is None:
            return {
                "ok": False,
                "error": "no active UI session — call start_ui_session first",
            }
        try:
            return self._transact(self._session_conn, cmd, params)
        except OSError:
            self._session_conn = None
            return {
                "ok": False,
                "error": "session disconnected — call start_ui_session to reconnect",
            }

    def end_session(self) -> dict:
        """Send quit to game and close connection."""
        if self._session_conn is not None:
            try:
                self._transact(self._session_conn, "quit", {})
            except OSError:
                pass
            try:
                self._session_conn.close()
            except OSError:
                pass
            self._session_conn = None
        if self._session_proc is not None:
            try:
                self._session_proc.wait(timeout=5)
            except Exception:
                self._session_proc.kill()
            self._session_proc = None
        return {"ok": True}

    def screenshot(self, save_path: str, project_path: str) -> dict:
        """Capture from active game session if running, else from editor plugin."""
        resolved = save_path or self._default_screenshot_path(project_path)
        if self._session_conn is not None:
            return self.send_session_command("screenshot", save_path=resolved)
        return self.send_editor_command("screenshot", save_path=resolved)

    # ── Shared helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _transact(conn: socket.socket, cmd: str, params: dict) -> dict:
        msg = json.dumps({"cmd": cmd, **params}) + "\n"
        conn.sendall(msg.encode())
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                raise OSError("connection closed before response")
            buf += chunk
        return json.loads(buf.split(b"\n")[0])

    @staticmethod
    def _default_screenshot_path(project_path: str) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(Path(project_path) / "tests" / "ui_screenshots" / f"{ts}.png")


_bridge = EditorBridge()


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def inspect_ui_scene(path: str, depth: int = 1) -> str:
    """Load a Godot scene into the editor's SubViewport and return its UI node tree as JSON.
    path is relative to the project root (e.g. 'scenes/hud.tscn').
    depth controls how many levels of children to include; default 1 = top-level only.
    Each call is a full load/unload cycle — any previously loaded scene is unloaded first.
    Requires the Godot editor to be open with the project loaded.
    Use this after editing a .tscn file or a script that populates UI in _ready."""
    safe = safe_path(path)
    if safe is None:
        return "Error: path escapes project root"
    result = _bridge.inspect_ui_scene_full(path, depth)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return json.dumps(result["tree"], indent=2)


@mcp.tool()
def start_ui_session(scene_path: str = "", timeout: int = 15) -> str:
    """Launch the Godot game with the --mcp flag and wait for the RemoteControl autoload
    to connect on localhost:6790. If scene_path is given (relative to project root),
    the game navigates to that scene after connecting.
    Returns confirmation when the session is ready.
    The Godot editor does NOT need to be open for this tool."""
    if scene_path:
        safe = safe_path(scene_path)
        if safe is None:
            return "Error: path escapes project root"
    result = _bridge.start_session(godot_bin(), godot_project(), scene_path, timeout)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "Session ready — call get_live_ui, navigate_ui, or screenshot_ui."


@mcp.tool()
def end_ui_session() -> str:
    """Send quit to the running game and close the RemoteControl connection.
    Safe to call even if no session is active."""
    _bridge.end_session()
    return "ok"


@mcp.tool()
def navigate_ui(action: str, params: dict | None = None) -> str:
    """Send a navigation or input command to the active UI session.
    Requires an active session started by start_ui_session.

    action values:
      'change_scene' — params: {"path": "scenes/gameplay.tscn"}
      'press_button' — params: {"node_path": "MainMenu/StartButton"}
      'input_action' — params: {"action": "ui_accept"}
    """
    if params is None:
        params = {}
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    if action == "change_scene":
        result = _bridge.send_session_command("change_scene", path=params.get("path", ""))
    else:
        result = _bridge.send_session_command("send_input", action=action, params=params)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"


@mcp.tool()
def get_live_ui(depth: int = 1) -> str:
    """Return the current UI node tree from the active game session as JSON.
    depth controls how many levels of children to include; default 1 = top-level only.
    Requires an active session started by start_ui_session.
    Call this after navigate_ui to verify the UI changed as expected."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command("get_ui", depth=depth)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return json.dumps(result["tree"], indent=2)


@mcp.tool()
def screenshot_ui(save_path: str = "") -> str:
    """Capture the current viewport as a PNG and return the absolute path to the saved file.
    If save_path is empty, saves to tests/ui_screenshots/<timestamp>.png in the project root.
    Uses the active game session if running; otherwise captures from the editor plugin's SubViewport.
    Call inspect_ui_scene or start_ui_session first."""
    if save_path:
        safe = safe_path(save_path)
        if safe is None:
            return "Error: path escapes project root"
    result = _bridge.screenshot(save_path, godot_project())
    if not result["ok"]:
        return f"Error: {result['error']}"
    return result["path"]


if __name__ == "__main__":
    mcp.run()
