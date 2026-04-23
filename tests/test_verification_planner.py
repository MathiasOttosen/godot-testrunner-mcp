import json

import server


def _write_project(tmp_path):
    (tmp_path / "project.godot").write_text('[application]\nconfig/name="Test"\n', encoding="utf-8")


def _write_ui_metadata(tmp_path):
    codex_dir = tmp_path / ".Codex"
    codex_dir.mkdir()
    (codex_dir / "ui_critical_scripts.json").write_text(
        json.dumps(
            {
                "scripts": {
                    "scripts/night_zero_room.gd": "Builds the night zero UI",
                    "scripts/sigil_renderer.gd": "Draws journal sigil strokes",
                }
            }
        ),
        encoding="utf-8",
    )


def test_plan_verification_marks_ui_critical_script_for_visual_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    _write_project(tmp_path)
    _write_ui_metadata(tmp_path)

    result = json.loads(server.plan_verification(["scripts/night_zero_room.gd"]))

    item = result["files"][0]
    assert item["path"] == "scripts/night_zero_room.gd"
    assert item["visual_validation_required"] is True
    assert "capture_scene" in item["recommended_tools"]
    assert "compare_ui_screenshot" in item["recommended_tools"]
    assert "Builds the night zero UI" in item["reason"]


def test_plan_verification_marks_scene_files_for_structural_or_runtime_capture(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    _write_project(tmp_path)

    result = json.loads(server.plan_verification(["scenes/room.tscn"]))

    item = result["files"][0]
    assert item["visual_validation_required"] is True
    assert "inspect_ui_scene" in item["recommended_tools"]
    assert "capture_scene" in item["recommended_tools"]


def test_plan_verification_warns_when_ui_metadata_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    _write_project(tmp_path)

    result = json.loads(server.plan_verification(["scripts/player.gd"]))

    assert "ui critical metadata not found" in result["warnings"]
    assert result["files"][0]["visual_validation_required"] is False


def test_plan_verification_uses_git_diff_when_changed_files_omitted(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    _write_project(tmp_path)

    def fake_run(*_args, **_kwargs):
        class Result:
            returncode = 0
            stdout = "scripts/foo.gd\nscenes/menu.tscn\n"
            stderr = ""

        return Result()

    monkeypatch.setattr(server.subprocess, "run", fake_run)

    result = json.loads(server.plan_verification())

    assert [item["path"] for item in result["files"]] == ["scripts/foo.gd", "scenes/menu.tscn"]


def test_plan_verification_reports_git_diff_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    _write_project(tmp_path)

    def fake_run(*_args, **_kwargs):
        class Result:
            returncode = 128
            stdout = ""
            stderr = "not a git repo"

        return Result()

    monkeypatch.setattr(server.subprocess, "run", fake_run)

    result = json.loads(server.plan_verification())

    assert result["files"] == []
    assert "could not inspect git diff: not a git repo" in result["warnings"]
