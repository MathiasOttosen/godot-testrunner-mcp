# Pixel-Diff Visual Regression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend godot-mcp with `compare_ui_screenshot` and `update_baseline` tools, and author a `pixel-diff` skill that tells agents when and how to use them.

**Architecture:** Two commits. Commit 1 adds `Pillow`, a private `_pixel_diff` helper, and the two MCP tools to `/Users/kognido/game-dev/godot-mcp/server.py`, with pytest tests in `tests/test_pixel_diff.py`. Commit 2 creates the `pixel-diff` skill markdown and registers it. The MCP tracks the most recent screenshot in a module-level variable so `update_baseline` can promote it without taking a second screenshot.

**Tech Stack:** Python 3.12, FastMCP 3.x, Pillow (image comparison), pytest, uv (dependency management). Godot project at `/Users/kognido/game-dev/the_pattern`.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `/Users/kognido/game-dev/godot-mcp/pyproject.toml` | Add `pillow` dependency |
| Modify | `/Users/kognido/game-dev/godot-mcp/server.py` | Add `_last_screenshot_path`, `_pixel_diff`, `compare_ui_screenshot`, `update_baseline` |
| Create | `/Users/kognido/game-dev/godot-mcp/tests/test_pixel_diff.py` | Pytest tests for all new code |
| Create | `tests/ui_screenshots/diffs/.gitignore` | Exclude ephemeral diff images from git |
| Create | `pixel-diff` skill file | Workflow guidance for agents |

---

## Commit 1 — MCP Extension

### Task 1: Write failing tests for `_pixel_diff` helper

The helper is a private function (not an MCP tool) that does the pixel-by-pixel comparison using Pillow. Writing tests first establishes the exact interface and return shape before touching `server.py`.

**Files:**
- Create: `/Users/kognido/game-dev/godot-mcp/tests/test_pixel_diff.py`

- [ ] **Step 1: Create the test file**

```python
# tests/test_pixel_diff.py
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

import server


# ── Helpers ────────────────────────────────────────────────────────────────────

def _solid_png(path: Path, color: tuple, size: tuple = (10, 10)) -> None:
    Image.new("RGB", size, color).save(path)


def _half_changed_png(path_a: Path, path_b: Path, size: tuple = (10, 10)) -> None:
    """Save two PNGs where the top half of b differs from a."""
    img_a = Image.new("RGB", size, (0, 0, 0))
    img_b = Image.new("RGB", size, (0, 0, 0))
    for y in range(size[1] // 2):
        for x in range(size[0]):
            img_b.putpixel((x, y), (255, 255, 255))
    img_a.save(path_a)
    img_b.save(path_b)


# ── _pixel_diff ────────────────────────────────────────────────────────────────

def test_pixel_diff_identical_images(tmp_path):
    a = tmp_path / "a.png"
    diff = tmp_path / "diff.png"
    _solid_png(a, (100, 150, 200))
    result = server._pixel_diff(a, a, diff, threshold=0.02)
    assert result["diff_ratio"] == 0.0
    assert result["passed"] is True
    assert diff.exists()  # diff image always written


def test_pixel_diff_completely_different(tmp_path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    diff = tmp_path / "diff.png"
    _solid_png(a, (0, 0, 0))
    _solid_png(b, (255, 255, 255))
    result = server._pixel_diff(a, b, diff, threshold=0.02)
    assert result["diff_ratio"] == 1.0
    assert result["passed"] is False


def test_pixel_diff_size_mismatch(tmp_path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    diff = tmp_path / "diff.png"
    _solid_png(a, (100, 100, 100), size=(10, 10))
    _solid_png(b, (100, 100, 100), size=(20, 20))
    result = server._pixel_diff(a, b, diff, threshold=0.02)
    assert result["error"] == "size_mismatch"
    assert "new_size" in result
    assert "baseline_size" in result


def test_pixel_diff_threshold_boundary(tmp_path):
    """50% changed pixels: passes at threshold=0.6, fails at threshold=0.4."""
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    diff = tmp_path / "diff.png"
    _half_changed_png(a, b)
    assert server._pixel_diff(a, b, diff, threshold=0.6)["passed"] is True
    assert server._pixel_diff(a, b, diff, threshold=0.4)["passed"] is False


def test_pixel_diff_diff_image_highlights_changes(tmp_path):
    """Changed pixels appear as magenta (255, 0, 200) in the diff image."""
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    diff = tmp_path / "diff.png"
    _solid_png(a, (0, 0, 0))
    _solid_png(b, (255, 255, 255))
    server._pixel_diff(a, b, diff, threshold=0.02)
    diff_img = Image.open(diff).convert("RGB")
    # Every pixel should be magenta
    pixels = list(diff_img.getdata())
    assert all(p == (255, 0, 200) for p in pixels)


# ── compare_ui_screenshot ──────────────────────────────────────────────────────

def test_compare_ui_screenshot_baseline_not_found(tmp_path):
    with patch.dict("os.environ", {"GODOT_PROJECT": str(tmp_path), "GODOT_BIN": "/fake/godot"}):
        raw = server.compare_ui_screenshot("nonexistent")
    result = json.loads(raw)
    assert result["error"] == "baseline_not_found"
    assert result["baseline_name"] == "nonexistent"


def test_compare_ui_screenshot_passes_on_identical(tmp_path):
    baseline_dir = tmp_path / "tests" / "ui_screenshots"
    baseline_dir.mkdir(parents=True)
    baseline = baseline_dir / "test_scene.png"
    _solid_png(baseline, (50, 50, 50))

    # Screenshot that matches the baseline exactly
    screenshot = tmp_path / "tests" / "ui_screenshots" / "snap.png"
    _solid_png(screenshot, (50, 50, 50))

    with patch.dict("os.environ", {"GODOT_PROJECT": str(tmp_path), "GODOT_BIN": "/fake/godot"}):
        with patch.object(server._bridge, "screenshot", return_value={"ok": True, "path": str(screenshot)}):
            result = json.loads(server.compare_ui_screenshot("test_scene", threshold=0.02))

    assert result["passed"] is True
    assert result["diff_ratio"] == 0.0
    assert "diff_image_path" in result
    assert "baseline_path" in result


def test_compare_ui_screenshot_fails_on_different(tmp_path):
    baseline_dir = tmp_path / "tests" / "ui_screenshots"
    baseline_dir.mkdir(parents=True)
    baseline = baseline_dir / "test_scene.png"
    _solid_png(baseline, (0, 0, 0))

    screenshot = tmp_path / "tests" / "ui_screenshots" / "snap.png"
    _solid_png(screenshot, (255, 255, 255))

    with patch.dict("os.environ", {"GODOT_PROJECT": str(tmp_path), "GODOT_BIN": "/fake/godot"}):
        with patch.object(server._bridge, "screenshot", return_value={"ok": True, "path": str(screenshot)}):
            result = json.loads(server.compare_ui_screenshot("test_scene", threshold=0.02))

    assert result["passed"] is False
    assert result["diff_ratio"] == 1.0


def test_compare_ui_screenshot_sets_last_screenshot(tmp_path):
    baseline_dir = tmp_path / "tests" / "ui_screenshots"
    baseline_dir.mkdir(parents=True)
    baseline = baseline_dir / "s.png"
    _solid_png(baseline, (0, 0, 0))
    screenshot = tmp_path / "snap.png"
    _solid_png(screenshot, (0, 0, 0))

    with patch.dict("os.environ", {"GODOT_PROJECT": str(tmp_path), "GODOT_BIN": "/fake/godot"}):
        with patch.object(server._bridge, "screenshot", return_value={"ok": True, "path": str(screenshot)}):
            server.compare_ui_screenshot("s")

    assert server._last_screenshot_path == screenshot


# ── update_baseline ────────────────────────────────────────────────────────────

def test_update_baseline_no_recent_screenshot(tmp_path):
    server._last_screenshot_path = None
    with patch.dict("os.environ", {"GODOT_PROJECT": str(tmp_path), "GODOT_BIN": "/fake/godot"}):
        result = server.update_baseline("t0_room")
    assert result.startswith("Error:")


def test_update_baseline_copies_file(tmp_path):
    baseline_dir = tmp_path / "tests" / "ui_screenshots"
    baseline_dir.mkdir(parents=True)
    screenshot = tmp_path / "snap.png"
    _solid_png(screenshot, (10, 20, 30))
    server._last_screenshot_path = screenshot

    with patch.dict("os.environ", {"GODOT_PROJECT": str(tmp_path), "GODOT_BIN": "/fake/godot"}):
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="")):
            result = json.loads(server.update_baseline("t0_room"))

    assert result["updated"] is True
    assert (baseline_dir / "t0_room.png").exists()


def test_update_baseline_stages_with_git(tmp_path):
    baseline_dir = tmp_path / "tests" / "ui_screenshots"
    baseline_dir.mkdir(parents=True)
    screenshot = tmp_path / "snap.png"
    _solid_png(screenshot, (10, 20, 30))
    server._last_screenshot_path = screenshot

    with patch.dict("os.environ", {"GODOT_PROJECT": str(tmp_path), "GODOT_BIN": "/fake/godot"}):
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="")) as mock_run:
            server.update_baseline("t0_room")

    call_args = mock_run.call_args[0][0]
    assert call_args[0] == "git"
    assert call_args[1] == "add"


def test_update_baseline_returns_error_on_git_failure(tmp_path):
    baseline_dir = tmp_path / "tests" / "ui_screenshots"
    baseline_dir.mkdir(parents=True)
    screenshot = tmp_path / "snap.png"
    _solid_png(screenshot, (10, 20, 30))
    server._last_screenshot_path = screenshot

    with patch.dict("os.environ", {"GODOT_PROJECT": str(tmp_path), "GODOT_BIN": "/fake/godot"}):
        with patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="not a git repo")):
            result = server.update_baseline("t0_room")

    assert result.startswith("Error:")
    assert "git add failed" in result
```

- [ ] **Step 2: Run tests to confirm they fail (Pillow and new functions missing)**

```bash
cd /Users/kognido/game-dev/godot-mcp
uv run pytest tests/test_pixel_diff.py -v 2>&1 | head -30
```

Expected: `ImportError` or `AttributeError` — `_pixel_diff`, `compare_ui_screenshot`, `update_baseline` do not exist yet.

---

### Task 2: Add Pillow dependency

**Files:**
- Modify: `/Users/kognido/game-dev/godot-mcp/pyproject.toml`

- [ ] **Step 1: Add pillow via uv**

```bash
cd /Users/kognido/game-dev/godot-mcp
uv add pillow
```

Expected: `pyproject.toml` updated with `pillow` entry, `uv.lock` updated.

---

### Task 3: Implement `_pixel_diff`, `compare_ui_screenshot`, `update_baseline` in `server.py`

**Files:**
- Modify: `/Users/kognido/game-dev/godot-mcp/server.py`

Add the module-level tracking variable immediately after the existing imports block (after `from typing import Any`):

- [ ] **Step 1: Add `_last_screenshot_path` tracking variable after the imports**

Find this line in `server.py` (near line 14):
```python
from typing import Any
```

Add immediately after:
```python
# Tracks the most recent screenshot taken in a UI session.
# Set by compare_ui_screenshot; consumed by update_baseline.
_last_screenshot_path: "Path | None" = None
```

- [ ] **Step 2: Add `_pixel_diff` helper and two MCP tools at the end of `server.py`**

Append after the last `@mcp.tool()` definition:

```python
# ── Pixel-diff visual regression ───────────────────────────────────────────────

def _pixel_diff(
    new_path: "Path",
    baseline_path: "Path",
    diff_path: "Path",
    threshold: float,
) -> dict:
    """Compare two PNG files pixel-by-pixel using Pillow.
    Writes a diff image (dark background, changed pixels in magenta) to diff_path.
    Returns a result dict — never raises."""
    from PIL import Image, ImageChops

    img_new = Image.open(new_path).convert("RGB")
    img_base = Image.open(baseline_path).convert("RGB")

    if img_new.size != img_base.size:
        return {
            "error": "size_mismatch",
            "new_size": list(img_new.size),
            "baseline_size": list(img_base.size),
        }

    diff = ImageChops.difference(img_new, img_base)
    w, h = diff.size
    pixels = diff.load()
    changed = 0

    vis = Image.new("RGB", (w, h), (20, 20, 20))
    vis_pixels = vis.load()

    for y in range(h):
        for x in range(w):
            r, g, b = pixels[x, y]
            if r > 0 or g > 0 or b > 0:
                changed += 1
                vis_pixels[x, y] = (255, 0, 200)

    diff_path.parent.mkdir(parents=True, exist_ok=True)
    vis.save(diff_path)

    total = w * h
    diff_ratio = changed / total
    return {
        "passed": diff_ratio <= threshold,
        "diff_ratio": round(diff_ratio, 6),
        "diff_image_path": str(diff_path),
        "baseline_path": str(baseline_path),
    }


@mcp.tool()
def compare_ui_screenshot(baseline_name: str, threshold: float = 0.02) -> str:
    """Take a fresh screenshot and compare it against a named baseline PNG using pixel-exact diff.
    baseline_name is the filename without extension, e.g. 't0_room'. The baseline is loaded from
    tests/ui_screenshots/<baseline_name>.png in the project root.
    threshold is the maximum acceptable changed-pixel ratio (default 0.02 = 2%).
    Always writes a diff image to tests/ui_screenshots/diffs/<baseline_name>_diff.png.
    Returns JSON: {passed, diff_ratio, diff_image_path, baseline_path}.
    If the baseline does not exist: {error: 'baseline_not_found', baseline_name}.
    Requires an active session started by start_ui_session."""
    global _last_screenshot_path

    project = godot_project()
    baseline_path = Path(project) / "tests" / "ui_screenshots" / f"{baseline_name}.png"

    if not baseline_path.exists():
        return json.dumps({"error": "baseline_not_found", "baseline_name": baseline_name})

    result = _bridge.screenshot("", project)
    if not result["ok"]:
        return f"Error: {result['error']}"

    new_path = Path(result["path"])
    _last_screenshot_path = new_path

    diff_path = Path(project) / "tests" / "ui_screenshots" / "diffs" / f"{baseline_name}_diff.png"
    comparison = _pixel_diff(new_path, baseline_path, diff_path, threshold)
    return json.dumps(comparison)


@mcp.tool()
def update_baseline(baseline_name: str) -> str:
    """Promote the most recent screenshot to the named baseline slot.
    baseline_name is the filename without extension, e.g. 't0_room'.
    Copies the screenshot from the last compare_ui_screenshot call to
    tests/ui_screenshots/<baseline_name>.png and stages it with git add.
    Does NOT commit — the caller commits with a descriptive message.
    Returns JSON: {updated, path}. Returns an error string on failure."""
    global _last_screenshot_path

    if _last_screenshot_path is None or not _last_screenshot_path.exists():
        return "Error: no recent screenshot — call compare_ui_screenshot first"

    project = godot_project()
    baseline_path = Path(project) / "tests" / "ui_screenshots" / f"{baseline_name}.png"
    shutil.copy2(_last_screenshot_path, baseline_path)

    git_result = subprocess.run(
        ["git", "add", str(baseline_path)],
        cwd=project,
        capture_output=True,
        text=True,
    )
    if git_result.returncode != 0:
        return f"Error: git add failed — {git_result.stderr.strip()}"

    return json.dumps({"updated": True, "path": str(baseline_path)})
```

- [ ] **Step 3: Run tests to confirm they pass**

```bash
cd /Users/kognido/game-dev/godot-mcp
uv run pytest tests/test_pixel_diff.py -v 2>&1 | tail -30
```

Expected: all `test_pixel_diff.py` tests PASS.

- [ ] **Step 4: Run full test suite to confirm nothing is broken**

```bash
cd /Users/kognido/game-dev/godot-mcp
uv run pytest -v 2>&1 | tail -20
```

Expected: all tests PASS.

---

### Task 4: Add diffs `.gitignore` in the game project

Diff images are ephemeral — regenerated on every run. They should not be committed.

**Files:**
- Create: `/Users/kognido/game-dev/the_pattern/tests/ui_screenshots/diffs/.gitignore`

- [ ] **Step 1: Create the directory and gitignore**

```bash
mkdir -p /Users/kognido/game-dev/the_pattern/tests/ui_screenshots/diffs
```

```
# tests/ui_screenshots/diffs/.gitignore
*
!.gitignore
```

- [ ] **Step 2: Commit both repos**

```bash
cd /Users/kognido/game-dev/godot-mcp
git add pyproject.toml uv.lock server.py tests/test_pixel_diff.py
git commit -m "$(cat <<'EOF'
feat: add compare_ui_screenshot and update_baseline tools

Pixel-exact image comparison via Pillow. compare_ui_screenshot takes a
fresh screenshot, diffs it against a named baseline, and always writes
a diff image. update_baseline promotes the last screenshot to a named
baseline slot and git-stages it without committing.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"

cd /Users/kognido/game-dev/the_pattern
git add tests/ui_screenshots/diffs/.gitignore
git commit -m "$(cat <<'EOF'
chore: gitignore ephemeral pixel-diff images

Diff images in tests/ui_screenshots/diffs/ are regenerated on every
compare_ui_screenshot run and should not be tracked.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Commit 2 — `pixel-diff` Skill

### Task 5: Author and register the `pixel-diff` skill

The skill is a markdown file that tells agents exactly when to run comparisons, how to interpret results, and how to handle baseline updates — including the pre-approval mechanism.

**Files:**
- Create: skill markdown (path determined by superpowers plugin — use the `update-config` skill to register after creating the file)

- [ ] **Step 1: Create the skill file**

The superpowers plugin reads skills from its installed location. Create the file at:
```
/Users/kognido/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/pixel-diff.md
```

> ⚠️ The plugin cache path may differ if the superpowers plugin version has been updated. Run `ls /Users/kognido/.claude/plugins/cache/claude-plugins-official/superpowers/` to confirm the current version before writing.

```markdown
---
name: pixel-diff
description: Visual regression check using godot-mcp screenshot comparison. Use after any renderer or UI change, before declaring a task done. Supports pre-approval to skip blocking on intentional visual changes.
---

# pixel-diff — Visual Regression Workflow

## Invocation

```
/pixel-diff [approve:<name>[,<name>...] | approve:all]
```

`approve` is optional. It pre-authorises baseline updates for the listed names (or all baselines) so the agent does not block when a diff fails. The update still fires and the result is always reported to the user.

**Warning:** `approve:all` should only be used when the full scope of visual changes is understood. Unexpected diffs will update automatically — the report is the only safeguard.

---

## When to use

After any change to:
- `scripts/sigil_renderer.gd` or `scripts/sigil_render_math.gd`
- Any `.tscn` file
- Any script listed in `.claude/ui_critical_scripts.json`
- Any script containing `_draw(`, `add_child(`, or container constructors

---

## Flow 1 — Normal check

1. Ensure a UI session is active. If not: `start_ui_session()`
2. Navigate to the relevant screen state
3. Call `compare_ui_screenshot(baseline_name, threshold=0.02)`
4. Read the image at `diff_image_path` from the result
5. **If `passed: true`:** report `baseline_name` and `diff_ratio` to user, continue
6. **If `passed: false` and baseline NOT pre-approved:** STOP. Report to user:
   - `diff_ratio`
   - Path to diff image
   - Description of what changed visually
   - Ask: update baseline, adjust code, or ignore?
7. **If `passed: false` and baseline IS pre-approved:** proceed to Flow 2

---

## Flow 2 — Intentional update (approved or pre-approved)

1. Call `update_baseline(baseline_name)`
2. Report to user:
   - Baseline name
   - Old `diff_ratio`
   - Whether update was pre-approved or user-approved
3. Commit with this message format:
   ```
   chore: update baseline <name> — <reason>

   Pre-approved / approved by user: <context>
   ```
4. Continue task

---

## Flow 3 — Missing baseline (first capture)

1. `compare_ui_screenshot` returns `{"error": "baseline_not_found"}`
2. Do not treat this as a failure
3. Call `update_baseline(baseline_name)`
4. Commit the new baseline file
5. Report: "No baseline existed for `<name>` — captured initial reference"

---

## Baseline naming

Name baselines after the game state they represent:

| Name | State |
|------|-------|
| `t0_room` | Room at Time T0 |
| `t1_room` | Room at Time T1 |
| `journal_open` | Journal visible |
| `night_end_overlay` | Night end overlay |

New baselines: `<context>_<state>`, e.g. `investigation_start`.

Baseline files live in `tests/ui_screenshots/`. Diff images (ephemeral) live in `tests/ui_screenshots/diffs/` and are gitignored.

---

## Reverting a baseline

```bash
git checkout tests/ui_screenshots/<name>.png
```
```

- [ ] **Step 2: Verify the skill appears in the available skills list**

Restart Claude Code and check that `pixel-diff` appears in the skills list in the system prompt. If it does not appear, use the `update-config` skill to investigate registration.

- [ ] **Step 3: Commit the skill file**

```bash
cd /Users/kognido/game-dev/godot-mcp
git add .
git commit -m "$(cat <<'EOF'
feat: add pixel-diff skill

Workflow guidance for agents: when to compare screenshots, how to
handle failing diffs, pre-approval mechanism for intentional visual
changes, baseline naming convention.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- ✅ `compare_ui_screenshot(baseline_name, threshold)` → Task 3
- ✅ Returns `{passed, diff_ratio, diff_image_path, baseline_path}` → Task 3
- ✅ Returns `{error: baseline_not_found}` → Task 3
- ✅ Always writes diff image → Task 3 (`_pixel_diff` always saves)
- ✅ `update_baseline(baseline_name)` → Task 3
- ✅ `git add` but no commit → Task 3
- ✅ `_last_screenshot_path` module-level tracking → Task 3
- ✅ `tests/ui_screenshots/diffs/` gitignored → Task 4
- ✅ Skill: three flows (normal, intentional update, missing baseline) → Task 5
- ✅ Skill: pre-approval mechanism with `approve:all` warning → Task 5
- ✅ Skill: baseline naming convention → Task 5
- ✅ Skill: rollback instruction → Task 5
- ✅ Pillow added via uv → Task 2

**Signature consistency:**
- `_pixel_diff(new_path, baseline_path, diff_path, threshold)` — defined Task 3 Step 2, called in `compare_ui_screenshot` in same step ✅
- `_last_screenshot_path` — declared Task 3 Step 1, set in `compare_ui_screenshot`, read in `update_baseline` ✅
- All test mocks reference `server._bridge.screenshot` and `server._last_screenshot_path` — consistent with server.py structure ✅

**One gap fixed:** `shutil` is already imported at the top of `server.py` (line 5) — `update_baseline` uses `shutil.copy2` without a local import. Confirmed safe.
