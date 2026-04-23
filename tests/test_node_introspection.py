from unittest.mock import MagicMock, patch

import server


def test_find_nodes_sends_contains_filter_when_requested(monkeypatch):
    bridge = MagicMock()
    bridge._session_conn = object()
    bridge.send_session_command.return_value = {"ok": True, "nodes": []}
    monkeypatch.setattr(server, "_bridge", bridge)

    server.find_nodes(name="Player", contains=True)

    bridge.send_session_command.assert_called_once_with("find_nodes", name="Player", contains=True)


def test_get_node_snapshot_sends_include_children_and_depth(monkeypatch):
    bridge = MagicMock()
    bridge._session_conn = object()
    bridge.send_session_command.return_value = {"ok": True, "node": {"name": "Player"}}
    monkeypatch.setattr(server, "_bridge", bridge)

    server.get_node_snapshot("Player", properties=["health"], include_children=True, depth=2)

    bridge.send_session_command.assert_called_once_with(
        "get_node_snapshot",
        node_path="Player",
        properties=["health"],
        include_children=True,
        depth=2,
    )


def test_scaffolded_remote_control_supports_snapshot_and_contains_search(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/usr/bin/false")
    (tmp_path / "project.godot").write_text('[application]\nconfig/name="Test"\n', encoding="utf-8")

    server.scaffold_tests()

    content = (tmp_path / "addons" / "godot_mcp" / "remote_control.gd").read_text(encoding="utf-8")
    assert '"get_node_snapshot"' in content
    assert 'params.get("contains", false)' in content


def test_scaffolded_tree_reports_script_path_and_property_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("GODOT_PROJECT", str(tmp_path))
    monkeypatch.setenv("GODOT_BIN", "/usr/bin/false")
    (tmp_path / "project.godot").write_text('[application]\nconfig/name="Test"\n', encoding="utf-8")

    server.scaffold_tests()

    content = (tmp_path / "addons" / "godot_mcp" / "mcp_tree.gd").read_text(encoding="utf-8")
    assert "script_path" in content
    assert "property_errors" in content
