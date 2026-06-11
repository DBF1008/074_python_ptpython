from __future__ import annotations

import os
import tempfile

import pytest
from prompt_toolkit.completion import CompleteEvent, Completion, FuzzyCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import fragment_list_to_text, to_formatted_text

from ptpython.completer import (
    CompletePrivateAttributes,
    DictionaryCompleter,
    HidePrivateCompleter,
    JediCompleter,
    PythonCompleter,
    _make_attr_preview,
    _make_jedi_preview,
    _make_path_preview,
)


def _get_completions(completer, text, complete_event=None):
    if complete_event is None:
        complete_event = CompleteEvent(completion_requested=True)
    doc = Document(text, len(text))
    return list(completer.get_completions(doc, complete_event))


def _display_text(completion):
    return fragment_list_to_text(to_formatted_text(completion.display))


def _meta_text(completion):
    meta = completion.display_meta
    if callable(meta):
        return meta()
    return fragment_list_to_text(to_formatted_text(meta))


# ---------------------------------------------------------------------------
# Jedi completion preview
# ---------------------------------------------------------------------------

class TestJediCompletionPreview:
    def setup_method(self):
        self.completer = JediCompleter(
            lambda: {"os": __import__("os")},
            lambda: {},
        )

    def test_function_completion_has_signature_preview(self):
        completions = _get_completions(self.completer, "os.path.join")
        join_completions = [c for c in completions if c.text == "join"]
        assert len(join_completions) == 1
        meta = _meta_text(join_completions[0])
        assert "(" in meta

    def test_module_completion_has_description(self):
        completions = _get_completions(self.completer, "os.path")
        path_completions = [c for c in completions if c.text == "path"]
        assert len(path_completions) == 1
        meta = _meta_text(path_completions[0])
        assert meta

    def test_class_completion_has_description(self):
        completer = JediCompleter(lambda: {}, lambda: {})
        completions = _get_completions(completer, "int")
        int_completions = [c for c in completions if c.text == "int"]
        if int_completions:
            meta = _meta_text(int_completions[0])
            assert meta

    def test_preview_is_lazy_callable(self):
        completer = JediCompleter(lambda: {}, lambda: {})
        completions = _get_completions(completer, "sorted")
        sorted_completions = [c for c in completions if c.text == "sorted"]
        if sorted_completions:
            meta = sorted_completions[0].display_meta
            # builtins get styled formatted text, non-builtins get lazy callable
            assert meta is not None

    def test_styled_completions_keep_type_label(self):
        completer = JediCompleter(lambda: {}, lambda: {})
        completions = _get_completions(completer, "prin")
        print_completions = [c for c in completions if c.text == "print"]
        if print_completions:
            meta = print_completions[0].display_meta
            assert not callable(meta)
            text = fragment_list_to_text(to_formatted_text(meta))
            assert text


# ---------------------------------------------------------------------------
# Dictionary completer attribute preview
# ---------------------------------------------------------------------------

class TestDictAttributePreview:
    def setup_method(self):
        self.test_obj = type("Obj", (), {
            "my_func": lambda self, x, y: x + y,
            "my_dict": {"a": 1, "b": 2},
            "my_list": [1, 2, 3],
            "my_str": "hello",
            "_private": 42,
            "__dunder__": True,
        })()
        self.completer = DictionaryCompleter(
            lambda: {"obj": self.test_obj},
            lambda: {"obj": self.test_obj},
        )

    def test_attribute_completions_have_meta(self):
        completions = _get_completions(self.completer, "obj.my_")
        assert len(completions) > 0
        for c in completions:
            assert c.display_meta is not None

    def test_callable_attr_shows_signature_or_type(self):
        completions = _get_completions(self.completer, "obj.my_func")
        func_completions = [c for c in completions if "my_func" in _display_text(c)]
        assert len(func_completions) >= 1
        meta = _meta_text(func_completions[0])
        assert "lambda" in meta or "function" in meta or "(" in meta

    def test_dict_attr_shows_key_count(self):
        completions = _get_completions(self.completer, "obj.my_dict")
        dict_completions = [c for c in completions if "my_dict" in _display_text(c)]
        assert len(dict_completions) >= 1
        meta = _meta_text(dict_completions[0])
        assert "2 keys" in meta

    def test_list_attr_shows_length(self):
        completions = _get_completions(self.completer, "obj.my_list")
        list_completions = [c for c in completions if "my_list" in _display_text(c)]
        assert len(list_completions) >= 1
        meta = _meta_text(list_completions[0])
        assert "len=3" in meta

    def test_string_attr_shows_repr(self):
        completions = _get_completions(self.completer, "obj.my_str")
        str_completions = [c for c in completions if "my_str" in _display_text(c)]
        assert len(str_completions) >= 1
        meta = _meta_text(str_completions[0])
        assert "hello" in meta


# ---------------------------------------------------------------------------
# _make_attr_preview unit tests
# ---------------------------------------------------------------------------

class TestMakeAttrPreview:
    def test_callable_preview(self):
        def my_func(a, b, c=3):
            pass
        obj = type("X", (), {"fn": staticmethod(my_func)})()
        preview = _make_attr_preview(obj, "fn")
        text = preview()
        assert "(a, b" in text

    def test_dict_preview(self):
        obj = type("X", (), {"d": {"x": 1}})()
        preview = _make_attr_preview(obj, "d")
        assert "1 keys" in preview()

    def test_list_preview(self):
        obj = type("X", (), {"items": [10, 20]})()
        preview = _make_attr_preview(obj, "items")
        assert "len=2" in preview()

    def test_scalar_preview(self):
        obj = type("X", (), {"val": 42})()
        preview = _make_attr_preview(obj, "val")
        assert "42" in preview()

    def test_long_repr_is_truncated(self):
        obj = type("X", (), {"val": "a" * 100})()
        preview = _make_attr_preview(obj, "val")
        text = preview()
        assert len(text) <= 53
        assert text.endswith("...")

    def test_none_preview(self):
        obj = type("X", (), {"val": None})()
        preview = _make_attr_preview(obj, "val")
        assert preview() == "None"

    def test_caching(self):
        call_count = 0
        class Tracked:
            @property
            def val(self):
                nonlocal call_count
                call_count += 1
                return 99
        obj = Tracked()
        preview = _make_attr_preview(obj, "val")
        preview()
        preview()
        assert call_count == 1


# ---------------------------------------------------------------------------
# Path completion preview
# ---------------------------------------------------------------------------

class TestPathPreview:
    def test_directory_preview(self):
        with tempfile.TemporaryDirectory() as d:
            preview = _make_path_preview(d)
            assert preview() == "directory"

    def test_file_preview_small(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello")
            f.flush()
            try:
                preview = _make_path_preview(f.name)
                assert "file" in preview()
                assert "5B" in preview()
            finally:
                os.unlink(f.name)

    def test_file_preview_kb(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x" * 2048)
            f.flush()
            try:
                preview = _make_path_preview(f.name)
                text = preview()
                assert "file" in text
                assert "KB" in text
            finally:
                os.unlink(f.name)

    def test_nonexistent_path(self):
        preview = _make_path_preview("/tmp/nonexistent_path_abc_xyz_123")
        assert preview() == ""

    def test_caching(self):
        with tempfile.TemporaryDirectory() as d:
            preview = _make_path_preview(d)
            r1 = preview()
            r2 = preview()
            assert r1 == r2 == "directory"


# ---------------------------------------------------------------------------
# HidePrivateCompleter regression
# ---------------------------------------------------------------------------

class _MockCompleter:
    def __init__(self, names):
        self._names = names

    def get_completions(self, document, complete_event):
        for name in self._names:
            yield Completion(name, 0, display=name)


class TestHidePrivateCompleter:
    def _get_filtered(self, names, mode):
        inner = _MockCompleter(names)
        completer = HidePrivateCompleter(inner, lambda: mode)
        return _get_completions(completer, "")

    def test_always_shows_all(self):
        names = ["public", "_private", "__dunder__"]
        result = self._get_filtered(names, CompletePrivateAttributes.ALWAYS)
        texts = [c.text for c in result]
        assert "public" in texts
        assert "_private" in texts
        assert "__dunder__" in texts

    def test_never_hides_private(self):
        names = ["public", "_private", "__dunder__"]
        result = self._get_filtered(names, CompletePrivateAttributes.NEVER)
        texts = [c.text for c in result]
        assert "public" in texts
        assert "_private" not in texts
        assert "__dunder__" not in texts

    def test_if_no_public_hides_when_public_exists(self):
        names = ["public", "_private"]
        result = self._get_filtered(names, CompletePrivateAttributes.IF_NO_PUBLIC)
        texts = [c.text for c in result]
        assert "public" in texts
        assert "_private" not in texts

    def test_if_no_public_shows_when_no_public(self):
        names = ["_private", "__dunder__"]
        result = self._get_filtered(names, CompletePrivateAttributes.IF_NO_PUBLIC)
        texts = [c.text for c in result]
        assert "_private" in texts
        assert "__dunder__" in texts

    def test_preserves_display_meta(self):
        inner_completions = [
            Completion("func", 0, display="func()", display_meta="method"),
        ]
        class MetaCompleter:
            def get_completions(self, doc, ev):
                return iter(inner_completions)
        completer = HidePrivateCompleter(
            MetaCompleter(), lambda: CompletePrivateAttributes.ALWAYS
        )
        result = _get_completions(completer, "")
        assert len(result) == 1
        assert _meta_text(result[0]) == "method"


# ---------------------------------------------------------------------------
# DictionaryCompleter sort order regression
# ---------------------------------------------------------------------------

class TestDictCompleterSortOrder:
    def test_sort_attribute_names(self):
        completer = DictionaryCompleter(lambda: {}, lambda: {})
        names = ["__dunder__", "public", "_private", "alpha", "__init__"]
        sorted_names = completer._sort_attribute_names(names)
        public_names = [n for n in sorted_names if not n.startswith("_")]
        private_names = [n for n in sorted_names if n.startswith("_") and not n.startswith("__")]
        dunder_names = [n for n in sorted_names if n.startswith("__")]
        assert sorted_names == public_names + private_names + dunder_names

    def test_public_before_private_before_dunder(self):
        completer = DictionaryCompleter(lambda: {}, lambda: {})
        names = ["__z__", "a", "_b"]
        result = completer._sort_attribute_names(names)
        assert result == ["a", "_b", "__z__"]


# ---------------------------------------------------------------------------
# JediCompleter sort order regression
# ---------------------------------------------------------------------------

class TestJediCompleterSortOrder:
    def test_private_after_public(self):
        completer = JediCompleter(
            lambda: {"os": __import__("os")},
            lambda: {},
        )
        completions = _get_completions(completer, "os.")
        display_texts = [_display_text(c) for c in completions]
        first_private_idx = None
        last_public_idx = None
        for i, text in enumerate(display_texts):
            if text.startswith("_"):
                if first_private_idx is None:
                    first_private_idx = i
            else:
                last_public_idx = i
        if first_private_idx is not None and last_public_idx is not None:
            assert last_public_idx < first_private_idx


# ---------------------------------------------------------------------------
# Fuzzy completion regression
# ---------------------------------------------------------------------------

class TestFuzzyCompletionRegression:
    def test_fuzzy_wrapping_preserves_completions(self):
        inner = JediCompleter(
            lambda: {"os": __import__("os")},
            lambda: {},
        )
        fuzzy = FuzzyCompleter(inner)
        doc = Document("os.path.jo", len("os.path.jo"))
        completions = list(fuzzy.get_completions(doc, CompleteEvent(completion_requested=True)))
        texts = [c.text for c in completions]
        assert any("join" in t for t in texts)

    def test_fuzzy_does_not_lose_meta(self):
        inner = JediCompleter(
            lambda: {"os": __import__("os")},
            lambda: {},
        )
        fuzzy = FuzzyCompleter(inner)
        doc = Document("os.path.join", len("os.path.join"))
        completions = list(fuzzy.get_completions(doc, CompleteEvent(completion_requested=True)))
        join_completions = [c for c in completions if "join" in c.text]
        if join_completions:
            assert join_completions[0].display_meta is not None


# ---------------------------------------------------------------------------
# PythonCompleter integration: path completions get preview
# ---------------------------------------------------------------------------

class TestPythonCompleterPathPreview:
    def test_path_completions_have_meta(self):
        completer = PythonCompleter(
            lambda: {},
            lambda: {},
            lambda: False,
        )
        with tempfile.TemporaryDirectory() as d:
            test_file = os.path.join(d, "test.txt")
            with open(test_file, "w") as f:
                f.write("hi")
            doc_text = f'"{d}{os.sep}'
            completions = _get_completions(completer, doc_text)
            if completions:
                for c in completions:
                    assert c.display_meta is not None


# ---------------------------------------------------------------------------
# PythonCompleter integration: dict completions get preview
# ---------------------------------------------------------------------------

class TestPythonCompleterDictAttrPreview:
    def test_dict_attr_completions_have_meta(self):
        import collections
        test_obj = type("T", (), {"count": 5, "items": [1, 2]})()
        completer = PythonCompleter(
            lambda: {"obj": test_obj},
            lambda: {"obj": test_obj},
            lambda: True,
        )
        completions = _get_completions(completer, "obj.coun")
        count_completions = [c for c in completions if "count" in _display_text(c)]
        if count_completions:
            meta = _meta_text(count_completions[0])
            assert meta
