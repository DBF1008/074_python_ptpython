from __future__ import annotations

import pytest
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.validation import ValidationError

from ptpython.utils import (
    has_unclosed_brackets,
    document_is_multiline_python,
    unindent_code,
    unindent_code_with_prefix,
    _cursor_in_string,
    _ends_in_unclosed_triple_string,
    _strip_string_literals,
)
from ptpython.validator import PythonValidator


class TestStripStringLiterals:
    def test_single_quoted(self):
        assert _strip_string_literals("x = 'hello'") == "x = "

    def test_double_quoted(self):
        assert _strip_string_literals('x = "hello"') == "x = "

    def test_triple_double_quoted(self):
        assert _strip_string_literals('x = """hello"""') == "x = "

    def test_triple_single_quoted(self):
        assert _strip_string_literals("x = '''hello'''") == "x = "

    def test_escaped_quote_in_single(self):
        assert _strip_string_literals(r"x = 'it\'s'") == "x = "

    def test_escaped_quote_in_double(self):
        assert _strip_string_literals(r'x = "say \"hi\""') == "x = "

    def test_unclosed_triple_quote(self):
        assert _strip_string_literals('x = """hello') == "x = "

    def test_brackets_inside_triple_string_removed(self):
        result = _strip_string_literals('print("""text ( bracket""")')
        assert "(" not in result or result.count("(") == result.count(")")

    def test_multiline_triple_string(self):
        text = '"""line1\nline2\nline3"""'
        assert _strip_string_literals(text) == ""


class TestHasUnclosedBrackets:
    def test_simple_unclosed_paren(self):
        assert has_unclosed_brackets("foo(") is True

    def test_matched_parens(self):
        assert has_unclosed_brackets("foo()") is False

    def test_brackets_inside_single_line_string(self):
        assert has_unclosed_brackets('x = "text with ("') is False

    def test_brackets_inside_triple_double_quoted_string(self):
        assert has_unclosed_brackets('print("""text with ( bracket""")') is False

    def test_brackets_inside_triple_single_quoted_string(self):
        assert has_unclosed_brackets("print('''text with [ bracket''')") is False

    def test_unclosed_bracket_outside_triple_string(self):
        assert has_unclosed_brackets('d = {"""key"""') is True

    def test_escaped_quotes_in_string(self):
        assert has_unclosed_brackets(r"x = 'it\'s a (test)'") is False

    def test_nested_brackets(self):
        assert has_unclosed_brackets("foo([{") is True

    def test_mixed_string_and_unclosed_bracket(self):
        assert has_unclosed_brackets('foo("bar", [1, 2') is True

    def test_complete_dict_literal(self):
        assert has_unclosed_brackets('{"key": "value"}') is False

    def test_no_brackets(self):
        assert has_unclosed_brackets("x = 42") is False

    def test_empty_string(self):
        assert has_unclosed_brackets("") is False

    def test_bracket_in_multiline_triple_string(self):
        text = '"""\nfoo(\nbar\n"""'
        assert has_unclosed_brackets(text) is False

    def test_mixed_quotes_with_brackets(self):
        assert has_unclosed_brackets("""x = "a(b" + 'c)d'""") is False


class TestEndsInUnclosedTripleString:
    def test_unclosed_triple_double(self):
        assert _ends_in_unclosed_triple_string('x = """hello') is True

    def test_closed_triple_double(self):
        assert _ends_in_unclosed_triple_string('x = """hello"""') is False

    def test_unclosed_triple_single(self):
        assert _ends_in_unclosed_triple_string("x = '''hello") is True

    def test_closed_triple_single(self):
        assert _ends_in_unclosed_triple_string("x = '''hello'''") is False

    def test_triple_quote_inside_single_line_string(self):
        assert _ends_in_unclosed_triple_string('x = \'"""\'') is False

    def test_no_strings(self):
        assert _ends_in_unclosed_triple_string("x = 42") is False

    def test_empty(self):
        assert _ends_in_unclosed_triple_string("") is False

    def test_multiline_unclosed(self):
        assert _ends_in_unclosed_triple_string('x = """\nhello\nworld') is True

    def test_multiline_closed(self):
        assert _ends_in_unclosed_triple_string('x = """\nhello\n"""') is False

    def test_empty_triple_string(self):
        assert _ends_in_unclosed_triple_string('x = """"""') is False

    def test_single_line_string_at_end(self):
        assert _ends_in_unclosed_triple_string('x = "hello"') is False

    def test_text_after_closed_triple(self):
        assert _ends_in_unclosed_triple_string('x = """hi""" + y') is False


class TestCursorInString:
    def test_cursor_before_string(self):
        assert _cursor_in_string('x = "hello"', 0) is False

    def test_cursor_at_equals(self):
        assert _cursor_in_string('x = "hello"', 2) is False

    def test_cursor_inside_double_quoted(self):
        assert _cursor_in_string('x = "hello"', 6) is True

    def test_cursor_inside_triple_quoted(self):
        assert _cursor_in_string('x = """description:', 15) is True

    def test_cursor_at_end_of_unclosed_triple(self):
        text = 'x = """line with:'
        assert _cursor_in_string(text, len(text)) is True

    def test_cursor_after_closed_string(self):
        assert _cursor_in_string('x = "hello" + y', 14) is False

    def test_cursor_at_opening_quote(self):
        assert _cursor_in_string('x = "hello"', 4) is False

    def test_cursor_at_closing_quote(self):
        assert _cursor_in_string('x = "hello"', 10) is True

    def test_cursor_in_multiline_triple_string(self):
        text = 'x = """\nhello\nworld'
        assert _cursor_in_string(text, 12) is True

    def test_cursor_outside_all_strings(self):
        text = '"a" + "b"'
        assert _cursor_in_string(text, 4) is False


class TestDocumentIsMultilinePython:
    def test_complete_expr_with_triple_string_brackets(self):
        text = 'print("""text with ( bracket""")'
        doc = Document(text, cursor_position=len(text))
        assert document_is_multiline_python(doc) is False

    def test_unclosed_triple_string(self):
        text = 'x = """hello'
        doc = Document(text, cursor_position=len(text))
        assert document_is_multiline_python(doc) is True

    def test_decorator_still_multiline(self):
        text = "@decorator"
        doc = Document(text, cursor_position=len(text))
        assert document_is_multiline_python(doc) is True

    def test_colon_at_end_still_multiline(self):
        text = "if True:"
        doc = Document(text, cursor_position=len(text))
        assert document_is_multiline_python(doc) is True

    def test_backslash_continuation_still_multiline(self):
        text = "x = 1 + \\"
        doc = Document(text, cursor_position=len(text))
        assert document_is_multiline_python(doc) is True

    def test_simple_assignment_not_multiline(self):
        text = "x = 42"
        doc = Document(text, cursor_position=len(text))
        assert document_is_multiline_python(doc) is False

    def test_unclosed_paren_multiline(self):
        text = "foo("
        doc = Document(text, cursor_position=len(text))
        assert document_is_multiline_python(doc) is True

    def test_closed_paren_not_multiline(self):
        text = "foo()"
        doc = Document(text, cursor_position=len(text))
        assert document_is_multiline_python(doc) is False

    def test_triple_string_with_colon_complete(self):
        text = 'x = """key: value"""'
        doc = Document(text, cursor_position=len(text))
        assert document_is_multiline_python(doc) is False

    def test_existing_newline_is_multiline(self):
        text = "x = 1\ny = 2"
        doc = Document(text, cursor_position=len(text))
        assert document_is_multiline_python(doc) is True

    def test_triple_quote_in_single_string_not_multiline(self):
        text = 'x = \'"""\''
        doc = Document(text, cursor_position=len(text))
        assert document_is_multiline_python(doc) is False


class TestAutoNewline:
    def _make_buffer(self, text, cursor_position=None):
        if cursor_position is None:
            cursor_position = len(text)
        buf = Buffer()
        buf.set_document(Document(text, cursor_position), bypass_readonly=True)
        return buf

    def test_colon_adds_indent(self):
        from ptpython.key_bindings import auto_newline

        buf = self._make_buffer("if True:")
        auto_newline(buf)
        assert buf.text == "if True:\n    "

    def test_no_extra_indent_inside_triple_string_with_colon(self):
        from ptpython.key_bindings import auto_newline

        text = '"""\ndescription:'
        buf = self._make_buffer(text)
        auto_newline(buf)
        assert "        " not in buf.text
        assert buf.text == '"""\ndescription:\n'

    def test_no_dedent_for_pass_inside_triple_string(self):
        from ptpython.key_bindings import auto_newline

        text = '"""\n    some pass'
        buf = self._make_buffer(text)
        auto_newline(buf)
        lines = buf.text.split("\n")
        last_line = lines[-1]
        assert last_line == "    "

    def test_normal_pass_dedent(self):
        from ptpython.key_bindings import auto_newline

        buf = self._make_buffer("    pass")
        auto_newline(buf)
        assert buf.text == "    pass\n"

    def test_plain_newline_in_middle(self):
        from ptpython.key_bindings import auto_newline

        buf = self._make_buffer("hello world", cursor_position=5)
        auto_newline(buf)
        assert buf.text == "hello\n world"

    def test_indentation_preserved(self):
        from ptpython.key_bindings import auto_newline

        buf = self._make_buffer("    x = 1")
        auto_newline(buf)
        assert buf.text == "    x = 1\n    "


class TestValidatorErrorPosition:
    def test_error_position_with_indented_code(self):
        text = "    x = 1\n    y = +"
        doc = Document(text, cursor_position=len(text))
        validator = PythonValidator()
        with pytest.raises(ValidationError) as exc_info:
            validator.validate(doc)
        error = exc_info.value
        assert error.cursor_position > len("    x = 1\n")

    def test_error_position_no_indent(self):
        text = "x = +"
        doc = Document(text, cursor_position=len(text))
        validator = PythonValidator()
        with pytest.raises(ValidationError):
            validator.validate(doc)

    def test_valid_code_passes(self):
        text = "    x = 1\n    y = 2"
        doc = Document(text, cursor_position=len(text))
        validator = PythonValidator()
        validator.validate(doc)

    def test_valid_single_line(self):
        text = "x = 42"
        doc = Document(text, cursor_position=len(text))
        validator = PythonValidator()
        validator.validate(doc)

    def test_error_on_correct_line(self):
        text = "    a = 1\n    b = 2\n    c = )"
        doc = Document(text, cursor_position=len(text))
        validator = PythonValidator()
        with pytest.raises(ValidationError) as exc_info:
            validator.validate(doc)
        error = exc_info.value
        third_line_start = len("    a = 1\n    b = 2\n")
        assert error.cursor_position >= third_line_start


class TestUnindentCodeWithPrefix:
    def test_returns_prefix_length(self):
        text = "    x = 1\n    y = 2"
        result, prefix_len = unindent_code_with_prefix(text)
        assert prefix_len == 4
        assert result == "x = 1\ny = 2"

    def test_no_common_prefix(self):
        text = "x = 1\ny = 2"
        result, prefix_len = unindent_code_with_prefix(text)
        assert prefix_len == 0
        assert result == text

    def test_mixed_indent(self):
        text = "    x = 1\n        y = 2"
        result, prefix_len = unindent_code_with_prefix(text)
        assert prefix_len == 4
        assert result == "x = 1\n    y = 2"

    def test_single_line(self):
        text = "    x = 1"
        result, prefix_len = unindent_code_with_prefix(text)
        assert prefix_len == 4
        assert result == "x = 1"

    def test_empty_string(self):
        result, prefix_len = unindent_code_with_prefix("")
        assert prefix_len == 0
        assert result == ""

    def test_unindent_code_unchanged(self):
        text = "    x = 1\n    y = 2"
        assert unindent_code(text) == "x = 1\ny = 2"
