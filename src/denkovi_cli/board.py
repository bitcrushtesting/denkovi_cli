# denkovi-cli - command line control of Denkovi USB relay boards.
# Copyright (C) 2026 Bernhard Trinnes
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License version 2, as published by the
# Free Software Foundation. This program is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY. See the LICENSE file for the full text.

"""Discovery of, and access to, Denkovi USB relay boards.

Thin wrapper around the ``dae_RelayBoard`` library that adds device discovery,
board type probing and errors that are fit to show to a user.
"""

from __future__ import annotations

import contextlib
import sys
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import dae_RelayBoard
import serial
from dae_RelayBoard import dae_RelayBoard_Common
from serial.tools import list_ports

#: FTDI's USB vendor id. Every Denkovi USB board is built around an FTDI chip:
#: an FT232R on the 4 and 16 relay boards, an FT245R on the 8 relay board.
FTDI_VENDOR_ID = 0x0403

#: Denkovi programs its boards with a serial number starting with this.
DENKOVI_SERIAL_PREFIX = dae_RelayBoard_Common.DENKOVI_ID

#: Board type -> relay count, in the naming the library uses.
BOARD_TYPES = {
    dae_RelayBoard.DAE_RELAYBOARD_TYPE_4: 4,
    dae_RelayBoard.DAE_RELAYBOARD_TYPE_8: 8,
    dae_RelayBoard.DAE_RELAYBOARD_TYPE_16: 16,
}

#: Boards driven over a virtual COM port with the ASCII "//" protocol.
VCP_BOARD_TYPES = (dae_RelayBoard.DAE_RELAYBOARD_TYPE_16,)

#: Boards driven by bit-banging the data lines of their FTDI chip.
BITBANG_BOARD_TYPES = (
    dae_RelayBoard.DAE_RELAYBOARD_TYPE_4,
    dae_RelayBoard.DAE_RELAYBOARD_TYPE_8,
)

#: Default inter-command delay of the VCP protocol, in seconds.
DEFAULT_DELAY = 0.05

#: How long a board is listened to before it is probed, in seconds. Only long
#: enough to catch a board that is already talking; it is dead time otherwise.
LISTEN_TIMEOUT = 0.1


class DenkoviError(Exception):
    """An error worth reporting to the user without a traceback."""


@dataclass(frozen=True)
class Device:
    """A serial port that looks like it could be a relay board."""

    port: str
    serial_number: str | None
    description: str
    manufacturer: str | None
    vendor_id: int | None
    product_id: int | None

    @property
    def is_denkovi(self) -> bool:
        serial_number = self.serial_number or ""
        manufacturer = self.manufacturer or ""
        return serial_number.upper().startswith(DENKOVI_SERIAL_PREFIX) or (
            "denkovi" in manufacturer.lower()
        )

    @property
    def is_ftdi(self) -> bool:
        return self.vendor_id == FTDI_VENDOR_ID


def discover_devices(*, all_ports: bool = False) -> list[Device]:
    """Return the Denkovi boards on this machine, ordered by port name.

    With ``all_ports`` every serial port is returned instead, which is the
    escape hatch for a board whose FTDI chip was reprogrammed with a serial
    number that does not identify it as a Denkovi.
    """
    devices = [
        Device(
            port=port.device,
            serial_number=port.serial_number,
            description=port.description,
            manufacturer=port.manufacturer,
            vendor_id=port.vid,
            product_id=port.pid,
        )
        for port in list_ports.comports()
    ]
    if not all_ports:
        devices = [device for device in devices if device.is_denkovi]
    return sorted(devices, key=lambda device: device.port)


def resolve_device(port: str | None = None, serial_number: str | None = None) -> Device:
    """Return the board to talk to.

    A serial number picks one out of several connected boards, a port names one
    directly, and with neither the single connected board is used.
    """
    if port is not None and serial_number is not None:
        raise DenkoviError("--port and --serial cannot be used together.")

    devices = discover_devices()

    if serial_number is not None:
        return _match_serial(devices, serial_number)

    if port is not None:
        # A port may legitimately name a board that discovery did not recognise,
        # so fall back to a device that carries nothing but the port.
        for device in devices:
            if device.port == port:
                return device
        return Device(
            port=port,
            serial_number=None,
            description="",
            manufacturer=None,
            vendor_id=None,
            product_id=None,
        )

    if not devices:
        raise DenkoviError(
            "no Denkovi board found. Check that it is plugged in, or pass "
            "--port explicitly ('denkovi list --all' shows every serial port)."
        )
    if len(devices) > 1:
        raise DenkoviError(
            f"several Denkovi boards found. Pick one with --serial:\n{_describe(devices)}"
        )
    return devices[0]


def _match_serial(devices: list[Device], serial_number: str) -> Device:
    """Find the one board whose serial number the user meant.

    Matching is case insensitive, as it is in the underlying library, and an
    unambiguous prefix is accepted so long serials need not be typed in full.
    """
    wanted = serial_number.upper()
    serials = [(device, (device.serial_number or "").upper()) for device in devices]

    matches = [device for device, found in serials if found == wanted]
    if not matches:
        matches = [device for device, found in serials if found.startswith(wanted)]

    if not matches:
        if not devices:
            raise DenkoviError(
                f"no board with serial {serial_number!r}: no Denkovi board is connected."
            )
        raise DenkoviError(
            f"no board with serial {serial_number!r}. Connected boards:\n{_describe(devices)}"
        )
    if len(matches) > 1:
        raise DenkoviError(
            f"serial {serial_number!r} matches several boards:\n{_describe(matches)}\n"
            "Give more of the serial number."
        )
    return matches[0]


def _describe(devices: list[Device]) -> str:
    return "\n".join(
        f"  {device.serial_number or '(no serial)':<16} {device.port}" for device in devices
    )


def probe_board_type(port: str, *, timeout: float = 1.0) -> str | None:
    """Return the board type on ``port``, or ``None`` if it cannot be told.

    Only the VCP boards can be identified over the wire: they answer the
    ``ask`` command with one status byte per eight relays. The bit-banged 4 and
    8 relay boards cannot be told apart from each other, so they have to be
    named explicitly.

    Nothing is written to a board that must not be written to. A bit-banged
    board is a FIFO wearing a serial port's clothes: every byte written to it
    lands on the relays, and 'ask//' would leave them holding a '/'. It gives
    itself away by handing over bytes with nothing asked of it, which a board
    that answers a protocol never does, so the port is listened to first and
    only a port that stays quiet is spoken to.
    """
    try:
        with serial.Serial(port=port, baudrate=9600, timeout=LISTEN_TIMEOUT) as connection:
            time.sleep(DEFAULT_DELAY)
            connection.reset_input_buffer()
            connection.reset_output_buffer()
            if connection.read(1):
                return None
            connection.timeout = timeout
            connection.write(b"ask//")
            time.sleep(DEFAULT_DELAY)
            reply = connection.read(2)
    except (OSError, serial.SerialException) as error:
        raise DenkoviError(f"could not open {port}: {error}") from error

    if len(reply) == 2:
        return dae_RelayBoard.DAE_RELAYBOARD_TYPE_16
    return None


def resolve_board_type(port: str, board_type: str | None) -> str:
    """Return the board type to drive ``port`` with, probing when not given."""
    if board_type is not None:
        if board_type not in BOARD_TYPES:
            supported = ", ".join(BOARD_TYPES)
            raise DenkoviError(f"unknown board type {board_type!r}. Supported: {supported}.")
        return board_type

    detected = probe_board_type(port)
    if detected is None:
        raise DenkoviError(
            f"could not identify the board on {port}. The 4 and 8 relay boards cannot "
            "be detected over the wire; pass --board type4 or --board type8."
        )
    return detected


class Board:
    """A connected relay board.

    Relays are numbered from 1, as they are labelled on the board and in the
    underlying library.
    """

    def __init__(
        self, handle: dae_RelayBoard.DAE_RelayBoard, device: Device, board_type: str
    ) -> None:
        self._handle = handle
        self.device = device
        self.board_type = board_type

    @property
    def port(self) -> str:
        return self.device.port

    @property
    def serial_number(self) -> str | None:
        return self.device.serial_number

    @property
    def num_relays(self) -> int:
        return self._handle.getNumRelays()

    def validate(self, relays: list[int]) -> None:
        """Raise if any relay number is outside what this board has."""
        out_of_range = sorted({relay for relay in relays if not 1 <= relay <= self.num_relays})
        if out_of_range:
            numbers = ", ".join(str(relay) for relay in out_of_range)
            raise DenkoviError(
                f"relay {numbers} out of range: this {self.board_type} board has "
                f"{self.num_relays} relays (1-{self.num_relays})."
            )

    def get_states(self) -> dict[int, bool]:
        return dict(self._handle.getStates())

    def set_states(self, states: Mapping[int, bool]) -> None:
        """Set the given relays, leaving every other relay untouched."""
        self.validate(list(states))
        if not states:
            return
        # The library writes one relay per command, so a full-board write is
        # worth collapsing into the board's own all-on/all-off command.
        wanted = set(states.values())
        if len(states) == self.num_relays and len(wanted) == 1:
            self.set_all(wanted.pop())
            return
        self._handle.setStates(dict(states))

    def set_all(self, on: bool) -> None:
        if on:
            self._handle.setAllStatesOn()
        else:
            self._handle.setAllStatesOff()

    def mask(self) -> int:
        """Return the board state as an integer, relay N in bit N-1."""
        return states_to_mask(self.get_states())


def states_to_mask(states: Mapping[int, bool]) -> int:
    mask = 0
    for relay, on in states.items():
        if on:
            mask |= 1 << (relay - 1)
    return mask


def mask_to_states(mask: int, num_relays: int) -> dict[int, bool]:
    return {relay: bool(mask >> (relay - 1) & 1) for relay in range(1, num_relays + 1)}


@contextlib.contextmanager
def open_board(
    device: Device,
    board_type: str,
    *,
    delay: float = DEFAULT_DELAY,
) -> Iterator[Board]:
    """Connect to a board, and disconnect again however the block exits."""
    port = device.port
    bit_banged = board_type in BITBANG_BOARD_TYPES
    if bit_banged and not _has_bitbang_support():
        raise DenkoviError(
            f"the {board_type} board is driven by bit-banging its FTDI chip, which is "
            f"implemented for Windows, macOS and Linux only (this is {sys.platform}). "
            "Only type16 boards can be used here."
        )

    try:
        # Only the VCP boards take a command delay; the bit-banged ones take no args.
        args = (delay,) if board_type in VCP_BOARD_TYPES else ()
        handle = dae_RelayBoard.DAE_RelayBoard(board_type, *args)
        if bit_banged and sys.platform != "win32":
            # The library has no backend for macOS, and the one it has for Linux
            # can only find a board by a prefix of its serial number, so both are
            # served by ours instead. Imported here to keep pylibftdi off the
            # path of anyone who only ever touches a type16 board.
            from .bitbang import BitBangBackend

            handle.relayHandler.FTD2XX = BitBangBackend(device.serial_number)
        handle.initialise(_initialise_argument(device, board_type))
    except dae_RelayBoard_Common.Denkovi_Exception as error:
        raise DenkoviError(f"could not connect to the board on {port}: {error}") from error

    board = Board(handle, device, board_type)
    try:
        yield board
    except dae_RelayBoard_Common.Denkovi_Exception as error:
        raise DenkoviError(
            f"communication with the board on {port} failed: {error}. Only one program "
            "can drive the board at a time; a longer --delay can also help."
        ) from error
    finally:
        with contextlib.suppress(Exception):
            handle.disconnect()


def _initialise_argument(device: Device, board_type: str) -> str:
    """Return what the library's ``initialise`` wants for this board type.

    The VCP boards are opened on their serial port. The bit-banged ones are not
    reached through a serial port at all: they are looked up on the USB bus by
    their FTDI serial number, and a board that only ``--port`` named may not
    have one to give, in which case the Denkovi prefix picks the first board.
    """
    if board_type in VCP_BOARD_TYPES:
        return device.port
    return device.serial_number or DENKOVI_SERIAL_PREFIX


def _has_bitbang_support() -> bool:
    if sys.platform == "win32":
        return True
    from .bitbang import is_supported

    return is_supported()
