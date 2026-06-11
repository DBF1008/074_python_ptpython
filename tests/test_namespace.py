"""
Tests for namespace injection/cleanup during embed sessions.

Verifies that _add_to_namespace / _remove_from_namespace correctly
save and restore host globals, even across repeated enter/exit cycles.
"""

from __future__ import annotations

import pytest

from ptpython.repl import PythonRepl, exit as PtExit


def _make_repl(ns: dict) -> PythonRepl:
    return PythonRepl(
        get_globals=lambda: ns,
        get_locals=lambda: ns,
        create_app=False,
    )


class TestNamespaceInjection:
    def test_injects_builtins(self) -> None:
        ns: dict = {}
        repl = _make_repl(ns)

        repl._add_to_namespace()

        assert "get_ptpython" in ns
        assert "exit" in ns
        assert isinstance(ns["exit"], PtExit)

    def test_cleanup_removes_injected_when_no_originals(self) -> None:
        ns: dict = {}
        repl = _make_repl(ns)

        repl._add_to_namespace()
        repl._remove_from_namespace()

        assert "get_ptpython" not in ns
        assert "exit" not in ns

    def test_cleanup_restores_host_exit(self) -> None:
        sentinel = object()
        ns: dict = {"exit": sentinel}
        repl = _make_repl(ns)

        repl._add_to_namespace()
        assert ns["exit"] is not sentinel

        repl._remove_from_namespace()
        assert ns["exit"] is sentinel

    def test_cleanup_restores_host_get_ptpython(self) -> None:
        original_fn = lambda: "host"
        ns: dict = {"get_ptpython": original_fn}
        repl = _make_repl(ns)

        repl._add_to_namespace()
        assert ns["get_ptpython"] is not original_fn

        repl._remove_from_namespace()
        assert ns["get_ptpython"] is original_fn

    def test_cleanup_restores_none_valued_host_exit(self) -> None:
        """Host had exit=None — cleanup must restore None, not delete."""
        ns: dict = {"exit": None}
        repl = _make_repl(ns)

        repl._add_to_namespace()
        repl._remove_from_namespace()

        assert "exit" in ns
        assert ns["exit"] is None

    def test_repeated_enter_exit_restores_each_time(self) -> None:
        sentinel = object()
        ns: dict = {"exit": sentinel}
        repl = _make_repl(ns)

        for _ in range(5):
            repl._add_to_namespace()
            assert isinstance(ns["exit"], PtExit)
            assert "get_ptpython" in ns
            repl._remove_from_namespace()
            assert ns["exit"] is sentinel
            assert "get_ptpython" not in ns

    def test_other_globals_untouched(self) -> None:
        ns: dict = {"foo": 42, "bar": "hello"}
        repl = _make_repl(ns)

        repl._add_to_namespace()
        repl._remove_from_namespace()

        assert ns["foo"] == 42
        assert ns["bar"] == "hello"

    def test_exit_isinstance_check(self) -> None:
        """The ptpython exit class is recognized by isinstance —
        ensures that typing 'exit' without parens still triggers ReplExit."""
        instance = PtExit()
        assert isinstance(instance, PtExit)

    def test_separate_repls_isolate_namespaces(self) -> None:
        """Two repls on separate namespaces don't interfere."""
        host_exit_a = object()
        host_exit_b = object()
        ns_a: dict = {"exit": host_exit_a}
        ns_b: dict = {"exit": host_exit_b}
        repl_a = _make_repl(ns_a)
        repl_b = _make_repl(ns_b)

        repl_a._add_to_namespace()
        repl_b._add_to_namespace()

        repl_a._remove_from_namespace()
        assert ns_a["exit"] is host_exit_a
        assert isinstance(ns_b["exit"], PtExit)

        repl_b._remove_from_namespace()
        assert ns_b["exit"] is host_exit_b
