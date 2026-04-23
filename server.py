import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tempfile import gettempdir
from typing import Any

from fastmcp import FastMCP
from PIL import Image

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

SCAFFOLD_VERSION = "1.1"
ADDON_PROTOCOL_VERSION = "1.2"

_SCAFFOLD_FILES = [
    "tests/base_test.gd",
    "tests/test_runner.gd",
    "tests/smoke/smoke_runner.gd",
]


def _addon_file_outdated(path: Path, fname: str) -> bool:
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8")
    if fname == "remote_control.gd":
        return f'PROTOCOL_VERSION := "{ADDON_PROTOCOL_VERSION}"' not in content
    if fname == "mcp_tree.gd":
        return "script_path" not in content or "property_errors" not in content
    return False


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
    for fname in ("plugin.cfg", "plugin.gd", "remote_control.gd", "mcp_tree.gd"):
        src = addon_src / fname
        dst = addon_dst / fname
        if src.exists() and (not dst.exists() or _addon_file_outdated(dst, fname)):
            shutil.copy(src, dst)
            created.append(f"addons/godot_mcp/{fname}")

    # Create screenshots directory
    screenshots_dir = Path(project) / "tests" / "ui_screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    gitkeep = screenshots_dir / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()
        created.append("tests/ui_screenshots/.gitkeep")
    diffs_dir = screenshots_dir / "diffs"
    diffs_dir.mkdir(parents=True, exist_ok=True)
    diffs_gitignore = diffs_dir / ".gitignore"
    if not diffs_gitignore.exists():
        diffs_gitignore.write_text("*\n!.gitignore\n", encoding="utf-8")
        created.append("tests/ui_screenshots/diffs/.gitignore")

    # Register RemoteControl autoload and enable EditorPlugin
    if project_godot.exists():
        content = project_godot.read_text(encoding="utf-8")
        if "GodotMCPRemoteControl" not in content:
            autoload_line = 'GodotMCPRemoteControl="*res://addons/godot_mcp/remote_control.gd"'
            if "[autoload]" in content:
                content = content.replace("[autoload]", f"[autoload]\n{autoload_line}", 1)
            else:
                content += f"\n[autoload]\n{autoload_line}\n"
            created.append("project.godot (GodotMCPRemoteControl autoload)")

        plugin_cfg = "res://addons/godot_mcp/plugin.cfg"
        if plugin_cfg not in content:
            if "[editor_plugins]" in content:
                # Append to existing PackedStringArray
                import re
                def _add_plugin(m: re.Match) -> str:
                    arr = m.group(0)
                    if plugin_cfg in arr:
                        return arr
                    return arr.replace('PackedStringArray(', f'PackedStringArray("{plugin_cfg}", ')
                content = re.sub(r'enabled=PackedStringArray\([^)]*\)', _add_plugin, content)
            else:
                content += f'\n[editor_plugins]\n\nenabled=PackedStringArray("{plugin_cfg}")\n'
            created.append("project.godot (godot_mcp plugin enabled)")

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

    # Check UI verification addon files
    addon_files = [
        Path(project) / "addons" / "godot_mcp" / "plugin.cfg",
        Path(project) / "addons" / "godot_mcp" / "plugin.gd",
        Path(project) / "addons" / "godot_mcp" / "remote_control.gd",
        Path(project) / "addons" / "godot_mcp" / "mcp_tree.gd",
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

    remote_control = Path(project) / "addons" / "godot_mcp" / "remote_control.gd"
    mcp_tree = Path(project) / "addons" / "godot_mcp" / "mcp_tree.gd"
    outdated_addons: list[str] = []
    if _addon_file_outdated(remote_control, "remote_control.gd"):
        outdated_addons.append("addons/godot_mcp/remote_control.gd")
    if _addon_file_outdated(mcp_tree, "mcp_tree.gd"):
        outdated_addons.append("addons/godot_mcp/mcp_tree.gd")
    if outdated_addons:
        return (
            f"Status: outdated\nExpected addon protocol: {ADDON_PROTOCOL_VERSION}\n"
            + "Outdated files:\n"
            + "\n".join(f"  {f}" for f in outdated_addons)
        )

    return f"Status: ok\nVersion: {SCAFFOLD_VERSION}"


@dataclass
class _LaunchObservation:
    command: list[str]
    fallback_attempted: bool = False
    safe_log_path: str | None = None
    exited: bool = False
    exit_code: int | None = None
    port_opened: bool = False
    handshake_ok: bool = False
    stdout_lines: deque[str] = field(default_factory=lambda: deque(maxlen=80))
    evidence_lines: list[str] = field(default_factory=list)
    classification: str | None = None
    summary: str | None = None

    def relevant_lines(self) -> list[str]:
        if self.evidence_lines:
            return self.evidence_lines[-10:]
        return list(self.stdout_lines)[-10:]


class _ProcessCapture:
    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self._proc = proc
        self._lines: deque[str] = deque(maxlen=200)
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def _drain(self) -> None:
        stream = self._proc.stdout
        if stream is None:
            return
        for line in stream:
            clean = line.rstrip()
            if not clean:
                continue
            with self._lock:
                self._lines.append(clean)

    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self._lines)


# ── EditorBridge ──────────────────────────────────────────────────────────────

class EditorBridge:
    """Manages TCP connections to the Godot EditorPlugin (:6789) and
    the in-game RemoteControl autoload (:6790)."""

    EDITOR_PORT: int = 6789
    REMOTE_PORT: int = 6790
    CONNECT_TIMEOUT: float = 2.0
    HANDSHAKE_TIMEOUT: float = 2.0
    EARLY_HEALTH_WINDOW: float = 3.0
    LOG_FAILURE_PATTERNS: tuple[str, ...] = (
        "Failed to open 'user://logs/",
        "RotatedFileLogger::rotate_file()",
    )
    TEST_EXIT_PATTERNS: tuple[str, ...] = (
        "PASS:",
        "FAIL:",
        "Test Summary",
        "All tests passed",
    )
    PROJECT_FAILURE_PATTERNS: tuple[str, ...] = (
        "SCRIPT ERROR:",
        "GDScript backtrace",
        "Parser Error:",
        "Parse Error:",
    )
    REQUIRED_REMOTE_COMMANDS: tuple[str, ...] = (
        "ping",
        "get_ui",
        "get_tree_paused",
        "set_tree_paused",
        "set_engine_time_scale",
        "quit",
    )

    def __init__(self) -> None:
        self._session_conn: socket.socket | None = None
        self._session_proc: subprocess.Popen | None = None
        self._last_launch_result: dict | None = None

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
        self,
        godot_bin: str,
        project_path: str,
        scene_path: str,
        timeout: int,
        launch_mode: str = "ui",
    ) -> dict:
        """Launch a Godot runtime session and verify the remote-control handshake."""
        self.end_session()

        args = self._build_launch_command(godot_bin, project_path, scene_path, launch_mode)
        result = self._launch_once(args, timeout, fallback_attempted=False)
        if self._should_retry_with_safe_log(result):
            fallback_args = self._build_launch_command(
                godot_bin,
                project_path,
                scene_path,
                launch_mode,
                safe_log_path=self._safe_log_file_path(project_path),
            )
            result = self._launch_once(fallback_args, timeout, fallback_attempted=True)
            if result["status"] == "ready":
                result["status"] = "launch_recovered_with_fallback"
        return result

    def send_session_command(
        self, cmd: str, socket_timeout: float | None = None, **params
    ) -> dict:
        """Send a command to the active game session."""
        if self._session_conn is None:
            return {
                "ok": False,
                "error": "no active UI session — call start_ui_session first",
            }
        try:
            if socket_timeout is not None:
                self._session_conn.settimeout(socket_timeout)
            return self._transact(self._session_conn, cmd, params)
        except OSError:
            self._session_conn = None
            return {
                "ok": False,
                "error": "session disconnected — call start_ui_session to reconnect",
            }
        finally:
            if socket_timeout is not None:
                try:
                    if self._session_conn is not None:
                        self._session_conn.settimeout(self.CONNECT_TIMEOUT)
                except OSError:
                    pass

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

    def _build_launch_command(
        self,
        godot_bin: str,
        project_path: str,
        scene_path: str,
        launch_mode: str,
        safe_log_path: str | None = None,
    ) -> list[str]:
        args = [godot_bin, "--path", project_path]
        if launch_mode in {"headless-mcp", "headless-tests"}:
            args.append("--headless")
        if safe_log_path:
            args += ["--log-file", safe_log_path]
        if launch_mode in {"ui", "headless-mcp"}:
            args += ["--", "--mcp"]
            if scene_path:
                args += ["--mcp-scene", scene_path]
        return args

    def _launch_once(self, args: list[str], timeout: int, fallback_attempted: bool) -> dict:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        capture = _ProcessCapture(proc)
        observation = _LaunchObservation(command=list(args), fallback_attempted=fallback_attempted)
        safe_log_path = self._extract_log_file_arg(args)
        if safe_log_path:
            observation.safe_log_path = safe_log_path

        deadline = time.monotonic() + timeout
        early_deadline = min(deadline, time.monotonic() + self.EARLY_HEALTH_WINDOW)
        while time.monotonic() < deadline:
            self._update_observation(proc, capture, observation)
            if observation.exited:
                self._close_session_connection()
                self._session_proc = None
                return self._finalize_failed_launch(observation)

            handshake = self._attempt_handshake(proc)
            if handshake.get("port_opened"):
                observation.port_opened = True
            self._update_observation(proc, capture, observation)
            if handshake["ok"]:
                observation.handshake_ok = True
                self._session_proc = proc
                return self._finalize_ready_launch(observation)
            self._close_session_connection()
            if not handshake.get("retryable", False):
                observation.classification = "project_incompatible"
                observation.summary = handshake["error"]
                observation.evidence_lines = [handshake["error"]]
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
                self._session_proc = None
                return self._finalize_failed_launch(observation, status="launch_failed_project")

            if time.monotonic() < early_deadline:
                time.sleep(0.1)
            else:
                time.sleep(0.2)

        self._update_observation(proc, capture, observation)
        self._close_session_connection()
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
        self._session_proc = None
        return self._finalize_failed_launch(
            observation,
            status="launch_failed_timeout",
            summary=f"remote control did not become ready within {timeout}s",
            classification="timeout",
        )

    def _attempt_handshake(self, proc: subprocess.Popen[str]) -> dict:
        try:
            conn = socket.create_connection(
                ("localhost", self.REMOTE_PORT), timeout=self.HANDSHAKE_TIMEOUT
            )
        except (ConnectionRefusedError, OSError) as exc:
            return {
                "ok": False,
                "retryable": True,
                "port_opened": False,
                "error": f"remote control not reachable yet: {exc}",
            }

        self._session_conn = conn
        try:
            result = self._transact(conn, "ping", {})
        except OSError as exc:
            return {
                "ok": False,
                "retryable": True,
                "port_opened": True,
                "error": f"remote control disconnected during ping: {exc}",
            }

        if not result.get("ok", False):
            return {
                "ok": False,
                "retryable": False,
                "port_opened": True,
                "error": str(result.get("error", "ping failed")),
            }

        advertised = result.get("commands")
        if isinstance(advertised, list):
            missing = [cmd for cmd in self.REQUIRED_REMOTE_COMMANDS if cmd not in advertised]
            if missing:
                return {
                    "ok": False,
                    "retryable": False,
                    "port_opened": True,
                    "error": f"remote control missing required commands: {', '.join(missing)}",
                }

        if proc.poll() is not None:
            return {
                "ok": False,
                "retryable": True,
                "port_opened": True,
                "error": "process exited before handshake completed",
            }
        return {"ok": True, "port_opened": True, "ping": result}

    def _update_observation(
        self,
        proc: subprocess.Popen[str],
        capture: _ProcessCapture,
        observation: _LaunchObservation,
    ) -> None:
        lines = capture.snapshot()
        observation.stdout_lines = deque(lines[-80:], maxlen=80)
        observation.exit_code = proc.poll()
        observation.exited = observation.exit_code is not None
        if observation.classification is None:
            classification = self._classify_output(lines, observation.port_opened)
            if classification:
                observation.classification = classification["classification"]
                observation.summary = classification["summary"]
                observation.evidence_lines = classification["evidence_lines"]

    def _classify_output(self, lines: list[str], port_opened: bool) -> dict | None:
        if not lines:
            return None
        engine_hits = [line for line in lines if any(pat in line for pat in self.LOG_FAILURE_PATTERNS)]
        if engine_hits:
            return {
                "classification": "engine_startup_failure",
                "summary": "Godot failed during engine startup before project autoloads became ready.",
                "evidence_lines": engine_hits[-3:],
            }
        project_hits = [line for line in lines if any(pat in line for pat in self.PROJECT_FAILURE_PATTERNS)]
        if project_hits:
            return {
                "classification": "project_script_failure",
                "summary": "Project startup emitted script errors before the MCP handshake completed.",
                "evidence_lines": project_hits[-3:],
            }
        test_hits = [line for line in lines if any(pat in line for pat in self.TEST_EXIT_PATTERNS)]
        if test_hits and not port_opened:
            return {
                "classification": "test_runner_exit",
                "summary": "Headless launch appears to have run tests and exited before MCP became available.",
                "evidence_lines": test_hits[-5:],
            }
        return None

    def _should_retry_with_safe_log(self, result: dict) -> bool:
        if result.get("status") != "launch_failed_engine":
            return False
        if result.get("fallback_attempted"):
            return False
        joined = "\n".join(result.get("evidence_lines", []) + result.get("last_output_lines", []))
        return any(pattern in joined for pattern in self.LOG_FAILURE_PATTERNS)

    def _finalize_ready_launch(self, observation: _LaunchObservation) -> dict:
        result = {
            "ok": True,
            "status": "ready",
            "command": observation.command,
            "process_exited": False,
            "exit_code": None,
            "port_opened": True,
            "fallback_attempted": observation.fallback_attempted,
            "safe_log_path": observation.safe_log_path,
        }
        self._last_launch_result = result
        return result

    def _finalize_failed_launch(
        self,
        observation: _LaunchObservation,
        status: str | None = None,
        summary: str | None = None,
        classification: str | None = None,
    ) -> dict:
        effective_classification = classification or observation.classification
        effective_summary = summary or observation.summary or "Godot session startup failed."
        effective_status = status or self._status_for_classification(effective_classification)
        result = {
            "ok": False,
            "status": effective_status,
            "command": observation.command,
            "process_exited": observation.exited,
            "exit_code": observation.exit_code,
            "port_opened": observation.port_opened,
            "fallback_attempted": observation.fallback_attempted,
            "safe_log_path": observation.safe_log_path,
            "classification": effective_classification,
            "summary": effective_summary,
            "evidence_lines": observation.evidence_lines,
            "last_output_lines": observation.relevant_lines(),
        }
        self._last_launch_result = result
        return result

    def _status_for_classification(self, classification: str | None) -> str:
        if classification == "engine_startup_failure":
            return "launch_failed_engine"
        if classification == "project_script_failure" or classification == "project_incompatible":
            return "launch_failed_project"
        if classification == "test_runner_exit":
            return "launch_failed_autoload_exit"
        return "launch_failed_timeout"

    def _safe_log_file_path(self, project_path: str) -> str:
        project_slug = Path(project_path).name.replace(" ", "-")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        directory = Path(gettempdir()) / "godot-mcp" / project_slug
        directory.mkdir(parents=True, exist_ok=True)
        return str(directory / f"{stamp}.log")

    def _extract_log_file_arg(self, args: list[str]) -> str | None:
        if "--log-file" not in args:
            return None
        idx = args.index("--log-file")
        if idx + 1 >= len(args):
            return None
        return args[idx + 1]

    def _close_session_connection(self) -> None:
        if self._session_conn is None:
            return
        try:
            self._session_conn.close()
        except OSError:
            pass
        self._session_conn = None

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
_last_screenshot_path: Path | None = None


def _is_valid_baseline_name(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", name))


def _baseline_path(baseline_name: str) -> Path | None:
    if not _is_valid_baseline_name(baseline_name):
        return None
    safe = safe_path(f"tests/ui_screenshots/{baseline_name}.png")
    return safe


def _diff_image_path(baseline_name: str) -> Path | None:
    if not _is_valid_baseline_name(baseline_name):
        return None
    safe = safe_path(f"tests/ui_screenshots/diffs/{baseline_name}_diff.png")
    return safe


def _port_accepting(port: int, timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection(("localhost", port), timeout=timeout):
            return True
    except OSError:
        return False


def _scaffold_status_from_check(result: str) -> str:
    first_line = result.splitlines()[0] if result else ""
    if first_line.startswith("Status: "):
        return first_line.removeprefix("Status: ").strip()
    if "already up to date" in result.lower():
        return "ok"
    return "unknown"


def _project_preflight() -> dict[str, Any]:
    project_path = godot_project()
    godot_path = godot_bin()
    project_root = Path(project_path)
    godot_binary = Path(godot_path)
    project_exists = project_root.exists()
    project_godot_exists = (project_root / "project.godot").exists()
    godot_bin_exists = godot_binary.exists()
    warnings: list[str] = []

    if not project_exists:
        warnings.append("project path does not exist")
    if not project_godot_exists:
        warnings.append("project.godot not found")
    if not godot_bin_exists:
        warnings.append("GODOT_BIN does not point to an existing file")

    scaffold_status = "unknown"
    if project_exists:
        try:
            scaffold_status = _scaffold_status_from_check(check_scaffold())
        except Exception as exc:
            scaffold_status = "error"
            warnings.append(f"could not check scaffold: {exc}")

    editor_bridge_available = _port_accepting(EditorBridge.EDITOR_PORT)
    remote_port_busy = _port_accepting(EditorBridge.REMOTE_PORT)
    if remote_port_busy:
        warnings.append(
            f"remote control port {EditorBridge.REMOTE_PORT} is already accepting connections"
        )

    if not project_exists or not project_godot_exists or not godot_bin_exists:
        recommended_path = "fix_environment"
    elif scaffold_status != "ok":
        recommended_path = "scaffold_tests"
    elif editor_bridge_available:
        recommended_path = "editor_bridge_or_runtime_session"
    else:
        recommended_path = "runtime_session"

    return {
        "project_path": project_path,
        "project_exists": project_exists,
        "project_godot_exists": project_godot_exists,
        "godot_bin": godot_path,
        "godot_bin_exists": godot_bin_exists,
        "scaffold_status": scaffold_status,
        "editor_bridge_available": editor_bridge_available,
        "remote_port_busy": remote_port_busy,
        "recommended_path": recommended_path,
        "warnings": warnings,
    }


def _load_ui_critical_scripts(project_path: str) -> tuple[dict[str, str], list[str]]:
    metadata_path = Path(project_path) / ".Codex" / "ui_critical_scripts.json"
    if not metadata_path.exists():
        return {}, ["ui critical metadata not found"]
    try:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, [f"could not parse ui critical metadata: {exc}"]
    scripts = raw.get("scripts", {})
    if not isinstance(scripts, dict):
        return {}, ["ui critical metadata has no scripts object"]
    return {str(path): str(reason) for path, reason in scripts.items()}, []


def _changed_files_from_git(project_path: str) -> tuple[list[str], list[str]]:
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        capture_output=True,
        text=True,
        cwd=project_path,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "unknown error").strip()
        return [], [f"could not inspect git diff: {message}"]
    return [line.strip() for line in result.stdout.splitlines() if line.strip()], []


def _baseline_hint_for_path(path: str) -> str | None:
    stem = Path(path).stem
    if not stem:
        return None
    return re.sub(r"[^A-Za-z0-9_-]+", "_", stem)


def _verification_item(path: str, ui_critical: dict[str, str]) -> dict[str, Any]:
    reason = ui_critical.get(path, "")
    tools: list[str] = []
    visual_required = False

    if path in ui_critical:
        visual_required = True
        tools.extend(["capture_scene", "compare_ui_screenshot"])
    elif path.endswith(".tscn"):
        visual_required = True
        tools.extend(["inspect_ui_scene", "capture_scene"])
        reason = "scene file changes affect rendered structure or runtime scene composition"
    elif path.startswith("tests/") and path.endswith(".gd"):
        tools.append("targeted_godot_tests")
        reason = "test file changes should be validated with the affected Godot test suite"
    else:
        tools.append("targeted_godot_tests")
        reason = "not listed as UI-critical; start with focused tests or state inspection"

    item: dict[str, Any] = {
        "path": path,
        "visual_validation_required": visual_required,
        "recommended_tools": tools,
        "reason": reason,
    }
    baseline_hint = _baseline_hint_for_path(path)
    if visual_required and baseline_hint:
        item["baseline_hint"] = baseline_hint
    return item


def _pixel_diff(
    baseline_path: Path, current_path: Path, diff_path: Path, threshold: float
) -> dict[str, Any]:
    baseline_image = Image.open(baseline_path).convert("RGBA")
    current_image = Image.open(current_path).convert("RGBA")

    if baseline_image.size != current_image.size:
        return {
            "error": "size_mismatch",
            "baseline_size": list(baseline_image.size),
            "current_size": list(current_image.size),
        }

    width, height = baseline_image.size
    total_pixels = width * height
    changed_pixels = 0
    diff_image = Image.new("RGB", baseline_image.size, (0, 0, 0))

    baseline_pixels = baseline_image.load()
    current_pixels = current_image.load()
    diff_pixels = diff_image.load()
    for y in range(height):
        for x in range(width):
            changed = baseline_pixels[x, y] != current_pixels[x, y]
            if changed:
                changed_pixels += 1
                diff_pixels[x, y] = (255, 0, 200)

    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_image.save(diff_path)

    diff_ratio = changed_pixels / total_pixels if total_pixels else 0.0
    return {
        "passed": diff_ratio <= threshold,
        "diff_ratio": diff_ratio,
        "changed_pixels": changed_pixels,
        "total_pixels": total_pixels,
    }


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def preflight_project() -> str:
    """Return project, scaffold, editor bridge, and runtime port diagnostics as JSON.
    This tool never launches Godot; use it before choosing editor inspection, runtime
    capture, or scaffold installation."""
    return json.dumps(_project_preflight(), indent=2)


@mcp.tool()
def capture_scene(
    scene_path: str,
    save_path: str = "",
    settle_frames: int = 3,
    timeout: int = 15,
    headless: bool = False,
) -> str:
    """Launch a short runtime MCP session, settle frames, capture a screenshot, and quit.
    Defaults to normal UI mode because some projects auto-run tests and exit in headless mode."""
    if safe_path(scene_path) is None:
        return "Error: path escapes project root"
    if save_path and safe_path(save_path) is None:
        return "Error: path escapes project root"

    launch_mode = "headless-mcp" if headless else "ui"
    launch = _bridge.start_session(
        godot_bin(),
        godot_project(),
        scene_path,
        timeout,
        launch_mode=launch_mode,
    )
    if not launch.get("ok", False):
        return json.dumps(
            {
                "error": "launch_failed",
                "status": launch.get("status", "launch_failed"),
                "scene_path": scene_path,
                "launch": launch,
            },
            indent=2,
        )

    try:
        frames = max(0, int(settle_frames))
        if frames:
            socket_timeout = max(frames / 60.0 + 5.0, 10.0)
            settled = _bridge.send_session_command(
                "await_frames", socket_timeout=socket_timeout, n=frames
            )
            if not settled.get("ok", False):
                return json.dumps(
                    {
                        "error": "settle_failed",
                        "status": "settle_failed",
                        "scene_path": scene_path,
                        "message": str(settled.get("error", "unknown settle error")),
                        "launch": launch,
                    },
                    indent=2,
                )

        screenshot = _bridge.screenshot(save_path, godot_project())
        if not screenshot.get("ok", False):
            return json.dumps(
                {
                    "error": "screenshot_failed",
                    "status": "screenshot_failed",
                    "scene_path": scene_path,
                    "message": str(screenshot.get("error", "unknown screenshot error")),
                    "launch": launch,
                },
                indent=2,
            )

        return json.dumps(
            {
                "status": "captured",
                "scene_path": scene_path,
                "screenshot_path": screenshot.get("path"),
                "viewport_size": screenshot.get("viewport_size"),
                "scene": screenshot.get("scene"),
                "frame": screenshot.get("frame"),
                "launch": launch,
                "warnings": [],
            },
            indent=2,
        )
    finally:
        _bridge.end_session()


@mcp.tool()
def plan_verification(changed_files: list[str] | None = None) -> str:
    """Recommend verification steps for changed project files.
    Uses optional .Codex/ui_critical_scripts.json metadata when present."""
    project_path = godot_project()
    warnings: list[str] = []
    ui_critical, metadata_warnings = _load_ui_critical_scripts(project_path)
    warnings.extend(metadata_warnings)

    files = changed_files
    if files is None:
        files, git_warnings = _changed_files_from_git(project_path)
        warnings.extend(git_warnings)

    result = {
        "project_path": project_path,
        "warnings": warnings,
        "recommended_sequence": [
            "preflight_project",
            "targeted_godot_tests",
            "inspect_ui_scene_or_capture_scene",
            "compare_ui_screenshot_if_baseline_exists",
        ],
        "files": [_verification_item(path, ui_critical) for path in files],
    }
    return json.dumps(result, indent=2)


@mcp.tool()
def get_session_status() -> str:
    """Return active runtime-session state and the most recent launch result."""
    proc = _bridge._session_proc
    process_running = bool(proc is not None and proc.poll() is None)
    return json.dumps(
        {
            "session_active": _bridge._session_conn is not None,
            "process_running": process_running,
            "last_launch": _bridge._last_launch_result,
        },
        indent=2,
    )

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
def start_ui_session(scene_path: str = "", timeout: int = 15, headless: bool = False) -> str:
    """Launch the Godot game with the --mcp flag and wait for the RemoteControl autoload
    to become responsive on localhost:6790. If scene_path is given (relative to the
    project root), the game navigates to that scene after connecting.
    By default this uses a normal UI launch; set headless=true for headless runtime control.
    Returns structured startup metadata including status and failure classification.
    The Godot editor does NOT need to be open for this tool."""
    if scene_path:
        safe = safe_path(scene_path)
        if safe is None:
            return "Error: path escapes project root"
    launch_mode = "headless-mcp" if headless else "ui"
    started_at = time.monotonic()
    result = _bridge.start_session(
        godot_bin(),
        godot_project(),
        scene_path,
        timeout,
        launch_mode=launch_mode,
    )
    result["elapsed_seconds"] = round(time.monotonic() - started_at, 3)
    return json.dumps(result, indent=2)


@mcp.tool()
def end_ui_session() -> str:
    """Send quit to the running game and close the RemoteControl connection.
    Safe to call even if no session is active."""
    _bridge.end_session()
    return "ok"


@mcp.tool()
def navigate_ui(action: str, params: dict | None = None) -> str:
    """Send a navigation or input command to the active UI session.
    Prefer send_key, click, and drag for new code, they are more direct.
    navigate_ui remains available for change_scene, press_button, and input_action.
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
    For targeted inspection of a specific node, use get_node instead.
    To find nodes by name or type, use find_nodes.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command("get_ui", depth=depth)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return json.dumps(result["tree"], indent=2)


@mcp.tool()
def screenshot_ui(save_path: str = "") -> str:
    """Capture the current viewport as a PNG and return JSON with path and metadata.
    Metadata fields: path (absolute), viewport_size [w, h], scene (current scene file path),
    frame (process frame count; 0 for editor captures).
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
    return json.dumps({k: v for k, v in result.items() if k != "ok"})


@mcp.tool()
def compare_ui_screenshot(baseline_name: str, threshold: float = 0.02) -> str:
    """Capture the current viewport and compare it against a named baseline PNG.
    baseline_name resolves to tests/ui_screenshots/<name>.png inside the Godot project.
    threshold is the maximum acceptable changed-pixel ratio; default 0.02 = 2%.
    Always writes a diff image to tests/ui_screenshots/diffs/<name>_diff.png when sizes match.
    Returns structured JSON for pass/fail, missing baselines, screenshot failures, or size mismatch."""
    global _last_screenshot_path

    baseline_path = _baseline_path(baseline_name)
    diff_path = _diff_image_path(baseline_name)
    if baseline_path is None or diff_path is None:
        return json.dumps({"error": "invalid_baseline_name", "baseline_name": baseline_name})

    screenshot = _bridge.screenshot("", godot_project())
    if not screenshot.get("ok", False):
        return json.dumps(
            {
                "error": "screenshot_failed",
                "baseline_name": baseline_name,
                "message": str(screenshot.get("error", "unknown screenshot error")),
            }
        )

    _last_screenshot_path = Path(str(screenshot["path"])).resolve()
    if not baseline_path.exists():
        return json.dumps(
            {
                "error": "baseline_not_found",
                "baseline_name": baseline_name,
                "baseline_path": str(baseline_path),
                "current_path": str(_last_screenshot_path),
            }
        )

    result = _pixel_diff(baseline_path, _last_screenshot_path, diff_path, threshold)
    result.update(
        {
            "baseline_name": baseline_name,
            "baseline_path": str(baseline_path),
            "current_path": str(_last_screenshot_path),
            "diff_image_path": str(diff_path),
            "threshold": threshold,
        }
    )
    return json.dumps(result, indent=2)


@mcp.tool()
def update_baseline(baseline_name: str) -> str:
    """Promote the most recent compare_ui_screenshot capture to a named baseline PNG.
    Copies the cached screenshot to tests/ui_screenshots/<name>.png and stages it with git add.
    Returns structured JSON for success or failure; this tool never commits changes."""
    baseline_path = _baseline_path(baseline_name)
    if baseline_path is None:
        return json.dumps({"error": "invalid_baseline_name", "baseline_name": baseline_name})

    if _last_screenshot_path is None:
        return json.dumps({"error": "no_recent_screenshot", "baseline_name": baseline_name})
    if not _last_screenshot_path.exists():
        return json.dumps(
            {
                "error": "recent_screenshot_missing",
                "baseline_name": baseline_name,
                "current_path": str(_last_screenshot_path),
            }
        )

    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_last_screenshot_path, baseline_path)

    git_add = subprocess.run(
        ["git", "add", str(baseline_path)],
        capture_output=True,
        text=True,
        cwd=godot_project(),
    )
    if git_add.returncode != 0:
        return json.dumps(
            {
                "error": "git_add_failed",
                "baseline_name": baseline_name,
                "path": str(baseline_path),
                "message": (git_add.stderr or git_add.stdout).strip(),
            }
        )

    return json.dumps({"updated": True, "path": str(baseline_path)}, indent=2)


@mcp.tool()
def send_key(
    key: str,
    pressed: bool = True,
    shift: bool = False,
    ctrl: bool = False,
    alt: bool = False,
    echo: bool = False,
) -> str:
    """Send a keyboard event to the active game session.
    key is a Godot key name (e.g. 'Right', 'Left', 'Space', 'A', 'Escape').
    pressed controls key-down (True) vs key-up (False); default is True.
    shift, ctrl, alt are modifier keys. echo is for held-key repeat events.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command(
        "send_key", key=key, pressed=pressed, shift=shift, ctrl=ctrl, alt=alt, echo=echo
    )
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"


@mcp.tool()
def send_mouse(x: float, y: float) -> str:
    """Move the mouse cursor to viewport coordinates (x, y) in the active game session.
    Coordinates are pixels from the top-left of the viewport.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command("send_mouse_move", x=x, y=y)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"


@mcp.tool()
def click(x: float, y: float, button: int = 1) -> str:
    """Click at viewport coordinates (x, y) in the active game session.
    button: 1=left (default), 2=right, 3=middle.
    Sends mouse_move, button_down, button_up as one atomic operation.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command("click", x=x, y=y, button=button)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"


@mcp.tool()
def drag(
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
    button: int = 1,
    steps: int = 5,
) -> str:
    """Drag from (from_x, from_y) to (to_x, to_y) in the active game session.
    button: 1=left (default), 2=right, 3=middle.
    steps controls intermediate mouse move events for the drag path (default 5).
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command(
        "drag", from_x=from_x, from_y=from_y, to_x=to_x, to_y=to_y, button=button, steps=steps
    )
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"


@mcp.tool()
def get_node(node_path: str, properties: list[str] | None = None) -> str:
    """Return data for a single node from the active game session.
    node_path is relative to the current scene root (e.g. 'Player', 'HUD/HealthBar').
    properties: optional list of extra property names to include (e.g. ['health', 'speed']).
    Returns JSON with standard fields plus requested extras.
    Use get_live_ui for the full scene tree; use get_node when you know the exact node.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    params: dict[str, Any] = {"node_path": node_path}
    if properties:
        params["properties"] = properties
    result = _bridge.send_session_command("get_node", **params)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return json.dumps(result["node"], indent=2)


@mcp.tool()
def find_nodes(name: str = "", type: str = "", contains: bool = False) -> str:
    """Search the current scene for nodes matching name and/or type.
    name: exact match on node.name. Omit to skip name filter.
    contains: when true, name is matched as a substring instead of an exact match.
    type: exact match on node class string. Omit to skip type filter.
    Returns JSON array of {path, type} for all matching nodes.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    params: dict[str, str | bool] = {}
    if name:
        params["name"] = name
    if type:
        params["type"] = type
    if contains:
        params["contains"] = True
    result = _bridge.send_session_command("find_nodes", **params)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return json.dumps(result["nodes"], indent=2)


@mcp.tool()
def get_node_snapshot(
    node_path: str,
    properties: list[str] | None = None,
    include_children: bool = False,
    depth: int = 1,
) -> str:
    """Return targeted node data with optional properties and child tree context."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command(
        "get_node_snapshot",
        node_path=node_path,
        properties=properties or [],
        include_children=include_children,
        depth=depth,
    )
    if not result["ok"]:
        return f"Error: {result['error']}"
    return json.dumps(result["node"], indent=2)


@mcp.tool()
def await_frames(n: int) -> str:
    """Wait for n game frames to pass in the active session before returning.
    Use after send_key, click, or drag to let the game process input before inspecting state.
    Blocks until Godot confirms n frames have elapsed.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    socket_timeout = max(n / 60.0 + 5.0, 10.0)
    result = _bridge.send_session_command(
        "await_frames", socket_timeout=socket_timeout, n=n
    )
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"


@mcp.tool()
def set_tree_paused(paused: bool) -> str:
    """Pause or unpause the active game session's SceneTree.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command("set_tree_paused", paused=paused)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"


@mcp.tool()
def get_tree_paused() -> str:
    """Return the active game session's paused state as JSON.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command("get_tree_paused")
    if not result["ok"]:
        return f"Error: {result['error']}"
    return json.dumps({"paused": result["paused"]}, indent=2)


@mcp.tool()
def set_engine_time_scale(scale: float) -> str:
    """Set Engine.time_scale for the active game session.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command("set_engine_time_scale", scale=scale)
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"


@mcp.tool()
def step_frames(n: int) -> str:
    """Advance the active game session by exactly n process frames, then restore pause state.
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


@mcp.tool()
def await_node_property(
    node_path: str, property: str, value: Any, timeout: float = 5.0
) -> str:
    """Wait until a node's property equals the given value, or until timeout seconds.
    node_path: path from current scene root.
    property: property name to watch.
    value: the expected value to wait for.
    Returns ok when matched; returns error with the actual value on timeout.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command(
        "await_node_property",
        socket_timeout=timeout + 2.0,
        node_path=node_path,
        property=property,
        value=value,
        timeout=timeout,
    )
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"


@mcp.tool()
def await_signal(node_path: str, signal: str, timeout: float = 5.0) -> str:
    """Wait for a signal to be emitted on a node, or until timeout seconds.
    node_path: path from current scene root.
    signal: signal name.
    Works for signals with 0, 1, or 2 arguments; best-effort for 3+ args.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command(
        "await_signal",
        socket_timeout=timeout + 2.0,
        node_path=node_path,
        signal=signal,
        timeout=timeout,
    )
    if not result["ok"]:
        return f"Error: {result['error']}"
    return "ok"


@mcp.tool()
def call_node_method(node_path: str, method: str, args: list | None = None) -> str:
    """Call a method on a node in the active game session and return the result as JSON.
    node_path: path from current scene root.
    method: method name.
    args: optional list of arguments to pass to the method.
    Non-JSON-serializable return values are converted to strings by the runtime.
    Use for debugging and verification, prefer send_key/click for normal gameplay interaction.
    Requires an active session started by start_ui_session."""
    if _bridge._session_conn is None:
        return "Error: no active UI session — call start_ui_session first"
    result = _bridge.send_session_command(
        "call_node_method", node_path=node_path, method=method, args=args or []
    )
    if not result["ok"]:
        return f"Error: {result['error']}"
    return json.dumps(result["result"], indent=2)


if __name__ == "__main__":
    mcp.run()
