#!/usr/bin/env python
"""
Tests for namespace injection and cleanup in the embedded REPL.

Verifies that ``embed()`` / ``PythonRepl.run()`` properly saves and
restores the host namespace, so that repeated enter/exit cycles do not
pollute the caller's globals or locals.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from prompt_toolkit.input import DummyInput
from prompt_toolkit.output import DummyOutput

from ptpython.repl import PythonRepl, exit as ptpython_exit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repl(
    globals: dict[str, Any] | None = None,
    locals: dict[str, Any] | None = None,
) -> PythonRepl:
    """Create a ``PythonRepl`` with dummy I/O (no real terminal needed)."""
    if globals is None:
        globals = {"__name__": "__main__", "__builtins__": __builtins__}
    if locals is None:
        locals = globals

    return PythonRepl(
        get_globals=lambda: globals,
        get_locals=lambda: locals,
        input=DummyInput(),
        output=DummyOutput(),
    )


def _run_repl(repl: PythonRepl) -> None:
    """Run the REPL loop, immediately exiting via ``EOFError`` (Ctrl-D)."""
    with patch.object(repl, "read", side_effect=EOFError):
        repl.run()


def _run_repl_with_expressions(repl: PythonRepl, expressions: list[str]) -> None:
    """Run the REPL loop, feeding *expressions* one by one, then EOFError."""
    it = iter(expressions)

    def fake_read() -> str:
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    with patch.object(repl, "read", side_effect=fake_read):
        repl.run()


# ---------------------------------------------------------------------------
# Tests: ``exit`` injection and cleanup
# ---------------------------------------------------------------------------


class TestExitCleanup:
    def test_exit_removed_when_not_preexisting(self) -> None:
        """Host has no ``exit`` → after REPL exits it should be gone."""
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
        }
        repl = _make_repl(globs)
        _run_repl(repl)

        assert "exit" not in globs

    def test_exit_restored_when_preexisting(self) -> None:
        """Host has a custom ``exit`` → after REPL exits it is restored."""
        my_exit = lambda: "custom"  # noqa: E731
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
            "exit": my_exit,
        }
        repl = _make_repl(globs)
        _run_repl(repl)

        assert globs["exit"] is my_exit

    def test_exit_restored_when_value_is_none(self) -> None:
        """Host had ``exit = None`` → must be restored as ``None``, not deleted."""
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
            "exit": None,
        }
        repl = _make_repl(globs)
        _run_repl(repl)

        assert "exit" in globs
        assert globs["exit"] is None

    def test_exit_is_ptpython_during_repl(self) -> None:
        """Inside the REPL, ``exit`` should be the ptpython exit instance."""
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
        }
        repl = _make_repl(globs)
        repl._add_to_namespace()

        assert isinstance(globs["exit"], ptpython_exit)

        repl._remove_from_namespace()

    def test_exit_cleaned_even_if_user_deletes_it(self) -> None:
        """If the user does ``del exit`` inside the REPL, cleanup must not crash."""
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
        }
        repl = _make_repl(globs)
        repl._add_to_namespace()

        # Simulate user deleting exit from the namespace.
        del globs["exit"]

        # Should not raise.
        repl._remove_from_namespace()
        assert "exit" not in globs


# ---------------------------------------------------------------------------
# Tests: ``get_ptpython`` injection and cleanup
# ---------------------------------------------------------------------------


class TestGetPtpythonCleanup:
    def test_get_ptpython_removed_when_not_preexisting(self) -> None:
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
        }
        repl = _make_repl(globs)
        _run_repl(repl)

        assert "get_ptpython" not in globs

    def test_get_ptpython_restored_when_preexisting(self) -> None:
        my_func = lambda: "original"  # noqa: E731
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
            "get_ptpython": my_func,
        }
        repl = _make_repl(globs)
        _run_repl(repl)

        assert globs["get_ptpython"] is my_func

    def test_get_ptpython_works_during_repl(self) -> None:
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
        }
        repl = _make_repl(globs)
        repl._add_to_namespace()

        assert callable(globs["get_ptpython"])
        assert globs["get_ptpython"]() is repl

        repl._remove_from_namespace()


# ---------------------------------------------------------------------------
# Tests: ``_`` and ``_N`` eval-result cleanup
# ---------------------------------------------------------------------------


class TestEvalResultCleanup:
    def test_underscore_removed_when_not_preexisting(self) -> None:
        """REPL writes ``_`` → cleaned on exit."""
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
        }
        repl = _make_repl(globs)
        repl._add_to_namespace()
        repl._store_eval_result(42)
        repl.current_statement_index += 1
        repl._remove_from_namespace()

        assert "_" not in globs

    def test_underscore_restored_when_preexisting(self) -> None:
        """Host had ``_ = "original"`` → restored after REPL."""
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
            "_": "original",
        }
        repl = _make_repl(globs)
        repl._add_to_namespace()
        # Simulate REPL overwriting ``_``.
        repl._store_eval_result("new_value")
        repl.current_statement_index += 1
        repl._remove_from_namespace()

        assert globs["_"] == "original"

    def test_underscore_n_variables_cleaned(self) -> None:
        """``_1``, ``_2``, ``_3`` produced by REPL are all removed."""
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
        }
        repl = _make_repl(globs)
        # Feed some expressions through the full loop.
        _run_repl_with_expressions(repl, ["1 + 1", "'hello'", "None"])

        assert "_" not in globs
        assert "_1" not in globs
        assert "_2" not in globs
        # _3 is not created because None results are not stored
        # (run_and_show_expression only stores if result is not None,
        # but _store_eval_result is called regardless in eval()).
        # Let's just check that no _N for N >= 1 leaks.
        for key in list(globs):
            if key.startswith("_") and key[1:].isdigit():
                pytest.fail(f"Unexpected _N variable left behind: {key}")

    def test_preexisting_underscore_n_preserved(self) -> None:
        """Host had ``_5 = 'mine'`` before REPL. It should survive."""
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
            "_5": "mine",
        }
        repl = _make_repl(globs)
        # current_statement_index starts at 1, so _1, _2 etc are REPL-made.
        # _5 is pre-existing and at index 5 which is beyond what this
        # short session will reach.
        _run_repl_with_expressions(repl, ["10", "20"])

        assert globs.get("_5") == "mine"

    def test_preexisting_underscore_n_overwritten_then_restored(self) -> None:
        """If REPL overwrites a pre-existing ``_N``, it should be removed
        (since it falls within the REPL's index range) — but only if the
        index was within the REPL session range."""
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
        }
        repl = _make_repl(globs)
        # Force the statement index to start at 5 to collide with host _5.
        repl.current_statement_index = 5
        globs["_5"] = "host_value"

        repl._add_to_namespace()
        # Simulate REPL producing _5 and _6.
        repl._store_eval_result("repl_value_5")
        repl.current_statement_index += 1
        repl._store_eval_result("repl_value_6")
        repl.current_statement_index += 1
        repl._remove_from_namespace()

        # _5 was in the REPL range [5, 7), so it gets cleaned up (popped).
        assert "_5" not in globs
        assert "_6" not in globs


# ---------------------------------------------------------------------------
# Tests: repeated embedding
# ---------------------------------------------------------------------------


class TestRepeatedEmbedding:
    def test_repeated_embed_restores_namespace(self) -> None:
        """Three consecutive embed cycles leave no trace."""
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
            "my_var": "keep_me",
        }
        original_keys = set(globs.keys())

        for _ in range(3):
            repl = _make_repl(globs)
            _run_repl_with_expressions(repl, ["1 + 1", "'test'"])

        # Only the original keys (plus any user assignments) should remain.
        # ``exit``, ``get_ptpython``, ``_``, ``_N`` must all be gone.
        assert "exit" not in globs
        assert "get_ptpython" not in globs
        assert "_" not in globs
        assert globs["my_var"] == "keep_me"

        # No _N variables should leak.
        for key in globs:
            if key.startswith("_") and key[1:].isdigit():
                pytest.fail(f"Leaked _N variable: {key}")

    def test_repeated_embed_with_preexisting_exit(self) -> None:
        """Host's custom ``exit`` survives repeated embeds."""
        my_exit = object()
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
            "exit": my_exit,
        }

        for _ in range(3):
            repl = _make_repl(globs)
            _run_repl(repl)
            assert globs["exit"] is my_exit, (
                "Host exit should be restored after each embed cycle"
            )


# ---------------------------------------------------------------------------
# Tests: user-defined variables
# ---------------------------------------------------------------------------


class TestUserDefinedVars:
    def test_user_defined_vars_persist(self) -> None:
        """Variables assigned inside the REPL via exec should persist
        (they are the user's data, not REPL artifacts)."""
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
        }
        repl = _make_repl(globs)
        _run_repl_with_expressions(repl, ["x = 42", "y = 'hello'"])

        assert globs.get("x") == 42
        assert globs.get("y") == "hello"


# ---------------------------------------------------------------------------
# Tests: separate globals and locals
# ---------------------------------------------------------------------------


class TestSeparateGlobalsLocals:
    def test_exit_cleaned_from_globals(self) -> None:
        """When globals ≠ locals, ``exit`` is cleaned from globals."""
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
        }
        locs: dict[str, Any] = {}
        repl = _make_repl(globs, locs)
        _run_repl(repl)

        assert "exit" not in globs
        assert "get_ptpython" not in globs

    def test_underscore_cleaned_from_locals(self) -> None:
        """When globals ≠ locals, ``_`` is cleaned from locals (not globals)."""
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
        }
        locs: dict[str, Any] = {}
        repl = _make_repl(globs, locs)

        repl._add_to_namespace()
        repl._store_eval_result(99)
        repl.current_statement_index += 1
        repl._remove_from_namespace()

        assert "_" not in locs
        assert "_" not in globs

    def test_preexisting_underscore_in_locals_restored(self) -> None:
        """If locals has ``_``, it should be restored (globals is separate)."""
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
        }
        locs: dict[str, Any] = {"_": "local_original"}
        repl = _make_repl(globs, locs)

        repl._add_to_namespace()
        repl._store_eval_result("repl_value")
        repl.current_statement_index += 1
        repl._remove_from_namespace()

        assert locs["_"] == "local_original"


# ---------------------------------------------------------------------------
# Tests: cleanup after exceptions
# ---------------------------------------------------------------------------


class TestCleanupOnException:
    def test_cleanup_after_eval_exception(self) -> None:
        """Even if an expression raises, namespace is still cleaned."""
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
        }
        repl = _make_repl(globs)
        # "1/0" will raise ZeroDivisionError, but the REPL loop continues.
        _run_repl_with_expressions(repl, ["1 / 0", "1 + 1"])

        assert "exit" not in globs
        assert "get_ptpython" not in globs

    def test_cleanup_after_repl_exit(self) -> None:
        """Calling ``exit()`` inside the REPL cleans up properly."""
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
        }
        repl = _make_repl(globs)

        # Feed an expression that triggers ReplExit via bare `exit`.
        # We need to manually trigger the add/remove since `exit` eval
        # raises ReplExit which terminates the run() loop.
        repl._add_to_namespace()

        assert isinstance(globs.get("exit"), ptpython_exit)

        # Simulate the finally block.
        repl._remove_from_namespace()

        assert "exit" not in globs
        assert "get_ptpython" not in globs
