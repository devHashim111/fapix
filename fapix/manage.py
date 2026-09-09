#!/usr/bin/env python3
import sys
from typer import run

def main():
    # Import the CLI app from your package
    try:
        from core.cli.main import cli
    except ImportError as e:
        print("Error importing Fapix CLI:", e)
        sys.exit(1)

    cli()

if __name__ == "__main__":
    main()

