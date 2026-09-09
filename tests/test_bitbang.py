"""Tests for driving the bit-banged boards, with the FTDI chip stubbed out."""

from __future__ import annotations

from pathlib import Path
from typing import Self

import pytest

from denkovi_cli import bitbang
from denkovi_cli import board as board_module
from denkovi_cli.board import DenkoviError, Device, open_board

TYPE8 = "type8"
TYPE16 = "type16"


def _device(serial_number: str | None = "DAE00745") -> Device:
    return Device(
        port="/dev/cu.usbserial-DAE00745",
        serial_number=serial_number,
        description="relay board",
        manufacturer="Denkovi",
        vendor_id=0x0403,
        product_id=0x6001,
    )


class FakeBitBangDevice:
    """Stands in for pylibftdi's BitBangDevice: one byte of latched state."""

    def __init__(self, device_id: str | None, **kwargs: object) -> None:
        self.device_id = device_id
        self.kwargs = kwargs
        self.port = 0
        self.baudrate = 0
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_ftdi(monkeypatch: pytest.MonkeyPatch) -> list[FakeBitBangDevice]:
    """Open every board onto a fake chip, and record the ones that were opened."""
    opened: list[FakeBitBangDevice] = []

    def bit_bang_device(device_id: str | None, **kwargs: object) -> FakeBitBangDevice:
        device = FakeBitBangDevice(device_id, **kwargs)
        opened.append(device)
        return device

    class FtdiError(Exception):
        pass

    monkeypatch.setattr(bitbang, "_pylibftdi", lambda: (bit_bang_device, object, FtdiError))
    monkeypatch.setattr(bitbang, "_driver", lambda driver_class: None)
    return opened


class TestBackend:
    def test_opens_the_board_by_its_whole_serial_number(
        self, fake_ftdi: list[FakeBitBangDevice]
    ) -> None:
        backend = bitbang.BitBangBackend("DAE00745")
        # The library passes the prefix it would have searched with; the exact
        # serial number of the resolved board wins over it.
        backend.initialise("DAE", 921600, 0xFF, 1)

        assert fake_ftdi[0].device_id == "DAE00745"
        assert fake_ftdi[0].kwargs["direction"] == 0xFF
        assert fake_ftdi[0].baudrate == 921600

    def test_without_a_serial_number_the_first_board_is_taken(
        self, fake_ftdi: list[FakeBitBangDevice]
    ) -> None:
        bitbang.BitBangBackend(None).initialise("DAE", 921600, 0xFF, 1)
        assert fake_ftdi[0].device_id is None

    def test_reads_and_writes_the_state_byte(self, fake_ftdi: list[FakeBitBangDevice]) -> None:
        backend = bitbang.BitBangBackend("DAE00745")
        backend.initialise("DAE", 921600, 0xFF, 1)

        backend.writeByte(0b10100101)
        assert fake_ftdi[0].port == 0b10100101
        assert backend.readByte() == 0b10100101

    def test_reopening_closes_the_previous_board(self, fake_ftdi: list[FakeBitBangDevice]) -> None:
        backend = bitbang.BitBangBackend("DAE00745")
        backend.initialise("DAE", 921600, 0xFF, 1)
        backend.initialise("DAE", 921600, 0xFF, 1)

        assert fake_ftdi[0].closed
        assert not fake_ftdi[1].closed

    def test_closing_twice_is_harmless(self, fake_ftdi: list[FakeBitBangDevice]) -> None:
        backend = bitbang.BitBangBackend("DAE00745")
        backend.initialise("DAE", 921600, 0xFF, 1)
        backend.close()
        backend.close()

    def test_using_a_closed_board_is_a_clean_error(
        self, fake_ftdi: list[FakeBitBangDevice]
    ) -> None:
        with pytest.raises(DenkoviError, match="not open"):
            bitbang.BitBangBackend("DAE00745").readByte()


class TestLibrarySearch:
    """macOS keeps libftdi where ctypes does not look, so paths are given."""

    def test_only_libraries_that_exist_are_offered(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "libftdi1.dylib").touch()
        monkeypatch.setattr(
            bitbang, "MACOS_LIBRARY_DIRS", (str(tmp_path), "/nowhere/lib", "", str(tmp_path))
        )
        assert bitbang.macos_library_paths("libftdi") == [str(tmp_path / "libftdi1.dylib")]
        assert bitbang.macos_library_paths("libusb") == []


class TestErrorMessages:
    """A failure to open should say what to do about it, not print a traceback."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("libftdi library not found (search: ['ftdi1'])", "brew install libftdi"),
            ("b'device not found' (-3)", "already driving it"),
            ("b'unable to claim usb device' (-5)", "another program is driving it"),
        ],
    )
    def test_known_failures_are_explained(self, text: str, expected: str) -> None:
        assert expected in bitbang._open_failed(Exception(text), "DAE00745")

    def test_an_unknown_failure_still_names_the_board(self) -> None:
        message = bitbang._open_failed(Exception("something else"), "DAE00745")
        assert "DAE00745" in message and "something else" in message

    def test_a_library_that_will_not_load_reads_as_a_missing_library(self) -> None:
        # ctypes raises rather than pylibftdi when the path resolves to a
        # library built for the wrong architecture.
        error = OSError("incompatible architecture")
        assert "brew install libftdi" in bitbang._open_failed(error, None)


class FakeRelayHandler:
    NUMRELAYS = 8

    def __init__(self) -> None:
        self.states = dict.fromkeys(range(1, 9), False)


class FakeLibraryBoard:
    """Stands in for the relay library's board, remembering how it was opened."""

    last: FakeLibraryBoard

    def __init__(self, board_type: str, *args: object) -> None:
        self.board_type = board_type
        self.args = args
        self.relayHandler = FakeRelayHandler()
        self.initialised_with: object = None
        FakeLibraryBoard.last = self

    def initialise(self, *args: object) -> None:
        self.initialised_with = args[0] if args else None

    def disconnect(self) -> None:
        pass

    def getNumRelays(self) -> int:
        return self.relayHandler.NUMRELAYS


@pytest.fixture
def fake_library(monkeypatch: pytest.MonkeyPatch) -> type[FakeLibraryBoard]:
    monkeypatch.setattr(
        board_module.dae_RelayBoard, "DAE_RelayBoard", FakeLibraryBoard, raising=True
    )
    return FakeLibraryBoard


class TestOpenBoard:
    def test_a_bit_banged_board_gets_our_backend_and_its_serial_number(
        self, fake_library: type[FakeLibraryBoard], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(board_module.sys, "platform", "darwin")
        with open_board(_device(), TYPE8) as board:
            assert board.num_relays == 8

        opened = fake_library.last
        # Looked up on the USB bus by serial number, not opened as a serial port.
        assert opened.initialised_with == "DAE00745"
        assert isinstance(opened.relayHandler.FTD2XX, bitbang.BitBangBackend)

    def test_a_board_without_a_serial_number_falls_back_to_the_denkovi_prefix(
        self, fake_library: type[FakeLibraryBoard], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(board_module.sys, "platform", "darwin")
        with open_board(_device(serial_number=None), TYPE8):
            pass
        assert fake_library.last.initialised_with == board_module.DENKOVI_SERIAL_PREFIX

    def test_windows_keeps_the_librarys_own_backend(
        self, fake_library: type[FakeLibraryBoard], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(board_module.sys, "platform", "win32")
        with open_board(_device(), TYPE8):
            pass
        assert not hasattr(fake_library.last.relayHandler, "FTD2XX")

    def test_a_vcp_board_is_still_opened_on_its_port(
        self, fake_library: type[FakeLibraryBoard]
    ) -> None:
        device = _device()
        with open_board(device, TYPE16, delay=0.25):
            pass
        assert fake_library.last.initialised_with == device.port
        assert fake_library.last.args == (0.25,)  # the command delay, VCP only

    def test_an_unsupported_platform_says_so_rather_than_failing_obscurely(
        self, fake_library: type[FakeLibraryBoard], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `board` and `bitbang` both read the one `sys.platform`.
        monkeypatch.setattr(board_module.sys, "platform", "sunos5")
        with (
            pytest.raises(DenkoviError, match="Windows, macOS and Linux only"),
            open_board(_device(), TYPE8),
        ):
            pass


class FakePort:
    """A serial port that streams ``stream``, and answers ``reply`` once written to.

    A bit-banged board is the streaming case: it hands over bytes unprompted.
    A type16 board is the answering case: quiet until asked.
    """

    def __init__(self, stream: bytes = b"", reply: bytes = b"") -> None:
        self.stream = stream
        self.reply = reply
        self.written = b""
        self.timeout: float | None = None

    def __call__(self, *, port: str, baudrate: int, timeout: float) -> Self:
        self.timeout = timeout
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def reset_input_buffer(self) -> None:
        pass

    def reset_output_buffer(self) -> None:
        pass

    def write(self, data: bytes) -> int:
        self.written += data
        self.stream += self.reply
        return len(data)

    def read(self, size: int) -> bytes:
        data, self.stream = self.stream[:size], self.stream[size:]
        return data


class TestProbe:
    """Probing must never write to a board whose relays are the data lines."""

    @pytest.fixture
    def port(self, monkeypatch: pytest.MonkeyPatch) -> type[FakePort]:
        def install(fake: FakePort) -> FakePort:
            monkeypatch.setattr(board_module.serial, "Serial", fake)
            return fake

        return install  # type: ignore[return-value]

    def test_a_talkative_port_is_left_alone(self, port) -> None:
        # An FT245 hands over bytes with nothing asked of it, and anything
        # written to it would land on the relays.
        fake = port(FakePort(stream=b"\x00" * 8))

        assert board_module.probe_board_type("/dev/fake") is None
        assert fake.written == b""

    def test_a_board_that_answers_is_a_type16(self, port) -> None:
        fake = port(FakePort(reply=b"\x00\x00"))

        assert board_module.probe_board_type("/dev/fake") == TYPE16
        assert fake.written == b"ask//"

    def test_a_board_that_says_nothing_at_all_is_unknown(self, port) -> None:
        port(FakePort())
        assert board_module.probe_board_type("/dev/fake") is None

    def test_an_unidentified_board_asks_to_be_named(self, port) -> None:
        port(FakePort(stream=b"\x00" * 8))

        with pytest.raises(DenkoviError, match="--board type8"):
            board_module.resolve_board_type("/dev/fake", None)
