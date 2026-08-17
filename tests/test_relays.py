"""Tests for the parts of the CLI that do not need a board attached."""

from __future__ import annotations

import pytest

from denkovi_cli.board import DenkoviError, mask_to_states, states_to_mask
from denkovi_cli.relays import (
    format_bits,
    format_mask,
    format_states,
    parse_pattern,
    parse_selection,
    summarise,
)


class TestParseSelection:
    @pytest.mark.parametrize(
        ("tokens", "expected"),
        [
            (["1"], [1]),
            (["1", "3"], [1, 3]),
            (["1,3"], [1, 3]),
            (["1-4"], [1, 2, 3, 4]),
            (["1,4-6"], [1, 4, 5, 6]),
            (["4-4"], [4]),
            (["all"], list(range(1, 17))),
            (["ALL"], list(range(1, 17))),
            (["3", "1", "3"], [1, 3]),  # deduplicated and sorted
            (["1,,2"], [1, 2]),  # empty pieces ignored
        ],
    )
    def test_accepts(self, tokens: list[str], expected: list[int]) -> None:
        assert parse_selection(tokens, 16) == expected

    @pytest.mark.parametrize("tokens", [["0"], ["foo"], ["3-1"], ["1-"], [""], ["1-x"]])
    def test_rejects(self, tokens: list[str]) -> None:
        with pytest.raises(DenkoviError):
            parse_selection(tokens, 16)

    def test_out_of_range_is_left_to_the_board(self) -> None:
        # The parser does not know the board size, so 17 survives parsing and
        # is caught by Board.validate against the real relay count.
        assert parse_selection(["17"], 16) == [17]


class TestParsePattern:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [("0", 0), ("255", 255), ("0xff", 255), ("0b101", 5), ("0o7", 7), ("0xffff", 0xFFFF)],
    )
    def test_accepts(self, text: str, expected: int) -> None:
        assert parse_pattern(text, 16) == expected

    @pytest.mark.parametrize("text", ["nope", "-1", "0x1ffff", ""])
    def test_rejects(self, text: str) -> None:
        with pytest.raises(DenkoviError):
            parse_pattern(text, 16)

    def test_respects_board_size(self) -> None:
        assert parse_pattern("0xff", 8) == 0xFF
        with pytest.raises(DenkoviError, match="does not have"):
            parse_pattern("0x100", 8)


class TestMasks:
    def test_relay_one_is_the_least_significant_bit(self) -> None:
        assert states_to_mask({1: True, 2: False, 3: True, 4: False}) == 0b0101

    def test_round_trip(self) -> None:
        states = mask_to_states(0xAAAA, 16)
        assert states_to_mask(states) == 0xAAAA
        assert states[2] is True
        assert states[1] is False

    def test_mask_to_states_covers_every_relay(self) -> None:
        assert sorted(mask_to_states(0, 8)) == list(range(1, 9))


class TestFormatting:
    def test_mask_is_padded_to_the_board_width(self) -> None:
        assert format_mask(5, 16) == "0x0005"
        assert format_mask(5, 8) == "0x05"
        assert format_mask(5, 4) == "0x5"

    def test_bits_are_padded_to_the_board_width(self) -> None:
        assert format_bits(5, 8) == "00000101"

    def test_summarise_compresses_runs(self) -> None:
        states = mask_to_states(0b0000_0000_0111_0001, 16)
        assert summarise(states) == "on: 1, 5-7"

    def test_summarise_when_nothing_is_on(self) -> None:
        assert summarise(mask_to_states(0, 16)) == "all off"

    def test_summarise_whole_board(self) -> None:
        assert summarise(mask_to_states(0xFFFF, 16)) == "on: 1-16"

    def test_states_grid_has_one_row_per_four_relays(self) -> None:
        rendered = format_states(mask_to_states(0b1010, 4), color=False)
        assert rendered.count("\n") == 0
        assert "ON" in rendered and "off" in rendered

        rendered = format_states(mask_to_states(0, 16), color=False)
        assert rendered.count("\n") == 3

    def test_states_grid_is_plain_without_color(self) -> None:
        assert "\033[" not in format_states(mask_to_states(0xFF, 8), color=False)
