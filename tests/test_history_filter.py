"""Tests for the history browser's filtering functionality."""

from __future__ import annotations

from unittest.mock import MagicMock

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.history import InMemoryHistory

from ptpython.history_browser import HistoryMapping


def _make_history(*entries: str) -> InMemoryHistory:
    h = InMemoryHistory()
    for entry in entries:
        h.append_string(entry)
    return h


def _make_mapping(
    entries: list[str],
    original_text: str = "",
    cursor_pos: int = 0,
) -> HistoryMapping:
    mock_history = MagicMock()
    mock_history.default_buffer = Buffer(
        document=Document(original_text, cursor_pos), read_only=True
    )
    python_history = _make_history(*entries)
    original_document = Document(original_text, cursor_pos)
    return HistoryMapping(mock_history, python_history, original_document)


# ---------------------------------------------------------------------------
# Basic filtering
# ---------------------------------------------------------------------------


class TestFilterNarrowsCandidates:
    def test_empty_filter_shows_all(self) -> None:
        m = _make_mapping(["print('hello')", "x = 1", "y = 2"])
        assert len(m.history_lines) == 3
        m.apply_filter("")
        assert len(m.history_lines) == 3

    def test_filter_matches_subset(self) -> None:
        m = _make_mapping(["print('hello')", "x = 1", "print('world')"])
        m.apply_filter("print")
        assert len(m.history_lines) == 2
        assert m.history_lines[0] == "print('hello')"
        assert m.history_lines[1] == "print('world')"

    def test_filter_is_case_insensitive(self) -> None:
        m = _make_mapping(["Print('hello')", "x = 1", "PRINT('world')"])
        m.apply_filter("print")
        assert len(m.history_lines) == 2

    def test_filter_no_matches_gives_empty(self) -> None:
        m = _make_mapping(["print('hello')", "x = 1"])
        m.apply_filter("zzzzz")
        assert len(m.history_lines) == 0
        assert m.concatenated_history == ""

    def test_filter_strips_whitespace(self) -> None:
        m = _make_mapping(["print('hello')", "x = 1"])
        m.apply_filter("  print  ")
        assert len(m.history_lines) == 1


# ---------------------------------------------------------------------------
# Multi-line statement boundary preservation
# ---------------------------------------------------------------------------


class TestMultiLineBoundaryPreservation:
    def test_multiline_entry_kept_together(self) -> None:
        entries = [
            "def foo():\n    return 42",
            "x = 1",
            "class Bar:\n    pass",
        ]
        m = _make_mapping(entries)
        m.apply_filter("foo")
        assert len(m.history_lines) == 2
        assert m.history_lines[0] == "def foo():"
        assert m.history_lines[1] == "    return 42"

    def test_match_on_second_line_keeps_whole_entry(self) -> None:
        entries = [
            "def foo():\n    return 42",
            "x = 1",
        ]
        m = _make_mapping(entries)
        m.apply_filter("return 42")
        assert len(m.history_lines) == 2
        assert m.history_lines[0] == "def foo():"
        assert m.history_lines[1] == "    return 42"

    def test_lines_starting_new_entries_correct_after_filter(self) -> None:
        entries = [
            "def foo():\n    return 1",
            "x = 10",
            "def bar():\n    return 2",
        ]
        m = _make_mapping(entries)
        m.apply_filter("def")
        assert 0 in m.lines_starting_new_entries
        assert 2 in m.lines_starting_new_entries
        assert len(m.lines_starting_new_entries) == 2

    def test_single_line_entries_unaffected(self) -> None:
        entries = ["a = 1", "b = 2", "c = 3"]
        m = _make_mapping(entries)
        m.apply_filter("b")
        assert m.history_lines == ["b = 2"]


# ---------------------------------------------------------------------------
# Display-to-original mapping
# ---------------------------------------------------------------------------


class TestDisplayOriginalMapping:
    def test_no_filter_maps_identity(self) -> None:
        m = _make_mapping(["a", "b", "c"])
        for i in range(3):
            assert m.display_to_original[i] == i
            assert m.original_to_display[i] == i

    def test_filter_maps_correctly(self) -> None:
        m = _make_mapping(["alpha", "beta", "gamma"])
        m.apply_filter("ph")
        # Only "alpha" (orig 0) matches "ph"
        assert len(m.display_to_original) == 1
        assert m.display_to_original[0] == 0
        assert m.original_to_display[0] == 0

    def test_multiline_filter_maps_correctly(self) -> None:
        entries = [
            "def foo():\n    pass",
            "x = 1",
            "def bar():\n    pass",
        ]
        m = _make_mapping(entries)
        m.apply_filter("def")
        # "def foo():\n    pass" -> orig lines 0,1
        # "def bar():\n    pass" -> orig lines 3,4
        assert m.display_to_original[0] == 0
        assert m.display_to_original[1] == 1
        assert m.display_to_original[2] == 3
        assert m.display_to_original[3] == 4

    def test_filtered_out_lines_not_in_original_to_display(self) -> None:
        m = _make_mapping(["alpha", "beta", "gamma"])
        m.apply_filter("ph")
        # Only "alpha" (orig 0) matches; "beta" (1) and "gamma" (2) filtered out
        assert 1 not in m.original_to_display
        assert 2 not in m.original_to_display


# ---------------------------------------------------------------------------
# Selection persistence across filter changes
# ---------------------------------------------------------------------------


class TestSelectionPersistence:
    def test_selections_survive_filter_change(self) -> None:
        m = _make_mapping(["alpha", "beta", "gamma"])
        m.selected_lines.add(0)  # select "alpha" (original index 0)
        m.selected_lines.add(2)  # select "gamma" (original index 2)

        m.apply_filter("beta")
        assert m.selected_lines == {0, 2}

    def test_selections_survive_filter_then_clear(self) -> None:
        m = _make_mapping(["alpha", "beta", "gamma"])
        m.selected_lines.add(1)  # select "beta"

        m.apply_filter("alpha")
        assert 1 not in m.original_to_display
        assert m.selected_lines == {1}

        m.apply_filter("")
        assert m.selected_lines == {1}
        assert 1 in m.original_to_display

    def test_hidden_selections_still_in_result(self) -> None:
        m = _make_mapping(["alpha", "beta", "gamma"])
        m.selected_lines.add(0)
        m.selected_lines.add(1)

        m.apply_filter("gamma")
        doc = m.get_new_document()
        assert "alpha" in doc.text
        assert "beta" in doc.text

    def test_select_while_filtered_uses_original_index(self) -> None:
        m = _make_mapping(["alpha", "beta", "gamma"])
        m.apply_filter("mm")
        # Only "gamma" (orig 2) matches "mm"
        assert len(m.history_lines) == 1
        original_idx = m.display_to_original[0]
        m.selected_lines.add(original_idx)
        assert 2 in m.selected_lines

        m.apply_filter("")
        assert 2 in m.selected_lines
        doc = m.get_new_document()
        assert "gamma" in doc.text


# ---------------------------------------------------------------------------
# Result document concatenation with original draft
# ---------------------------------------------------------------------------


class TestResultDocumentConcatenation:
    def test_no_original_text(self) -> None:
        m = _make_mapping(["alpha", "beta"], original_text="")
        m.selected_lines.add(0)
        m.selected_lines.add(1)
        doc = m.get_new_document()
        assert doc.text == "alpha\nbeta"

    def test_original_text_before_cursor(self) -> None:
        m = _make_mapping(
            ["alpha", "beta"],
            original_text="existing",
            cursor_pos=8,
        )
        m.selected_lines.add(0)
        doc = m.get_new_document()
        assert doc.text == "existing\nalpha"

    def test_original_text_after_cursor(self) -> None:
        m = _make_mapping(
            ["alpha"],
            original_text="before\nafter",
            cursor_pos=7,  # after the \n, so text_after_cursor = "after"
        )
        m.selected_lines.add(0)
        doc = m.get_new_document()
        assert doc.text == "before\n\nalpha\nafter"

    def test_filtered_selection_result_correct(self) -> None:
        entries = [
            "def foo():\n    return 1",
            "x = 10",
            "def bar():\n    return 2",
        ]
        m = _make_mapping(entries, original_text="draft", cursor_pos=5)

        m.apply_filter("foo")
        # Select both lines of "def foo(): ..." via display indices
        m.selected_lines.add(m.display_to_original[0])
        m.selected_lines.add(m.display_to_original[1])

        m.apply_filter("")
        doc = m.get_new_document()
        assert doc.text == "draft\ndef foo():\n    return 1"

    def test_multientry_selection_order_preserved(self) -> None:
        entries = ["c = 3", "a = 1", "b = 2"]
        m = _make_mapping(entries)
        m.selected_lines.add(0)
        m.selected_lines.add(2)
        doc = m.get_new_document()
        lines = doc.text.split("\n")
        assert lines[0] == "c = 3"
        assert lines[1] == "b = 2"

    def test_result_line_offset_with_multiline_original(self) -> None:
        m = _make_mapping(
            ["alpha"],
            original_text="line1\nline2\nline3",
            cursor_pos=11,  # end of "line2"
        )
        assert m.result_line_offset == 2

    def test_cursor_position_clamped(self) -> None:
        m = _make_mapping(["alpha"])
        m.selected_lines.add(0)
        doc = m.get_new_document(cursor_pos=99999)
        assert doc.cursor_position == len(doc.text)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_history(self) -> None:
        m = _make_mapping([])
        assert m.history_lines == []
        assert m.all_history_lines == []
        m.apply_filter("anything")
        assert m.history_lines == []

    def test_single_entry(self) -> None:
        m = _make_mapping(["only_one"])
        m.apply_filter("only")
        assert m.history_lines == ["only_one"]
        m.apply_filter("nope")
        assert m.history_lines == []

    def test_repeated_filter_same_result(self) -> None:
        m = _make_mapping(["alpha", "beta"])
        m.apply_filter("alpha")
        first = list(m.history_lines)
        m.apply_filter("alpha")
        assert m.history_lines == first

    def test_all_history_lines_immutable_across_filters(self) -> None:
        m = _make_mapping(["a", "b", "c"])
        original = list(m.all_history_lines)
        m.apply_filter("a")
        m.apply_filter("z")
        m.apply_filter("")
        assert m.all_history_lines == original

    def test_concatenated_history_matches_lines(self) -> None:
        m = _make_mapping(["def f():\n    pass", "x = 1"])
        m.apply_filter("f")
        assert m.concatenated_history == "\n".join(m.history_lines)
