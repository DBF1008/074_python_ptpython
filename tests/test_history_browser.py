"""
Regression tests for the history browser (F3).

Covers: truncation at statement boundaries, get_new_document draft
preservation, result_line_offset consistency, and GrayExistingText
alignment.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text.base import OneStyleAndTextTuple
from prompt_toolkit.layout.processors import TransformationInput

from ptpython.history_browser import (
    HISTORY_COUNT,
    GrayExistingText,
    HistoryMapping,
)


def _make_mapping(
    entries: list[str],
    original_text: str = "",
    cursor_position: int | None = None,
) -> HistoryMapping:
    if cursor_position is None:
        cursor_position = len(original_text)
    doc = Document(original_text, cursor_position)
    mock_python_history = MagicMock()
    mock_python_history.get_strings.return_value = entries
    mock_history = MagicMock()
    return HistoryMapping(mock_history, mock_python_history, doc)


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


class TestTruncation:
    def test_no_truncation_keeps_all_entries(self) -> None:
        entries = ["print(1)", "print(2)", "x = 3"]
        m = _make_mapping(entries)
        assert len(m.lines_starting_new_entries) == 3
        assert m.history_lines == ["print(1)", "print(2)", "x = 3"]

    def test_multiline_entry_no_truncation(self) -> None:
        entries = ["def foo():\n    pass", "x = 1"]
        m = _make_mapping(entries)
        assert m.history_lines == ["def foo():", "    pass", "x = 1"]
        assert 0 in m.lines_starting_new_entries
        assert 2 in m.lines_starting_new_entries

    def test_truncation_inserts_separate_message(self) -> None:
        """Truncation message should be a standalone entry, not replace a
        line from a real history entry."""
        n = HISTORY_COUNT + 5
        entries = [f"line_{i}" for i in range(n)]
        m = _make_mapping(entries)

        assert m.history_lines[0].startswith("# *** History has been truncated")
        assert 0 in m.lines_starting_new_entries
        assert m.history_lines[1] == f"line_{n - HISTORY_COUNT}"
        assert 1 in m.lines_starting_new_entries

    def test_truncation_preserves_multiline_boundary(self) -> None:
        """When the first retained entry is multiline, ALL its lines must
        survive intact — the truncation message must not overwrite any."""
        multiline_first = "def hello():\n    print('hi')\n    return 42"
        skipped = [f"skip_{i}" for i in range(3)]
        remaining = [f"fill_{i}" for i in range(HISTORY_COUNT - 1)]
        entries = skipped + [multiline_first] + remaining
        m = _make_mapping(entries)

        assert m.history_lines[0].startswith("# ***")
        idx = 1
        assert idx in m.lines_starting_new_entries
        assert m.history_lines[idx] == "def hello():"
        assert m.history_lines[idx + 1] == "    print('hi')"
        assert m.history_lines[idx + 2] == "    return 42"
        assert (idx + 1) not in m.lines_starting_new_entries
        assert (idx + 2) not in m.lines_starting_new_entries

    def test_truncation_message_counted_as_entry(self) -> None:
        n = HISTORY_COUNT + 1
        entries = [f"l{i}" for i in range(n)]
        m = _make_mapping(entries)
        assert 0 in m.lines_starting_new_entries
        assert 1 in m.lines_starting_new_entries


# ---------------------------------------------------------------------------
# result_line_offset
# ---------------------------------------------------------------------------


class TestResultLineOffset:
    def test_empty_before(self) -> None:
        m = _make_mapping(["x = 1"], original_text="", cursor_position=0)
        assert m.result_line_offset == 0

    def test_before_no_trailing_newline(self) -> None:
        m = _make_mapping(["x = 1"], original_text="draft", cursor_position=5)
        assert m.result_line_offset == 1

    def test_before_trailing_newline(self) -> None:
        m = _make_mapping(
            ["x = 1"], original_text="draft\n", cursor_position=6
        )
        assert m.result_line_offset == 1

    def test_multiline_before_cursor_mid(self) -> None:
        text = "a = 1\nb = 2"
        m = _make_mapping(["x"], original_text=text, cursor_position=len(text))
        assert m.result_line_offset == 2

    def test_multiline_before_cursor_at_newline(self) -> None:
        text = "a = 1\nb = 2\n"
        m = _make_mapping(["x"], original_text=text, cursor_position=len(text))
        assert m.result_line_offset == 2


# ---------------------------------------------------------------------------
# get_new_document — draft preservation
# ---------------------------------------------------------------------------


class TestGetNewDocument:
    def test_no_selection_empty_draft(self) -> None:
        m = _make_mapping(["x = 1"], original_text="", cursor_position=0)
        doc = m.get_new_document()
        assert doc.text == ""

    def test_no_selection_preserves_draft_exactly(self) -> None:
        original = "hello\nworld"
        m = _make_mapping(["x"], original_text=original, cursor_position=5)
        doc = m.get_new_document()
        assert doc.text == original

    def test_no_selection_cursor_at_newline(self) -> None:
        original = "a = 1\nb = 2"
        m = _make_mapping(["x"], original_text=original, cursor_position=6)
        doc = m.get_new_document()
        assert doc.text == original

    def test_no_selection_trailing_newline(self) -> None:
        original = "a = 1\n"
        m = _make_mapping(["x"], original_text=original, cursor_position=6)
        doc = m.get_new_document()
        assert doc.text == original

    def test_selection_with_empty_draft(self) -> None:
        m = _make_mapping(["alpha", "beta"], original_text="", cursor_position=0)
        m.selected_lines.add(0)
        doc = m.get_new_document()
        assert doc.text == "alpha"

    def test_selection_before_no_trailing_newline(self) -> None:
        m = _make_mapping(
            ["alpha", "beta"], original_text="draft", cursor_position=5
        )
        m.selected_lines.add(0)
        doc = m.get_new_document()
        assert doc.text == "draft\nalpha"

    def test_selection_before_trailing_newline(self) -> None:
        m = _make_mapping(
            ["alpha", "beta"], original_text="draft\n", cursor_position=6
        )
        m.selected_lines.add(0)
        doc = m.get_new_document()
        assert doc.text == "draft\nalpha"

    def test_selection_with_after(self) -> None:
        original = "before\nafter"
        m = _make_mapping(
            ["alpha"], original_text=original, cursor_position=6
        )
        m.selected_lines.add(0)
        doc = m.get_new_document()
        assert doc.text == "before\nalpha\nafter"

    def test_selection_cursor_at_newline_with_after(self) -> None:
        original = "x = 1\ny = 2"
        m = _make_mapping(["sel"], original_text=original, cursor_position=6)
        m.selected_lines.add(0)
        doc = m.get_new_document()
        assert doc.text == "x = 1\nsel\ny = 2"

    def test_multiple_selections(self) -> None:
        m = _make_mapping(
            ["a", "b", "c"], original_text="", cursor_position=0
        )
        m.selected_lines.update({0, 2})
        doc = m.get_new_document()
        assert doc.text == "a\nc"

    def test_cursor_pos_clamped(self) -> None:
        m = _make_mapping(["x"], original_text="hi", cursor_position=2)
        doc = m.get_new_document(cursor_pos=9999)
        assert doc.cursor_position == len(doc.text)


# ---------------------------------------------------------------------------
# Preview / backfill consistency
# ---------------------------------------------------------------------------


class TestPreviewBackfillConsistency:
    """The text shown in the right-side preview (default_buffer) must be
    identical to what gets backfilled into the REPL on Enter."""

    def _get_preview_text(self, m: HistoryMapping) -> str:
        return m.get_new_document().text

    def test_multiline_entry_selected(self) -> None:
        entries = ["def foo():\n    pass", "x = 1"]
        m = _make_mapping(entries, original_text="", cursor_position=0)
        m.selected_lines.update({0, 1})
        text = self._get_preview_text(m)
        assert text == "def foo():\n    pass"

    def test_multiline_with_draft(self) -> None:
        entries = ["for i in range(10):\n    print(i)"]
        m = _make_mapping(
            entries, original_text="result = []", cursor_position=11
        )
        m.selected_lines.update({0, 1})
        text = self._get_preview_text(m)
        assert text == "result = []\nfor i in range(10):\n    print(i)"

    def test_selected_lines_match_preview_lines(self) -> None:
        entries = ["line_a", "line_b", "line_c"]
        m = _make_mapping(entries, original_text="pre", cursor_position=3)
        m.selected_lines.update({0, 2})

        doc = m.get_new_document()
        result_lines = doc.text.split("\n")
        offset = m.result_line_offset

        assert result_lines[offset] == "line_a"
        assert result_lines[offset + 1] == "line_c"


# ---------------------------------------------------------------------------
# GrayExistingText alignment with result_line_offset
# ---------------------------------------------------------------------------


class TestGrayExistingText:
    @staticmethod
    def _make_ti(
        lineno: int, text: str = "some code"
    ) -> TransformationInput:
        fragments: list[OneStyleAndTextTuple] = [("", text)]
        return TransformationInput(
            buffer_control=MagicMock(),
            document=MagicMock(),
            lineno=lineno,
            source_to_display=lambda i: i,
            fragments=fragments,
            width=80,
            height=24,
        )

    def test_gray_before_selected_region(self) -> None:
        m = _make_mapping(
            ["alpha"], original_text="draft\n", cursor_position=6
        )
        m.selected_lines.add(0)
        proc = GrayExistingText(m)

        ti = self._make_ti(0)
        result = proc.apply_transformation(ti)
        assert result.fragments[0][0] == "class:history.existing-input"

    def test_selected_region_not_grayed(self) -> None:
        m = _make_mapping(
            ["alpha"], original_text="draft\n", cursor_position=6
        )
        m.selected_lines.add(0)
        proc = GrayExistingText(m)

        ti = self._make_ti(m.result_line_offset)
        result = proc.apply_transformation(ti)
        assert result.fragments[0][0] == ""

    def test_gray_after_selected_region(self) -> None:
        m = _make_mapping(
            ["alpha"], original_text="before\nafter", cursor_position=6
        )
        m.selected_lines.add(0)
        proc = GrayExistingText(m)

        after_line = m.result_line_offset + len(m.selected_lines)
        ti = self._make_ti(after_line)
        result = proc.apply_transformation(ti)
        assert result.fragments[0][0] == "class:history.existing-input"

    def test_offset_matches_between_gray_and_margin(self) -> None:
        for text, cpos in [
            ("x", 1),
            ("x\n", 2),
            ("a\nb", 3),
            ("a\nb\n", 4),
        ]:
            m = _make_mapping(["sel"], original_text=text, cursor_position=cpos)
            m.selected_lines.add(0)
            proc = GrayExistingText(m)

            doc = m.get_new_document()
            result_lines = doc.text.split("\n")
            assert result_lines[m.result_line_offset] == "sel"

            ti_before = self._make_ti(m.result_line_offset - 1) if m.result_line_offset > 0 else None
            ti_at = self._make_ti(m.result_line_offset)

            if ti_before:
                r = proc.apply_transformation(ti_before)
                assert r.fragments[0][0] == "class:history.existing-input"

            r = proc.apply_transformation(ti_at)
            assert r.fragments[0][0] == ""
