#!/usr/bin/env python3
"""Nanobot launcher for the embedded Hermes runtime."""

from gateway.platforms.nanobot_api_compat import install as install_nanobot_overlay
from hermes_cli.main import main as hermes_main


def main() -> None:
    install_nanobot_overlay()
    hermes_main()


if __name__ == "__main__":
    main()
