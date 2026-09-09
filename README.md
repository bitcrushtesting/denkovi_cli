# denkovi-cli

[![CI](https://github.com/bitcrushtesting/denkovi_cli/actions/workflows/ci.yml/badge.svg)](https://github.com/bitcrushtesting/denkovi_cli/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/denkovi-cli.svg)](https://pypi.org/project/denkovi-cli/)

Command line control of [Denkovi](https://denkovi.com) USB relay boards.

```console
$ denkovi on 1,3
type16 DAE007Ej on /dev/cu.usbserial-DAE007Ej, 16 relays
 1 ●  ON    2 ○  off   3 ●  ON    4 ○  off
 5 ○  off   6 ○  off   7 ○  off   8 ○  off
 9 ○  off  10 ○  off  11 ○  off  12 ○  off
13 ○  off  14 ○  off  15 ○  off  16 ○  off
on: 1, 3  [0x0005]
```

## Install

Python 3.12 or newer.

```sh
uv tool install denkovi-cli     # or: pipx install denkovi-cli
```

That puts `denkovi` on your PATH. To add it to a project instead:

```sh
uv add denkovi-cli              # or: pip install denkovi-cli
```

### From a source checkout

```sh
git clone https://github.com/bitcrushtesting/denkovi_cli
cd denkovi_cli
uv sync                         # or: pip install .
```

### Without installing anything

To run from a source checkout with only the runtime dependencies present:

```sh
pip install pyserial dae-RelayBoard
pip install pylibftdi          # macOS and Linux, for the 4 and 8 relay boards
PYTHONPATH=src python -m denkovi_cli.cli status
```

`--version` reports `0.0.0+unknown` this way, since there is no installed package to
read it from.

### Running the command

The examples below are written as `uv run denkovi ...`, which is what a source
checkout needs. Drop the `uv run` prefix after `uv tool install` or `pipx install`,
or whenever the virtualenv is activated.

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
| `-s`, `--serial` | Serial number of the board, for when several are connected. |
| `-p`, `--port` | Serial port of the board. Mutually exclusive with `--serial`. |
| `-b`, `--board` | `type4`, `type8` or `type16`. Defaults to probing the board. |
| `--delay` | Seconds between board commands, type16 only. Default `0.05`. |
| `--json` | Machine readable output. |
| `--no-color` | Never colourise, whether or not the output is a terminal. |

With exactly one board connected, neither `--serial` nor `--port` is needed.

### Several boards at once

`denkovi list` prints the serial number of every connected board:

```console
$ denkovi list
SERIAL    PORT          DESCRIPTION
DAE007Ej  /dev/ttyUSB0  FT232R USB UART
DAE00ABC  /dev/ttyUSB1  FT232R USB UART
DAE00ABD  /dev/ttyUSB2  FT232R USB UART
```

Pass one to `--serial` to pick that board:

```sh
denkovi --serial DAE00ABC on 1
denkovi -s dae00abc on 1        # case insensitive
denkovi -s DAE00ABC toggle 1-4
```

An unambiguous prefix is enough, so `-s DAE007` is the same as `-s DAE007Ej` above.
If a prefix matches more than one board the command refuses rather than guessing,
and names the candidates.

Prefer `--serial` over `--port` when more than one board is connected: serial numbers
are burned into the FTDI chip and stay put, while port names (`/dev/ttyUSB0`, `COM3`)
depend on the order the boards were enumerated in and can move between reboots.

Running a command with several boards connected and no selector is an error that
lists what it found:

```console
$ denkovi status
denkovi: error: several Denkovi boards found. Pick one with --serial:
  DAE007Ej         /dev/ttyUSB0
  DAE00ABC         /dev/ttyUSB1
  DAE00ABD         /dev/ttyUSB2
```

Boards are recognised by their FTDI serial number, which Denkovi programs to start
with `DAE`. If a board's chip was reflashed with a serial number that does not,
find it with `denkovi list --all` and address it by `--port`.

Board type is probed by asking the board for its state: only the 16 relay board
answers. The 4 and 8 relay boards cannot be told apart from each other, so they have
to be named with `--board`:

```console
$ denkovi --board type8 on 1,3
type8 DAE00745 on /dev/cu.usbserial-DAE00745, 8 relays
1 ●  ON   2 ○  off  3 ●  ON   4 ○  off
5 ○  off  6 ○  off  7 ○  off  8 ○  off
on: 1, 3  [0x05]
```

Probing never writes to a bit-banged board. Its FTDI chip is a FIFO rather than a
UART, so every byte written to it lands straight on the relays — asking it for its
state would leave them holding a `/`, and the board would then answer with enough
bytes to pass for a 16 relay board that is not there.

So a bit-banged board is ruled out first, without writing anything. Reading the chip's
data lines changes nothing — no byte is sent and no pin is switched to an output — but
it wakes the read side of the FIFO, and the board then hands the port bytes with
nothing asked of it, which a board that answers a protocol does not do. Relays are
left exactly where they were.

This needs `libftdi`. Without it nothing can be told about the data lines and the
board is left to the protocol probe, which is where `--board` comes in.

## Board support

| Board | Driver | Works on |
| --- | --- | --- |
| `type16` | virtual COM port, ASCII protocol | macOS, Linux, Windows |
| `type8`, `type4` | FTDI chip bit-banged | macOS, Linux, Windows |

The 4 and 8 relay boards speak no protocol at all: their relays hang off the data
lines of the board's FTDI chip — an FT245 on the 8 relay board, an FT232 on the 4 —
which is driven in bit-bang mode. Because nothing answers back, these boards cannot
be probed and have to be named with `--board type8` or `--board type4`.

Windows reaches the chip through FTDI's D2XX driver and needs nothing extra:
`FTD2XX.dll` arrives with the board's own driver. macOS and Linux go through
`libftdi`, which is a C library and so does not come from pip:

```sh
brew install libftdi            # macOS
sudo apt install libftdi1-2     # Debian, Ubuntu
```

Its Python binding, `pylibftdi`, is installed with denkovi-cli. Nothing has to be
unloaded or disabled on macOS: the board can be bit-banged while the system's FTDI
serial driver still offers it as `/dev/cu.usbserial-*`.

## Notes

- Only one program can drive a board at a time. Two processes on the same serial
  port interleave their commands and corrupt each other's replies, which shows up
  as a communication error. A bit-banged board is claimed outright, and the second
  command reports that it could not open the board.
- Bit-banged boards keep their relays where they were left: the state lives in the
  FTDI chip's output latch, and closing the board does not disturb it.
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
[Peter Bingham][author], taken from PyPI as [`dae_RelayBoard`][pypi]. It implements
both the ASCII serial protocol of the 16 relay boards and the bit-banging of the 4
and 8 relay boards; this project adds discovery, argument parsing and output on top,
plus the `pylibftdi` backend that carries the bit-banged boards on macOS. The library
is distributed under the MIT licence.

Relay boards and their documentation are made by [Denkovi Assembly Electronics][denkovi],
who are not affiliated with this project.

[lib]: https://github.com/petersbingham/dae-py-relay-controller
[pypi]: https://pypi.org/project/dae-RelayBoard/
[author]: https://github.com/petersbingham
[denkovi]: https://denkovi.com

## Licence

Copyright (C) 2026 Bernhard Trinnes.

This program is free software; you can redistribute it and/or modify it under the
terms of the GNU General Public License version 2, as published by the Free Software
Foundation. It is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See [LICENSE](LICENSE) for the full text.

The MIT licence of `dae_RelayBoard` is compatible with the GPL, so the combined work
may be distributed under the GPL. That library keeps its own MIT licence.
