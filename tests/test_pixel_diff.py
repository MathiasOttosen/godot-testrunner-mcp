import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

import server


@pytest.fixture(autouse=True)
def reset_last_screenshot():
    server._last_screenshot_path = None
    yield
    server._last_screenshot_path = None


def _solid_png(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (10, 10)) -> None:
    Image.new("RGB", size, color).save(path)


def _half_changed_png(path_a: Path, path_b: Path, size: tuple[int, int] = (10, 10)) -> None:
    img_a = Image.new("RGB", size, (0, 0, 0))
    img_b = Image.new("RGB", size, (0, 0, 0))
    for y in range(size[1] // 2):
        for x in range(size[0]):
            img_b.putpixel((x, y), (255, 255, 255))
    img_a.save(path_a)
    img_b.save(path_b)


def test_pixel_diff_identical_images(tmp_path):
    baseline = tmp_path / "baseline.png"
    diff = tmp_path / "diff.png"
    _solid_png(baseline, (100, 150, 200))

    result = server._pixel_diff(baseline, baseline, diff, threshold=0.02)

    assert result["diff_ratio"] == 0.0
    assert result["passed"] is True
    assert diff.exists()


def test_pixel_diff_completely_different(tmp_path):
    baseline = tmp_path / "baseline.png"
    current = tmp_path / "current.png"
    diff = tmp_path / "diff.png"
    _solid_png(baseline, (0, 0, 0))
    _solid_png(current, (255, 255, 255))

    result = server._pixel_diff(baseline, current, diff, threshold=0.02)

    assert result["diff_ratio"] == 1.0
    assert result["passed"] is False


def test_pixel_diff_size_mismatch(tmp_path):
    baseline = tmp_path / "baseline.png"
    current = tmp_path / "current.png"
    diff = tmp_path / "diff.png"
    _solid_png(baseline, (100, 100, 100), size=(10, 10))
    _solid_png(current, (100, 100, 100), size=(20, 20))

    result = server._pixel_diff(baseline, current, diff, threshold=0.02)

    assert result["error"] == "size_mismatch"
    assert result["baseline_size"] == [10, 10]
    assert result["current_size"] == [20, 20]
    assert not diff.exists()


def test_pixel_diff_threshold_boundary(tmp_path):
    baseline = tmp_path / "baseline.png"
    current = tmp_path / "current.png"
    diff = tmp_path / "diff.png"
    _half_changed_png(baseline, current)

    assert server._pixel_diff(baseline, current, diff, threshold=0.6)["passed"] is True
    assert server._pixel_diff(baseline, current, diff, threshold=0.4)["passed"] is False


def test_pixel_diff_diff_image_highlights_changes(tmp_path):
    baseline = tmp_path / "baseline.png"
    current = tmp_path / "current.png"
    diff = tmp_path / "diff.png"
    _solid_png(baseline, (0, 0, 0))
    _solid_png(current, (255, 255, 255))

    server._pixel_diff(baseline, current, diff, threshold=0.02)

    diff_image = Image.open(diff).convert("RGB")
    assert all(diff_image.getpixel((x, y)) == (255, 0, 200) for y in range(10) for x in range(10))


def test_compare_ui_screenshot_baseline_not_found(tmp_path, monkeypatch):
    screenshot = tmp_path / "snap.png"
    _solid_png(screenshot, (20, 20, 20))
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))

    with patch.object(server._bridge, "screenshot", return_value={"ok": True, "path": str(screenshot)}):
        result = json.loads(server.compare_ui_screenshot("missing"))

    assert result["error"] == "baseline_not_found"
    assert result["baseline_name"] == "missing"
    assert result["current_path"] == str(screenshot.resolve())


def test_compare_ui_screenshot_passes_on_identical(tmp_path, monkeypatch):
    baseline_dir = tmp_path / "tests" / "ui_screenshots"
    baseline_dir.mkdir(parents=True)
    baseline = baseline_dir / "test_scene.png"
    screenshot = baseline_dir / "snap.png"
    _solid_png(baseline, (50, 50, 50))
    _solid_png(screenshot, (50, 50, 50))
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))

    with patch.object(server._bridge, "screenshot", return_value={"ok": True, "path": str(screenshot)}):
        result = json.loads(server.compare_ui_screenshot("test_scene", threshold=0.02))

    assert result["passed"] is True
    assert result["diff_ratio"] == 0.0
    assert result["baseline_path"] == str(baseline)
    assert result["diff_image_path"].endswith("test_scene_diff.png")


def test_compare_ui_screenshot_tracks_last_screenshot(tmp_path, monkeypatch):
    baseline_dir = tmp_path / "tests" / "ui_screenshots"
    baseline_dir.mkdir(parents=True)
    baseline = baseline_dir / "state.png"
    screenshot = tmp_path / "snap.png"
    _solid_png(baseline, (0, 0, 0))
    _solid_png(screenshot, (0, 0, 0))
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))

    with patch.object(server._bridge, "screenshot", return_value={"ok": True, "path": str(screenshot)}):
        server.compare_ui_screenshot("state")

    assert server._last_screenshot_path == screenshot.resolve()


def test_compare_ui_screenshot_rejects_invalid_baseline_name():
    result = json.loads(server.compare_ui_screenshot("../escape"))
    assert result["error"] == "invalid_baseline_name"


def test_update_baseline_without_recent_screenshot(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    server._last_screenshot_path = None

    result = json.loads(server.update_baseline("t0_room"))

    assert result["error"] == "no_recent_screenshot"


def test_update_baseline_copies_file_and_stages_it(tmp_path, monkeypatch):
    baseline_dir = tmp_path / "tests" / "ui_screenshots"
    baseline_dir.mkdir(parents=True)
    screenshot = tmp_path / "snap.png"
    _solid_png(screenshot, (10, 20, 30))
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    server._last_screenshot_path = screenshot.resolve()

    with patch("server.subprocess.run", return_value=MagicMock(returncode=0, stderr="")) as run_mock:
        result = json.loads(server.update_baseline("t0_room"))

    baseline = baseline_dir / "t0_room.png"
    assert result["updated"] is True
    assert result["path"] == str(baseline)
    assert baseline.exists()
    assert run_mock.call_args[0][0] == ["git", "add", str(baseline)]
    assert run_mock.call_args[1]["cwd"] == str(tmp_path)


def test_update_baseline_rejects_invalid_baseline_name(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    server._last_screenshot_path = tmp_path / "snap.png"

    result = json.loads(server.update_baseline("bad/name"))

    assert result["error"] == "invalid_baseline_name"
