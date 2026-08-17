# denkovi-cli

[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)

Command line control of [Denkovi](https://denkovi.com) USB relay boards.

```console
$ denkovi on 1,3
type16 on /dev/cu.usbserial-DAE007Ej, 16 relays
 1 ●  ON    2 ○  off   3 ●  ON    4 ○  off
 5 ○  off   6 ○  off   7 ○  off   8 ○  off
 9 ○  off  10 ○  off  11 ○  off  12 ○  off
13 ○  off  14 ○  off  15 ○  off  16 ○  off
on: 1, 3  [0x0005]
```

## Install

Python 3.12 or newer. The relay library is a git submodule, so clone with it:

```sh
git clone --recurse-submodules <this repo>
cd denkovi_cli
```

If the repository was cloned without `--recurse-submodules`, run
`git submodule update --init` first, otherwise there is nothing to build.

### With uv

```sh
uv sync
```

### With pip

uv is not required; this is a standard PEP 621 package.

```sh
python3 -m venv .venv
source .venv/bin/activate               # Windows: .venv\Scripts\activate
pip install ./dae-py-relay-controller   # the submodule, first
pip install .
```

Install the submodule first, as above, if you want the copy this repository pins.
pip does not read `[tool.uv.sources]`, which is what points the `dae-RelayBoard`
dependency at the submodule, so a bare `pip install .` downloads `dae_RelayBoard`
from PyPI instead. Both work and both give version 1.5.2 — the PyPI release differs
only in code formatting — but only the two-step form is guaranteed to track the
submodule.

### Without installing anything

To run from a source checkout with only pyserial present:

```sh
pip install pyserial
PYTHONPATH=src:dae-py-relay-controller python -m denkovi_cli.cli status
```

`--version` reports `0.0.0+unknown` this way, since there is no installed package to
read it from.

### Running the command

The examples below are written as `uv run denkovi ...`. Drop the `uv run` prefix when
the virtualenv is activated, or after `uv tool install .` / `pipx install .`, which
put `denkovi` on your PATH.

## Usage

```sh
uv run denkovi list              # find connected boards
uv run denkovi status            # show every relay

uv run denkovi on 1              # one relay
uv run denkovi on 1-4            # a range, inclusive
uv run denkovi off 1,3,5-8       # a list, ranges allowed
uv run denkovi on all            # the whole board
uv run denkovi toggle 2

uv run denkovi set 0b10101010    # set the whole board at once
uv run denkovi pulse 3 -d 0.5    # on for half a second, then back
uv run denkovi watch             # print state changes as they happen
```

Relays are numbered from 1, the way they are labelled on the board.

In the bit mask `status` prints, and in the pattern `set` takes, relay N is bit N-1:
relay 1 is the least significant bit, so `0b101` means relays 1 and 3.

`--json` makes every command print machine readable output instead:

```sh
uv run denkovi --json status | jq '.relays["1"]'
```

### Options

| Option | Meaning |
| --- | --- |
| `-p`, `--port` | Serial port of the board. Defaults to the one connected Denkovi board. |
| `-b`, `--board` | `type4`, `type8` or `type16`. Defaults to probing the board. |
| `--delay` | Seconds between board commands, type16 only. Default `0.05`. |
| `--json` | Machine readable output. |
| `--no-color` | Never colourise, whether or not the output is a terminal. |

Boards are found by their FTDI serial number, which Denkovi programs to start with
`DAE`. If a board's chip was reflashed with a different serial number, find it with
`denkovi list --all` and pass `--port` yourself.

Board type is probed by asking the board for its state: only the 16 relay board
answers. The 4 and 8 relay boards are silent and indistinguishable from each other,
so they have to be named with `--board`.

## Board support

| Board | Driver | Works on |
| --- | --- | --- |
| `type16` | virtual COM port, ASCII protocol | macOS, Linux, Windows |
| `type8`, `type4` | FTDI D2XX bit-banging | Linux, Windows |

The 4 and 8 relay boards are driven by bit-banging the FT232R through the D2XX
driver, which the underlying library only implements for Windows and Linux; on
Linux they additionally need `pylibftdi`. Asking for one on macOS fails with an
explanation rather than a traceback.

## Notes

- Only one program can drive a board at a time. Two processes on the same serial
  port interleave their commands and corrupt each other's replies, which shows up
  as a communication error.
- The type16 protocol needs a delay between commands. The library's default of
  50ms is used; the documented 5ms was found to corrupt replies. `--delay` can
  raise it if a board proves flaky. Commands that drive the whole board the same
  way, such as `on all` or `set 0`, collapse into a single board command rather
  than 16 delayed ones; a mixed pattern still costs one command per relay.
- `pulse` restores the previous state of the relays it touched even if it is
  interrupted.

## Development

```sh
uv run pytest                          # tests, no board required
uv run ruff check src tests
uv run ruff format src tests
```

Or without uv, in an activated virtualenv:

```sh
pip install pytest ruff
python -m pytest
```

The tests cover the parsing, mask, formatting and CLI plumbing, and stub out device
discovery so they never touch a real board. CI runs them on Linux, macOS and Windows
against Python 3.12 to 3.14.

## Credits

The board communication is done by **[dae-py-relay-controller][lib]** by
[Peter Bingham][author], vendored here as a git submodule. It implements both the
ASCII serial protocol of the 16 relay boards and the D2XX bit-banging of the 4 and 8
relay boards; this project only adds discovery, argument parsing and output on top.
The library is distributed under the MIT licence — see
[`dae-py-relay-controller/README.md`](dae-py-relay-controller/README.md).

Relay boards and their documentation are made by [Denkovi Assembly Electronics][denkovi],
who are not affiliated with this project.

[lib]: https://github.com/petersbingham/dae-py-relay-controller
[author]: https://github.com/petersbingham
[denkovi]: https://denkovi.com

## Licence

Copyright (C) 2026 Bernhard Trinnes.

This program is free software; you can redistribute it and/or modify it under the
terms of the GNU General Public License version 2, as published by the Free Software
Foundation. It is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See [LICENSE](LICENSE) for the full text.

The MIT licence of the vendored library is compatible with the GPL, so the combined
work may be distributed under the GPL. The submodule keeps its own MIT licence.
