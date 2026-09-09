from pathlib import Path
import shutil

import typer
from rich import print


app = typer.Typer()


# ==========================================================
# PROJECT DETECTION
# ==========================================================

def find_project_root() -> Path | None:
    """
    Find the Fapix project root.

    A valid project contains:

        main.py
        apps/
    """

    current = Path.cwd().resolve()

    while True:

        if (
            (current / "main.py").is_file()
            and (current / "apps").is_dir()
        ):
            return current

        if current == current.parent:
            break

        current = current.parent

    return None


def require_project_root() -> Path:

    project_root = find_project_root()

    if project_root is None:

        print(
            "[red]❌ No Fapix project found.[/red]"
        )

        print(
            "[yellow]"
            "Run 'fapix deleteapp' inside a Fapix project."
            "[/yellow]"
        )

        raise typer.Exit(code=1)

    return project_root


# ==========================================================
# APP NAME
# ==========================================================

def normalize_app_name(
    name: str,
) -> str:

    return (
        name.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


# ==========================================================
# REMOVE ROUTER FROM MAIN.PY
# ==========================================================

def remove_router_from_main(
    main_file: Path,
    app_name: str,
):

    content = main_file.read_text(
        encoding="utf-8"
    )

    router_name = (
        f"{app_name}_router"
    )

    import_line = (
        f"from apps.{app_name}.urls "
        f"import router as {router_name}"
    )

    include_line = (
        f"app.include_router({router_name})"
    )

    lines = content.splitlines()

    new_lines = []

    removed_import = False
    removed_include = False

    for line in lines:

        stripped = line.strip()

        # --------------------------------------------------
        # Remove generated router import
        # --------------------------------------------------

        if stripped == import_line:

            removed_import = True
            continue

        # --------------------------------------------------
        # Remove generated include_router
        # --------------------------------------------------

        if stripped == include_line:

            removed_include = True
            continue

        new_lines.append(line)

    # ------------------------------------------------------
    # Remove excessive blank lines
    # ------------------------------------------------------

    cleaned_lines = []

    previous_blank = False

    for line in new_lines:

        is_blank = (
            not line.strip()
        )

        if is_blank and previous_blank:
            continue

        cleaned_lines.append(line)

        previous_blank = is_blank

    main_file.write_text(
        "\n".join(
            cleaned_lines
        ).rstrip() + "\n",
        encoding="utf-8",
    )

    if removed_import or removed_include:

        typer.secho(
            f"   └── Router '{app_name}' "
            "removed from main.py",
            fg=typer.colors.GREEN,
        )

    else:

        typer.secho(
            f"   └── No registered router "
            f"for '{app_name}' found in main.py",
            fg=typer.colors.YELLOW,
        )


# ==========================================================
# DELETE APP
# ==========================================================

@app.command()
def deleteapp_cmd(

    app_name: str = typer.Argument(
        ...,
        help="App name to delete",
    ),

):
    """
    Delete a Fapix app.

    Example:

        fapix deleteapp blog
    """

    # ------------------------------------------------------
    # PROJECT
    # ------------------------------------------------------

    project_root = (
        require_project_root()
    )

    # ------------------------------------------------------
    # Normalize
    # ------------------------------------------------------

    app_name = normalize_app_name(
        app_name
    )

    # ------------------------------------------------------
    # App path
    # ------------------------------------------------------

    app_path = (
        project_root
        / "apps"
        / app_name
    )

    # ------------------------------------------------------
    # Security check
    # ------------------------------------------------------

    apps_root = (
        project_root
        / "apps"
    ).resolve()

    app_path_resolved = (
        app_path.resolve()
    )

    if (
        app_path_resolved.parent
        != apps_root
    ):

        typer.secho(
            "❌ Invalid app path.",
            fg=typer.colors.RED,
        )

        raise typer.Exit(code=1)

    # ------------------------------------------------------
    # Check app
    # ------------------------------------------------------

    if not app_path.is_dir():

        typer.secho(
            f"❌ App '{app_name}' not found.",
            fg=typer.colors.RED,
        )

        typer.echo()

        typer.echo(
            f"Expected:"
        )

        typer.secho(
            f"    apps/{app_name}/",
            fg=typer.colors.YELLOW,
        )

        raise typer.Exit(code=1)

    # ------------------------------------------------------
    # Confirmation
    # ------------------------------------------------------

    typer.echo()

    typer.secho(
        f"⚠️ You are about to permanently delete:",
        fg=typer.colors.YELLOW,
        bold=True,
    )

    typer.secho(
        f"    {app_path}",
        fg=typer.colors.RED,
    )

    typer.echo()

    confirm = typer.confirm(
        f"Delete app '{app_name}'?"
    )

    if not confirm:

        typer.secho(
            "⚠️ App deletion cancelled.",
            fg=typer.colors.YELLOW,
        )

        raise typer.Exit(code=0)

    # ------------------------------------------------------
    # Delete
    # ------------------------------------------------------

    try:

        shutil.rmtree(
            app_path
        )

    except Exception as e:

        typer.secho(
            f"❌ Error deleting app: {e}",
            fg=typer.colors.RED,
        )

        raise typer.Exit(code=1)

    typer.secho(
        f"🗑️ App '{app_name}' deleted successfully.",
        fg=typer.colors.GREEN,
    )

    # ------------------------------------------------------
    # Remove router
    # ------------------------------------------------------

    main_file = (
        project_root / "main.py"
    )

    try:

        remove_router_from_main(
            main_file,
            app_name,
        )

    except Exception as e:

        typer.secho(
            "⚠️ App deleted, but main.py "
            f"could not be updated: {e}",
            fg=typer.colors.YELLOW,
        )

    # ------------------------------------------------------
    # Done
    # ------------------------------------------------------

    typer.echo()

    typer.secho(
        "✅ APP DELETION COMPLETED",
        fg=typer.colors.GREEN,
        bold=True,
    )

    typer.echo()