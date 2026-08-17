# denkovi-cli - command line control of Denkovi USB relay boards.
# Copyright (C) 2026 Bernhard Trinnes
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License version 2, as published by the
# Free Software Foundation. This program is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY. See the LICENSE file for the full text.

"""Parsing of relay selections and patterns, and rendering of board state."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Mapping

from .board import DenkoviError

#: Selects every relay on the board.
ALL = "all"


def parse_selection(tokens: Iterable[str], num_relays: int) -> list[int]:
    """Turn command line relay arguments into a sorted list of relay numbers.

    Accepts single relays, inclusive ranges and comma separated lists, so
    ``4``, ``1-3``, ``1,4-6`` and ``all`` are all valid, and may be mixed
    across several arguments.
    """
    relays: set[int] = set()
    for token in tokens:
        for part in token.split(","):
            part = part.strip()
            if not part:
                continue
            if part.lower() == ALL:
                relays.update(range(1, num_relays + 1))
            elif "-" in part.lstrip("-"):
                relays.update(_parse_range(part))
            else:
                relays.add(_parse_relay(part))

    if not relays:
        raise DenkoviError("no relays given. Pass relay numbers, e.g. '1', '1-4', '1,3' or 'all'.")
    return sorted(relays)


def _parse_range(part: str) -> range:
    start_text, _, end_text = part.partition("-")
    start, end = _parse_relay(start_text), _parse_relay(end_text)
    if start > end:
        raise DenkoviError(f"invalid relay range {part!r}: {start} is above {end}.")
    return range(start, end + 1)


def _parse_relay(text: str) -> int:
    try:
        relay = int(text.strip())
    except ValueError:
        raise DenkoviError(
            f"invalid relay {text.strip()!r}: expected a number, a range or 'all'."
        ) from None
    if relay < 1:
        raise DenkoviError(f"invalid relay {relay}: relays are numbered from 1.")
    return relay


def parse_pattern(text: str, num_relays: int) -> int:
    """Parse a whole-board pattern into a bit mask with relay N in bit N-1.

    Understands decimal, and the ``0b``/``0o``/``0x`` prefixes, so relays 1 and
    3 of an eight relay board are ``5``, ``0b101`` or ``0x5``.
    """
    try:
        mask = int(text, 0)
    except ValueError:
        raise DenkoviError(
            f"invalid pattern {text!r}: expected a number such as 255, 0b1010 or 0xff."
        ) from None
    if mask < 0:
        raise DenkoviError(f"invalid pattern {text!r}: must not be negative.")
    if mask >> num_relays:
        raise DenkoviError(
            f"pattern {text!r} sets relays above {num_relays}, which this board does not have. "
            f"The largest pattern is {(1 << num_relays) - 1:#x}."
        )
    return mask


def format_mask(mask: int, num_relays: int) -> str:
    """Format a mask as hex, wide enough for the whole board."""
    return f"{mask:#0{2 + (num_relays + 3) // 4}x}"


def format_bits(mask: int, num_relays: int) -> str:
    """Format a mask as binary, most significant (highest numbered) relay first."""
    return f"{mask:0{num_relays}b}"


def format_states(
    states: Mapping[int, bool],
    *,
    columns: int = 4,
    color: bool | None = None,
) -> str:
    """Render relay states as a grid, four relays to a row by default."""
    style = _Style(color)
    relays = sorted(states)
    width = len(str(relays[-1])) if relays else 1

    lines = []
    for row_start in range(0, len(relays), columns):
        cells = []
        for relay in relays[row_start : row_start + columns]:
            on = states[relay]
            marker = style.on("●  ON ") if on else style.off("○  off")
            cells.append(f"{style.dim(f'{relay:>{width}}')} {marker}")
        lines.append("  ".join(cells))
    return "\n".join(lines)


def summarise(states: Mapping[int, bool]) -> str:
    """One line naming which relays are on."""
    on = sorted(relay for relay, state in states.items() if state)
    if not on:
        return "all off"
    return "on: " + ", ".join(_compress(on))


def _compress(relays: list[int]) -> list[str]:
    """Collapse consecutive relay numbers into ranges: 1,2,3,7 -> '1-3', '7'."""
    parts: list[str] = []
    start = previous = relays[0]
    for relay in relays[1:] + [None]:  # type: ignore[list-item]
        if relay == previous + 1:
            previous = relay
            continue
        parts.append(str(start) if start == previous else f"{start}-{previous}")
        if relay is not None:
            start = previous = relay
    return parts


class _Style:
    """ANSI styling, switched off when the output is not a terminal."""

    def __init__(self, color: bool | None = None) -> None:
        if color is None:
            color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        self.enabled = color

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def on(self, text: str) -> str:
        return self._wrap("32;1", text)

    def off(self, text: str) -> str:
        return self._wrap("2", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)
