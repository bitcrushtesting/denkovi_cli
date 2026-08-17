# denkovi-cli - command line control of Denkovi USB relay boards.
# Copyright (C) 2026 Bernhard Trinnes
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License version 2, as published by the
# Free Software Foundation. This program is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY. See the LICENSE file for the full text.

"""Command line control of Denkovi USB relay boards."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("denkovi-cli")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"

__all__ = ["__version__", "main"]


def main(argv: list[str] | None = None) -> int:
    """Entry point, kept lazy so importing the package stays cheap."""
    from .cli import main as _main

    return _main(argv)
