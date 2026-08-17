# denkovi-cli - command line control of Denkovi USB relay boards.
# Copyright (C) 2026 Bernhard Trinnes
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License version 2, as published by the
# Free Software Foundation. This program is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY. See the LICENSE file for the full text.

"""Command line interface for Denkovi USB relay boards."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Mapping
from typing import NoReturn

from . import __version__
from .board import (
    BOARD_TYPES,
    DEFAULT_DELAY,
    Board,
    DenkoviError,
    discover_devices,
    mask_to_states,
    open_board,
    resolve_board_type,
    resolve_port,
    states_to_mask,
)
from .relays import (
    format_bits,
    format_mask,
    format_states,
    parse_pattern,
    parse_selection,
    summarise,
)

EXIT_ERROR = 1
EXIT_INTERRUPTED = 130


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except DenkoviError as error:
        print(f"denkovi: error: {error}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return EXIT_INTERRUPTED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="denkovi",
        description="Control Denkovi USB relay boards.",
        epilog=(
            "Relays are numbered from 1 and can be given as single numbers, ranges or "
            "comma separated lists: 'denkovi on 1', 'denkovi off 1-4', "
            "'denkovi toggle 1,3,5-8', 'denkovi on all'."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"denkovi {__version__}")
    parser.add_argument(
        "-p",
        "--port",
        help="serial port of the board (default: the single connected Denkovi board)",
    )
    parser.add_argument(
        "-b",
        "--board",
        choices=sorted(BOARD_TYPES),
        help="board type (default: probed, which only works for type16)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        metavar="SECONDS",
        help=(
            "delay between board commands, for type16 boards "
            f"(default: {DEFAULT_DELAY}; lower risks corrupt replies)"
        ),
    )
    parser.add_argument("--json", action="store_true", help="print machine readable output")
    parser.add_argument("--no-color", action="store_true", help="do not colourise output")

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    list_parser = subparsers.add_parser("list", help="list connected boards")
    list_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        dest="all_ports",
        help="list every serial port, not only Denkovi boards",
    )
    list_parser.set_defaults(handler=command_list)

    status_parser = subparsers.add_parser(
        "status", aliases=["state"], help="show the state of every relay"
    )
    status_parser.set_defaults(handler=command_status)

    for name, help_text in (
        ("on", "switch relays on"),
        ("off", "switch relays off"),
        ("toggle", "invert relays"),
    ):
        switch_parser = subparsers.add_parser(name, help=help_text)
        switch_parser.add_argument(
            "relays", nargs="+", metavar="RELAY", help="relays to act on, or 'all'"
        )
        switch_parser.set_defaults(handler=command_switch, action=name)

    set_parser = subparsers.add_parser(
        "set",
        help="set every relay at once from a bit pattern",
        description=(
            "Set the whole board from a bit pattern, where relay N is bit N-1. "
            "For example '0b101' switches relays 1 and 3 on and every other relay off."
        ),
    )
    set_parser.add_argument("pattern", help="pattern such as 255, 0b10101010 or 0xff")
    set_parser.set_defaults(handler=command_set)

    pulse_parser = subparsers.add_parser(
        "pulse", help="switch relays for a while, then switch back"
    )
    pulse_parser.add_argument("relays", nargs="+", metavar="RELAY", help="relays to pulse")
    pulse_parser.add_argument(
        "-d",
        "--duration",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="how long to hold the relays (default: 1.0)",
    )
    pulse_parser.add_argument(
        "--off",
        action="store_true",
        dest="pulse_off",
        help="pulse the relays off instead of on",
    )
    pulse_parser.set_defaults(handler=command_pulse)

    watch_parser = subparsers.add_parser("watch", help="poll the board and report state changes")
    watch_parser.add_argument(
        "-i",
        "--interval",
        type=float,
        default=0.5,
        metavar="SECONDS",
        help="seconds between polls (default: 0.5)",
    )
    watch_parser.set_defaults(handler=command_watch)

    return parser


###############
### Commands ##
###############


def command_list(args: argparse.Namespace) -> int:
    devices = discover_devices(all_ports=args.all_ports)

    if args.json:
        print(
            json.dumps(
                [vars(device) | {"denkovi": device.is_denkovi} for device in devices], indent=2
            )
        )
        return 0

    if not devices:
        what = "serial ports" if args.all_ports else "Denkovi boards"
        print(f"No {what} found.")
        return 0

    for device in devices:
        print(device.port)
        print(f"    serial       {device.serial_number or '-'}")
        print(f"    description  {device.description}")
        print(f"    manufacturer {device.manufacturer or '-'}")
    return 0


def command_status(args: argparse.Namespace) -> int:
    with _connect(args) as board:
        _report(board, board.get_states(), args)
    return 0


def command_switch(args: argparse.Namespace) -> int:
    with _connect(args) as board:
        relays = parse_selection(args.relays, board.num_relays)
        board.validate(relays)

        if args.action == "toggle":
            current = board.get_states()
            wanted = {relay: not current[relay] for relay in relays}
        else:
            on = args.action == "on"
            wanted = {relay: on for relay in relays}

        board.set_states(wanted)
        _report(board, board.get_states(), args)
    return 0


def command_set(args: argparse.Namespace) -> int:
    with _connect(args) as board:
        mask = parse_pattern(args.pattern, board.num_relays)
        board.set_states(mask_to_states(mask, board.num_relays))
        _report(board, board.get_states(), args)
    return 0


def command_pulse(args: argparse.Namespace) -> int:
    if args.duration < 0:
        raise DenkoviError("pulse duration must not be negative.")

    with _connect(args) as board:
        relays = parse_selection(args.relays, board.num_relays)
        board.validate(relays)

        held = not args.pulse_off
        before = board.get_states()
        board.set_states({relay: held for relay in relays})
        try:
            time.sleep(args.duration)
        finally:
            # Put back exactly what was there, whatever ended the sleep.
            board.set_states({relay: before[relay] for relay in relays})
        _report(board, board.get_states(), args)
    return 0


def command_watch(args: argparse.Namespace) -> int:
    if args.interval <= 0:
        raise DenkoviError("watch interval must be positive.")

    with _connect(args) as board:
        previous: dict[int, bool] | None = None
        while True:
            states = board.get_states()
            if states != previous:
                _report_change(board, states, previous, args)
                previous = states
            time.sleep(args.interval)


###############
### Helpers ###
###############


def _connect(args: argparse.Namespace):
    port = resolve_port(args.port)
    board_type = resolve_board_type(port, args.board)
    return open_board(port, board_type, delay=args.delay)


def _report(board: Board, states: Mapping[int, bool], args: argparse.Namespace) -> None:
    if args.json:
        print(json.dumps(_as_dict(board, states), indent=2))
        return

    mask = states_to_mask(states)
    print(f"{board.board_type} on {board.port}, {board.num_relays} relays")
    print(format_states(states, color=_color(args)))
    print(f"{summarise(states)}  [{format_mask(mask, board.num_relays)}]")


def _report_change(
    board: Board,
    states: Mapping[int, bool],
    previous: Mapping[int, bool] | None,
    args: argparse.Namespace,
) -> None:
    stamp = time.strftime("%H:%M:%S")
    if args.json:
        print(json.dumps(_as_dict(board, states) | {"time": stamp}), flush=True)
        return

    mask = states_to_mask(states)
    changed = (
        ""
        if previous is None
        else "  changed: "
        + ", ".join(str(relay) for relay in sorted(states) if states[relay] != previous[relay])
    )
    print(
        f"{stamp}  {format_bits(mask, board.num_relays)}  {summarise(states)}{changed}", flush=True
    )


def _as_dict(board: Board, states: Mapping[int, bool]) -> dict:
    mask = states_to_mask(states)
    return {
        "port": board.port,
        "board": board.board_type,
        "num_relays": board.num_relays,
        "mask": mask,
        "hex": format_mask(mask, board.num_relays),
        "relays": {str(relay): states[relay] for relay in sorted(states)},
    }


def _color(args: argparse.Namespace) -> bool | None:
    return False if args.no_color else None


def run() -> NoReturn:
    sys.exit(main())


if __name__ == "__main__":
    run()
