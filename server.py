import json
import os
import shutil
import socket
import subprocess
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
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(Path(project_path) / "tests" / "ui_screenshots" / f"{ts}.png")


_bridge = EditorBridge()


# ── Tools (stubs — filled in subsequent tasks) ─────────────────────────────────

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
    """Launch the Godot game with --mcp flag and open a RemoteControl session.
    Stub — implemented in Task 4."""
    raise NotImplementedError("start_ui_session not yet implemented")


@mcp.tool()
def end_ui_session() -> str:
    """End the active UI session and quit the game.
    Stub — implemented in Task 4."""
    raise NotImplementedError("end_ui_session not yet implemented")


@mcp.tool()
def navigate_ui(action: str, params: dict | None = None) -> str:
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
