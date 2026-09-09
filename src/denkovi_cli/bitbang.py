# denkovi-cli - command line control of Denkovi USB relay boards.
# Copyright (C) 2026 Bernhard Trinnes
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License version 2, as published by the
# Free Software Foundation. This program is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY. See the LICENSE file for the full text.

"""Bit-banged access to the 4 and 8 relay boards, on macOS as well as Linux.

Those boards carry no serial protocol: their relays hang off the eight data
lines of the FTDI chip, which is driven in asynchronous bit-bang mode. The
relay library reaches those lines through a backend it picks by platform, and
it has one for Windows and one for Linux only, so on macOS it ends up with no
backend at all.

This module is a backend of the same shape, written against ``pylibftdi`` --
the library the Linux one uses, which works just as well on macOS. It is put
in place of the library's own; see `board.open_board`. Two things it does
differently:

* it finds ``libftdi`` where Homebrew and MacPorts put it, which is outside
  the paths ctypes searches;
* it opens a board by its whole serial number rather than by a prefix, so the
  board that ``--serial`` picked is the board that gets driven.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .board import DenkoviError

#: Where Homebrew and MacPorts keep their libraries. ``HOMEBREW_PREFIX`` comes
#: first so a non-standard Homebrew is honoured.
MACOS_LIBRARY_DIRS = (
    os.environ.get("HOMEBREW_PREFIX", "") + "/lib",
    "/opt/homebrew/lib",  # Homebrew on Apple silicon
    "/usr/local/lib",  # Homebrew on Intel
    "/opt/local/lib",  # MacPorts
)

#: File name of each library pylibftdi loads, as installed on macOS.
MACOS_LIBRARY_NAMES = {"libftdi": "libftdi1.dylib", "libusb": "libusb-1.0.dylib"}


def is_supported() -> bool:
    """Whether this platform can bit-bang a board through pylibftdi."""
    return sys.platform == "darwin" or "linux" in sys.platform


def macos_library_paths(name: str) -> list[str]:
    """Return the paths to try for ``name`` before ctypes' own library search.

    Only paths that exist are returned: a path that does not resolve sends
    pylibftdi on to ``find_library``, which on a Mac that has both Homebrew
    prefixes can turn up a library built for the other architecture.
    """
    file_name = MACOS_LIBRARY_NAMES[name]
    paths = [str(Path(directory) / file_name) for directory in MACOS_LIBRARY_DIRS if directory]
    return [path for path in dict.fromkeys(paths) if Path(path).is_file()]


class BitBangBackend:
    """An FTDI chip driven in bit-bang mode, one byte in and one byte out.

    Implements the four methods the relay library calls on its backend:
    ``initialise``, ``close``, ``writeByte`` and ``readByte``. The library
    keeps the relay-to-bit mapping and the read-modify-write of the state
    byte to itself.
    """

    def __init__(self, serial_number: str | None = None) -> None:
        self.serial_number = serial_number
        self._device: Any = None

    def initialise(self, device_id: str, baud_rate: int, mask: int, bit_mode: int) -> None:
        """Open the board. Called by the library with its own defaults."""
        # `device_id` is the serial number prefix the library searches with, so
        # it would open whichever DAE board came first. The serial number of
        # the board that was actually resolved is better, and is used when
        # there is one; a board addressed by --port alone may not have one, and
        # then the first FTDI device on the bus is taken.
        wanted = self.serial_number or None
        bit_bang_device, driver, ftdi_error = _pylibftdi()

        self.close()
        try:
            device = bit_bang_device(
                wanted,
                direction=mask,
                bitbang_mode=bit_mode,
                driver=_driver(driver),
                # On macOS there is no kernel driver to hand back, and asking
                # for one pulls in libusb for nothing.
                auto_detach=sys.platform != "darwin",
            )
            device.baudrate = baud_rate
        # pylibftdi raises FtdiError for anything it recognises; a library that
        # cannot be loaded at all surfaces as the ctypes error instead.
        except (ftdi_error, OSError, AttributeError) as error:
            raise DenkoviError(_open_failed(error, wanted)) from error
        self._device = device

    def close(self) -> None:
        device, self._device = self._device, None
        if device is not None:
            device.close()

    def writeByte(self, byte: int) -> None:  # camelCase: named by the library
        self._connected().port = byte

    def readByte(self) -> int:  # camelCase: named by the library
        return int(self._connected().port)

    def _connected(self) -> Any:
        if self._device is None:
            raise DenkoviError("the board is not open.")
        return self._device


def _pylibftdi() -> tuple[Any, Any, type[BaseException]]:
    """Return the pylibftdi names used here, or say how to install it."""
    try:
        from pylibftdi import BitBangDevice, Driver, FtdiError
    except ImportError as error:
        raise DenkoviError(
            "the 4 and 8 relay boards are driven through pylibftdi, which is not "
            "installed. Install it with 'pip install pylibftdi' (it also needs the "
            "libftdi C library: 'brew install libftdi' on macOS, or the distribution's "
            "libftdi1 package on Linux)."
        ) from error
    return BitBangDevice, Driver, FtdiError


def _driver(driver_class: Any) -> Any:
    """Return a pylibftdi driver that can find its libraries on this platform.

    Everywhere but macOS the stock search works. On macOS the Homebrew and
    MacPorts paths have to be added: ctypes does not look there, and neither
    ``libftdi`` nor ``libusb`` ships with the system. They go in front of the
    plain library names rather than after, so the library that was actually
    installed wins over anything ``find_library`` digs up. The search list is
    set on the instance because the constructor argument covers only
    ``libftdi``, and setting it writes through to state shared by every driver.
    """
    driver = driver_class()
    if sys.platform == "darwin":
        driver._lib_search = {
            name: [*macos_library_paths(name), *search]
            for name, search in driver_class._lib_search.items()
        }
    return driver


def _open_failed(error: BaseException, serial_number: str | None) -> str:
    """Turn a pylibftdi failure into something worth reading."""
    text = str(error)
    which = f"board {serial_number}" if serial_number else "board"

    if "libftdi library not found" in text or isinstance(error, OSError | AttributeError):
        return (
            "could not load the libftdi library, which the 4 and 8 relay boards are "
            "driven through. Install it with 'brew install libftdi' on macOS, or the "
            "distribution's libftdi1 package on Linux."
        )
    if "unable to claim" in text.lower() or "(-5)" in text:
        return (
            f"could not claim the {which}: another program is driving it. Close any "
            "other denkovi command, and on Linux unload the ftdi_sio driver if it is "
            "holding the board."
        )
    if "(-3)" in text:
        # libftdi walks past a board it cannot open and ends up reporting that it
        # found nothing, so a busy board and an absent one look the same here.
        return (
            f"could not open the {which} on the USB bus: either it is not plugged in, "
            "or another program is already driving it, which only one can at a time "
            "('denkovi list' shows the boards that were found)."
        )
    return f"could not open the {which}: {text.strip()}"
