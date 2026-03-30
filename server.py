from fastmcp import FastMCP

mcp = FastMCP("godot-mcp")


# ── Resources ──────────────────────────────────────────────────────────────────

@mcp.resource("godot://docs/{topic}")
def godot_docs(topic: str) -> str:
    """Godot documentation reference for a given topic."""
    return f"Documentation for '{topic}': (not yet implemented)"


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def run_gdscript(script: str) -> str:
    """Run a GDScript snippet via a headless Godot process."""
    raise NotImplementedError("run_gdscript not yet implemented")


@mcp.tool()
def open_scene(scene_path: str) -> str:
    """Open a .tscn scene file in the running Godot editor."""
    raise NotImplementedError("open_scene not yet implemented")


@mcp.tool()
def list_project_files(directory: str = "res://") -> list[str]:
    """List files inside a Godot project directory."""
    raise NotImplementedError("list_project_files not yet implemented")


# ── Prompts ────────────────────────────────────────────────────────────────────

@mcp.prompt()
def gdscript_review(code: str) -> str:
    """Review GDScript code for best practices and common mistakes."""
    return (
        f"Please review the following GDScript code for correctness, "
        f"Godot 4 best practices, and potential bugs:\n\n```gdscript\n{code}\n```"
    )


if __name__ == "__main__":
    mcp.run()
