import subprocess
import sys
from pathlib import Path

import typer

app = typer.Typer()


def get_project_root() -> Path | None:
    """Walk upward from the current directory until a Fapix project root is found."""
    current = Path.cwd().resolve()

    while True:
        if (current / "main.py").is_file() and (current / "apps").is_dir():
            return current

        if current == current.parent:
            return None

        current = current.parent


# FAPIX_ROUTER_IMPORT = "from fapix.core.homepage import router as _fapix_homepage_router"
# FAPIX_ROUTER_INCLUDE = "app.include_router(_fapix_homepage_router)"


# def ensure_fapix_routes(project_root: Path) -> None:
#     """
#     Wire the built-in Fapix homepage/tester routes into the project's
#     router.py, unless they are already wired in.

#     The routes and their templates live entirely inside fapix.core.homepage;
#     only an import and an include_router call are written here, so the
#     developer can remove or replace them like any other line in the file.
#     """
#     router_file = project_root / "router.py"

#     if not router_file.is_file():
#         return

#     content = router_file.read_text(encoding="utf-8")

#     if FAPIX_ROUTER_IMPORT in content and FAPIX_ROUTER_INCLUDE in content:
#         return

#     changed = False

#     if FAPIX_ROUTER_IMPORT not in content:
#         lines = content.splitlines()
#         last_import_index = -1

#         for index, line in enumerate(lines):
#             if line.strip().startswith(("import ", "from ")):
#                 last_import_index = index

#         insert_at = last_import_index + 1 if last_import_index >= 0 else 0
#         lines.insert(insert_at, FAPIX_ROUTER_IMPORT)
#         content = "\n".join(lines)
#         changed = True

#     if FAPIX_ROUTER_INCLUDE not in content:
#         lines = content.splitlines()
#         app_creation_index = -1

#         for index, line in enumerate(lines):
#             if "FastAPI(" in line:
#                 app_creation_index = index

#         if app_creation_index >= 0:
#             lines.insert(app_creation_index + 1, "")
#             lines.insert(app_creation_index + 2, FAPIX_ROUTER_INCLUDE)
#         else:
#             lines.append("")
#             lines.append(FAPIX_ROUTER_INCLUDE)

#         content = "\n".join(lines)
#         changed = True

#     if changed:
#         router_file.write_text(content.rstrip() + "\n", encoding="utf-8")


@app.command()
def runserver_cmd(
    port: int | None = typer.Argument(None, help="Port number"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host address"),
    option_port: int | None = typer.Option(None, "--port", "-p", help="Port number"),
    reload: bool = typer.Option(True, "--reload/--no-reload", help="Enable or disable auto reload"),
    log_level: str = typer.Option("warning", "--log-level", help="Uvicorn log level"),
    workers: int | None = typer.Option(None, "--workers", help="Number of worker processes"),
):
    """Run the Fapix development server with auto-reload and optional worker processes."""

    project_root = get_project_root()

    if project_root is None:
        typer.secho("No Fapix project found.", fg=typer.colors.RED, bold=True)
        raise typer.Exit(code=1)

    if port is not None and option_port is not None:
        typer.secho(
            "Specify the port either as an argument or with --port, not both.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    selected_port = (
        option_port if option_port is not None
        else port if port is not None
        else 8000
    )

    if workers is not None and workers < 1:
        typer.secho("Workers must be at least 1.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if reload and workers is not None:
        typer.secho("--workers cannot be used with --reload.", fg=typer.colors.YELLOW)
        typer.echo("Use --no-reload when using workers.")
        raise typer.Exit(code=1)

   

    typer.echo()
    typer.secho(
        f"Starting Fapix server at http://{host}:{selected_port}",
        fg=typer.colors.CYAN,
        bold=True,
    )
    typer.secho(f"Tester pages:  http://{host}:{selected_port}/tester", fg=typer.colors.GREEN)
    typer.echo()
    typer.secho(f"Swagger docs:  http://{host}:{selected_port}/docs", fg=typer.colors.BLUE)
    typer.echo()

    if not reload:
        import uvicorn

        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from main import app as project_app

        try:
            uvicorn.run(
                project_app,
                host=host,
                port=selected_port,
                log_level=log_level,
                workers=workers or 1,
            )
        except KeyboardInterrupt:
            typer.echo()
            typer.echo("Server stopped.")

        return

    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        host,
        "--port",
        str(selected_port),
        "--log-level",
        log_level,
        "--reload",
    ]

    try:
        subprocess.run(command, cwd=project_root, check=True)
    except KeyboardInterrupt:
        typer.echo()
        typer.echo("Server stopped.")
    except subprocess.CalledProcessError as exc:
        typer.secho(
            f"Server stopped with exit code {exc.returncode}.",
            fg=typer.colors.RED,
        )