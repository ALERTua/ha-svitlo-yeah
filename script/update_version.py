# /// script
# dependencies = [
#   "typer",
# ]
# ///
"""Script to update version in pyproject.toml and manifest.json."""

import json
import os
from pathlib import Path

import typer

app = typer.Typer()


@app.command()
def update_version(
    version: str = typer.Argument(..., help="New version to set"),
) -> None:
    """Update version in project files and run uv lock."""
    # Update pyproject.toml via uv
    os.system(f"uv version {version}")  # noqa: S605

    # Update manifest.json
    manifest_path = Path("custom_components/svitlo_yeah/manifest.json")
    with manifest_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    data["version"] = version

    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    typer.echo(f"Version updated to {version}")


if __name__ == "__main__":
    app()
