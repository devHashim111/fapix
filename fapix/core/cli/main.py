import typer

from .commands.all_custom_commands import (
    startproject_cmd,
    startapp_cmd,
    startdb_cmd,
    runserver_cmd,
    deleteapp_cmd,
    makemigrations_cmd,
    migrate_cmd,
    createuser_cmd,
    createsuperuser_cmd
)

cli = typer.Typer(help=" Fapix CLI: Batteries-included Async toolkit on FastAPI")

cli.command("startproject")(startproject_cmd)
cli.command("startapp")(startapp_cmd)
cli.command("startdb")(startdb_cmd)
cli.command("runserver")(runserver_cmd)
cli.command("deleteapp")(deleteapp_cmd)
cli.command("makemigrations")(makemigrations_cmd)
cli.command("migrate")(migrate_cmd)
cli.command("createuser")(createuser_cmd)
cli.command("createsuperuser")(createsuperuser_cmd)

if __name__ == "__main__":
    cli()
    app = cli()

