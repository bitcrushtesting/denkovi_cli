"""Tests for the CLI paths that work without a board attached."""

from __future__ import annotations

import json

import pytest

from denkovi_cli import board as board_module
from denkovi_cli import cli
from denkovi_cli.board import Device


def _fake_discovery(monkeypatch: pytest.MonkeyPatch, devices: list[Device]) -> None:
    """Pretend these are the connected boards, so no test touches real hardware.

    Both modules are patched: `list` calls the name imported into `cli`, while
    port auto-detection calls the one in `board`.
    """
    for module in (cli, board_module):
        monkeypatch.setattr(module, "discover_devices", lambda **_: list(devices))


@pytest.fixture
def no_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_discovery(monkeypatch, [])


@pytest.fixture
def one_device(monkeypatch: pytest.MonkeyPatch) -> Device:
    device = Device(
        port="/dev/ttyUSB0",
        serial_number="DAE007Ej",
        description="FT232R USB UART",
        manufacturer="Denkovi",
        vendor_id=0x0403,
        product_id=0x6001,
    )
    _fake_discovery(monkeypatch, [device])
    return device


class TestList:
    """These are the paths CI exercises on a runner with no hardware."""

    def test_says_so_when_nothing_is_connected(
        self, no_devices: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["list"]) == 0
        assert "No Denkovi boards found." in capsys.readouterr().out

    def test_json_is_an_empty_list_when_nothing_is_connected(
        self, no_devices: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["--json", "list"]) == 0
        assert json.loads(capsys.readouterr().out) == []

    def test_reports_a_board(self, one_device: Device, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["list"]) == 0
        out = capsys.readouterr().out
        assert one_device.port in out
        assert "DAE007Ej" in out

    def test_json_reports_a_board(
        self, one_device: Device, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["--json", "list"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload == [
            {
                "port": "/dev/ttyUSB0",
                "serial_number": "DAE007Ej",
                "description": "FT232R USB UART",
                "manufacturer": "Denkovi",
                "vendor_id": 0x0403,
                "product_id": 0x6001,
                "denkovi": True,
            }
        ]


class TestErrors:
    def test_no_board_is_a_clean_error_not_a_traceback(
        self, no_devices: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["status"]) == cli.EXIT_ERROR
        captured = capsys.readouterr()
        assert captured.err.startswith("denkovi: error: no Denkovi board found")
        assert "Traceback" not in captured.err

    def test_unparsable_relay_never_opens_the_port(
        self,
        one_device: Device,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def explode(*args: object, **kwargs: object) -> None:
            raise AssertionError("the board must not be opened for an invalid argument")

        monkeypatch.setattr(cli, "resolve_board_type", explode)
        assert cli.main(["--board", "type16", "pulse", "1", "-d", "-1"]) == cli.EXIT_ERROR
        assert "must not be negative" in capsys.readouterr().err

    def test_bad_board_type_is_rejected_by_argparse(self) -> None:
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["--board", "type32", "status"])
        assert exit_info.value.code == 2

    def test_a_command_is_required(self) -> None:
        with pytest.raises(SystemExit) as exit_info:
            cli.main([])
        assert exit_info.value.code == 2


class TestParser:
    def test_every_command_has_a_handler(self) -> None:
        parser = cli.build_parser()
        subparsers = next(
            action
            for action in parser._actions
            if hasattr(action, "choices") and action.dest == "command"
        )
        assert set(subparsers.choices) == {
            "list",
            "status",
            "state",
            "on",
            "off",
            "toggle",
            "set",
            "pulse",
            "watch",
        }
        for name, subparser in subparsers.choices.items():
            assert subparser.get_default("handler") is not None, name
