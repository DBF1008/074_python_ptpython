"""
Utility for creating a Python repl.

::

    from ptpython.repl import embed
    embed(globals(), locals(), vi_mode=False)

"""

from __future__ import annotations

import asyncio
import builtins
import os
import signal
import sys
import traceback
import types
import warnings
from dis import COMPILER_FLAG_NAMES
from pathlib import Path
from typing import (
    Any,
    Callable,
    ContextManager,
    Coroutine,
    Iterable,
    Literal,
    NoReturn,
    Sequence,
    overload,
)

from prompt_toolkit.formatted_text import OneStyleAndTextTuple
from prompt_toolkit.patch_stdout import patch_stdout as patch_stdout_context
from prompt_toolkit.shortcuts import (
    clear_title,
    set_title,
)
from prompt_toolkit.utils import DummyContext
from pygments.lexers import PythonTracebackLexer  # noqa: F401

from .printer import OutputPrinter
from .python_input import PythonInput

PyCF_ALLOW_TOP_LEVEL_AWAIT: int
try:
    from ast import PyCF_ALLOW_TOP_LEVEL_AWAIT  # type: ignore
except ImportError:
    PyCF_ALLOW_TOP_LEVEL_AWAIT = 0


__all__ = [
    "PythonRepl",
    "enable_deprecation_warnings",
    "run_config",
    "embed",
    "exit",
    "ReplExit",
]

# Sentinel used to distinguish "key was absent" from "key had value None"
# in namespace save/restore logic.
_KEY_NOT_PRESENT = object()


def _get_coroutine_flag() -> int | None:
    for k, v in COMPILER_FLAG_NAMES.items():
        if v == "COROUTINE":
            return k

    # Flag not found.
    return None


COROUTINE_FLAG: int | None = _get_coroutine_flag()


def _has_coroutine_flag(code: types.CodeType) -> bool:
    if COROUTINE_FLAG is None:
        # Not supported on this Python version.
        return False

    return bool(code.co_flags & COROUTINE_FLAG)


class PythonRepl(PythonInput):
    def __init__(self, *a, **kw) -> None:
        self._startup_paths: Sequence[str | Path] | None = kw.pop("startup_paths", None)
        super().__init__(*a, **kw)
        self._load_start_paths()

        # Namespace save/restore state (used by _add/_remove_from_namespace).
        self._saved_globals: dict[str, Any] = {}
        self._saved_locals: dict[str, Any] = {}
        self._repl_start_statement_index: int = 0

    def _load_start_paths(self) -> None:
        "Start the Read-Eval-Print Loop."
        if self._startup_paths:
            for path in self._startup_paths:
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        code = compile(f.read(), path, "exec")
                        exec(code, self.get_globals(), self.get_locals())
                else:
                    output = self.app.output
                    output.write(f"WARNING | File not found: {path}\n\n")

    def run_and_show_expression(self, expression: str) -> None:
        try:
            # Eval.
            try:
                result = self.eval(expression)
            except KeyboardInterrupt:
                # KeyboardInterrupt doesn't inherit from Exception.
                raise
            except SystemExit:
                raise
            except ReplExit:
                raise
            except BaseException as e:
                self._handle_exception(e)
            else:
                if isinstance(result, exit):
                    # When `exit` is evaluated without parentheses.
                    # Automatically trigger the `ReplExit` exception.
                    raise ReplExit

                # Print.
                if result is not None:
                    self._show_result(result)
                    if self.insert_blank_line_after_output:
                        self.app.output.write("\n")

                # Loop.
                self.current_statement_index += 1
                self.signatures = []

        except KeyboardInterrupt as e:
            # Handle all possible `KeyboardInterrupt` errors. This can
            # happen during the `eval`, but also during the
            # `show_result` if something takes too long.
            # (Try/catch is around the whole block, because we want to
            # prevent that a Control-C keypress terminates the REPL in
            # any case.)
            self._handle_keyboard_interrupt(e)

    def _get_output_printer(self) -> OutputPrinter:
        return OutputPrinter(
            output=self.app.output,
            input=self.app.input,
            style=self._current_style,
            style_transformation=self.style_transformation,
            title=self.title,
        )

    def _show_result(self, result: object) -> None:
        self._get_output_printer().display_result(
            result=result,
            out_prompt=self.get_output_prompt(),
            reformat=self.enable_output_formatting,
            highlight=self.enable_syntax_highlighting,
            paginate=self.enable_pager,
        )

    def run(self) -> None:
        """
        Run the REPL loop.
        """
        if self.terminal_title:
            set_title(self.terminal_title)

        self._add_to_namespace()

        try:
            while True:
                # Pull text from the user.
                try:
                    text = self.read()
                except EOFError:
                    return
                except BaseException:
                    # Something went wrong while reading input.
                    # (E.g., a bug in the completer that propagates. Don't
                    # crash the REPL.)
                    traceback.print_exc()
                    continue

                # Run it; display the result (or errors if applicable).
                try:
                    self.run_and_show_expression(text)
                except ReplExit:
                    return
        finally:
            if self.terminal_title:
                clear_title()
            self._remove_from_namespace()

    async def run_and_show_expression_async(self, text: str) -> Any:
        loop = asyncio.get_running_loop()
        system_exit: SystemExit | None = None

        try:
            try:
                # Create `eval` task. Ensure that control-c will cancel this
                # task.
                async def eval() -> Any:
                    nonlocal system_exit
                    try:
                        return await self.eval_async(text)
                    except SystemExit as e:
                        # Don't propagate SystemExit in `create_task()`. That
                        # will kill the event loop. We want to handle it
                        # gracefully.
                        system_exit = e

                task = asyncio.create_task(eval())
                loop.add_signal_handler(signal.SIGINT, lambda *_: task.cancel())
                result = await task

                if system_exit is not None:
                    raise system_exit
            except KeyboardInterrupt:
                # KeyboardInterrupt doesn't inherit from Exception.
                raise
            except SystemExit:
                raise
            except BaseException as e:
                self._handle_exception(e)
            else:
                # Print.
                if result is not None:
                    await loop.run_in_executor(None, lambda: self._show_result(result))

                # Loop.
                self.current_statement_index += 1
                self.signatures = []
                # Return the result for future consumers.
                return result
            finally:
                loop.remove_signal_handler(signal.SIGINT)

        except KeyboardInterrupt as e:
            # Handle all possible `KeyboardInterrupt` errors. This can
            # happen during the `eval`, but also during the
            # `show_result` if something takes too long.
            # (Try/catch is around the whole block, because we want to
            # prevent that a Control-C keypress terminates the REPL in
            # any case.)
            self._handle_keyboard_interrupt(e)

    async def run_async(self) -> None:
        """
        Run the REPL loop, but run the blocking parts in an executor, so that
        we don't block the event loop. Both the input and output (which can
        display a pager) will run in a separate thread with their own event
        loop, this way ptpython's own event loop won't interfere with the
        asyncio event loop from where this is called.

        The "eval" however happens in the current thread, which is important.
        (Both for control-C to work, as well as for the code to see the right
        thread in which it was embedded).
        """
        loop = asyncio.get_running_loop()

        if self.terminal_title:
            set_title(self.terminal_title)

        self._add_to_namespace()

        try:
            while True:
                try:
                    # Read.
                    try:
                        text = await loop.run_in_executor(None, self.read)
                    except EOFError:
                        return
                    except BaseException:
                        # Something went wrong while reading input.
                        # (E.g., a bug in the completer that propagates. Don't
                        # crash the REPL.)
                        traceback.print_exc()
                        continue

                    # Eval.
                    await self.run_and_show_expression_async(text)

                except KeyboardInterrupt as e:
                    # XXX: This does not yet work properly. In some situations,
                    # `KeyboardInterrupt` exceptions can end up in the event
                    # loop selector.
                    self._handle_keyboard_interrupt(e)
                except SystemExit:
                    return
        finally:
            if self.terminal_title:
                clear_title()
            self._remove_from_namespace()

    def eval(self, line: str) -> object:
        """
        Evaluate the line and print the result.
        """
        # WORKAROUND: Due to a bug in Jedi, the current directory is removed
        # from sys.path. See: https://github.com/davidhalter/jedi/issues/1148
        if "" not in sys.path:
            sys.path.insert(0, "")

        if line.lstrip().startswith("!"):
            # Run as shell command
            os.system(line[1:])
        else:
            # Try eval first
            try:
                code = self._compile_with_flags(line, "eval")
            except SyntaxError:
                pass
            else:
                # No syntax errors for eval. Do eval.
                result = eval(code, self.get_globals(), self.get_locals())

                if _has_coroutine_flag(code):
                    result = asyncio.get_running_loop().run_until_complete(result)

                self._store_eval_result(result)
                return result

            # If not a valid `eval` expression, run using `exec` instead.
            # Note that we shouldn't run this in the `except SyntaxError` block
            # above, then `sys.exc_info()` would not report the right error.
            # See issue: https://github.com/prompt-toolkit/ptpython/issues/435
            code = self._compile_with_flags(line, "exec")
            result = eval(code, self.get_globals(), self.get_locals())

            if _has_coroutine_flag(code):
                result = asyncio.get_running_loop().run_until_complete(result)

        return None

    async def eval_async(self, line: str) -> object:
        """
        Evaluate the line and print the result.
        """
        # WORKAROUND: Due to a bug in Jedi, the current directory is removed
        # from sys.path. See: https://github.com/davidhalter/jedi/issues/1148
        if "" not in sys.path:
            sys.path.insert(0, "")

        if line.lstrip().startswith("!"):
            # Run as shell command
            os.system(line[1:])
        else:
            # Try eval first
            try:
                code = self._compile_with_flags(line, "eval")
            except SyntaxError:
                pass
            else:
                # No syntax errors for eval. Do eval.
                result = eval(code, self.get_globals(), self.get_locals())

                if _has_coroutine_flag(code):
                    result = await result

                self._store_eval_result(result)
                return result

            # If not a valid `eval` expression, compile as `exec` expression
            # but still run with eval to get an awaitable in case of a
            # awaitable expression.
            code = self._compile_with_flags(line, "exec")
            result = eval(code, self.get_globals(), self.get_locals())

            if _has_coroutine_flag(code):
                result = await result

        return None

    def _store_eval_result(self, result: object) -> None:
        locals: dict[str, Any] = self.get_locals()
        locals["_"] = locals[f"_{self.current_statement_index}"] = result

    def get_compiler_flags(self) -> int:
        return super().get_compiler_flags() | PyCF_ALLOW_TOP_LEVEL_AWAIT

    def _compile_with_flags(self, code: str, mode: str) -> Any:
        "Compile code with the right compiler flags."
        return compile(
            code,
            "<stdin>",
            mode,
            flags=self.get_compiler_flags(),
            dont_inherit=True,
        )

    def _handle_exception(self, e: BaseException) -> None:
        # Required for pdb.post_mortem() to work.
        t, v, tb = sys.exc_info()
        sys.last_type, sys.last_value, sys.last_traceback = t, v, tb

        self._get_output_printer().display_exception(
            e,
            highlight=self.enable_syntax_highlighting,
            paginate=self.enable_pager,
        )

    def _handle_keyboard_interrupt(self, e: KeyboardInterrupt) -> None:
        output = self.app.output

        output.write("\rKeyboardInterrupt\n\n")
        output.flush()

    def _add_to_namespace(self) -> None:
        """
        Add ptpython built-ins to global namespace.

        Saves the current values of any keys that will be injected, so that
        ``_remove_from_namespace`` can restore them on exit.  This ensures
        that repeated ``embed()`` calls do not pollute the host namespace.
        """
        globals = self.get_globals()
        locals = self.get_locals()

        # Snapshot existing values (sentinel for "key was not present").
        self._saved_globals = {
            "exit": globals.get("exit", _KEY_NOT_PRESENT),
            "get_ptpython": globals.get("get_ptpython", _KEY_NOT_PRESENT),
        }
        self._saved_locals = {
            "_": locals.get("_", _KEY_NOT_PRESENT),
        }
        self._repl_start_statement_index = self.current_statement_index

        # Add a 'get_ptpython', similar to 'get_ipython'
        def get_ptpython() -> PythonInput:
            return self

        globals["get_ptpython"] = get_ptpython
        globals["exit"] = exit()

    def _remove_from_namespace(self) -> None:
        """
        Remove injected symbols from globals/locals and restore originals.

        For every key that was injected by ``_add_to_namespace``:
        - If the key did not exist before, remove it.
        - If the key had a previous value, restore it.

        Also cleans up ``_`` and ``_N`` eval-result variables that were
        written to locals during this REPL session.
        """
        globals = self.get_globals()
        locals = self.get_locals()

        # Restore injected globals.
        for key in ("exit", "get_ptpython"):
            original = self._saved_globals.get(key, _KEY_NOT_PRESENT)
            if original is _KEY_NOT_PRESENT:
                globals.pop(key, None)
            else:
                globals[key] = original

        # Restore ``_`` in locals.
        original_underscore = self._saved_locals.get("_", _KEY_NOT_PRESENT)
        if original_underscore is _KEY_NOT_PRESENT:
            locals.pop("_", None)
        else:
            locals["_"] = original_underscore

        # Clean up ``_N`` eval result variables added during this session.
        for i in range(
            self._repl_start_statement_index, self.current_statement_index
        ):
            locals.pop(f"_{i}", None)

        # Release references so we don't hold on to host objects.
        self._saved_globals = {}
        self._saved_locals = {}

    def print_paginated_formatted_text(
        self,
        formatted_text: Iterable[OneStyleAndTextTuple],
        end: str = "\n",
    ) -> None:
        # Warning: This is mainly here backwards-compatibility. Some projects
        # call `print_paginated_formatted_text` on the Repl object.
        self._get_output_printer().display_style_and_text_tuples(
            formatted_text, paginate=True
        )


def enable_deprecation_warnings() -> None:
    """
    Show deprecation warnings, when they are triggered directly by actions in
    the REPL. This is recommended to call, before calling `embed`.

    e.g. This will show an error message when the user imports the 'sha'
         library on Python 2.7.
    """
    warnings.filterwarnings("default", category=DeprecationWarning, module="__main__")


DEFAULT_CONFIG_FILE = "~/.config/ptpython/config.py"


def _discover_config_file() -> str | None:
    """
    Discover the config file path for embed mode.

    Checks ``$PTPYTHON_CONFIG_HOME/config.py`` first, then falls back to the
    XDG default via ``appdirs`` (lazy import).  Returns ``None`` when the file
    does not exist — never creates directories or blocks.
    """
    config_dir = os.environ.get("PTPYTHON_CONFIG_HOME")
    if config_dir:
        path = os.path.join(config_dir, "config.py")
        if os.path.isfile(path):
            return path
        return None

    # Fall back to XDG / platform default via lazy import.
    try:
        import appdirs

        config_dir = appdirs.user_config_dir("ptpython", "prompt_toolkit")
    except ImportError:
        config_dir = os.path.expanduser("~/.config/ptpython")

    path = os.path.join(config_dir, "config.py")
    if os.path.isfile(path):
        return path
    return None


def run_config(repl: PythonInput, config_file: str | None = None, *, quiet: bool = False) -> None:
    """
    Execute REPL config file.

    :param repl: `PythonInput` instance.
    :param config_file: Path of the configuration file.
    :param quiet: When ``True``, silently return on missing files and don't
                  block on errors (suitable for embed mode).
    """
    explicit_config_file = config_file is not None

    # Expand tildes.
    config_file = os.path.expanduser(
        config_file if config_file is not None else DEFAULT_CONFIG_FILE
    )

    def enter_to_continue() -> None:
        if not quiet:
            input("\nPress ENTER to continue...")

    # Check whether this file exists.
    if not os.path.exists(config_file):
        if explicit_config_file and not quiet:
            print(f"Impossible to read {config_file}")
            enter_to_continue()
        return

    # Run the config file in an empty namespace.
    try:
        namespace: dict[str, Any] = {}

        with open(config_file, "rb") as f:
            code = compile(f.read(), config_file, "exec")
            exec(code, namespace, namespace)

        # Now we should have a 'configure' method in this namespace. We call this
        # method with the repl as an argument.
        if "configure" in namespace:
            namespace["configure"](repl)

    except Exception:
        traceback.print_exc()
        enter_to_continue()


class exit:
    """
    Exit the ptpython REPL.
    """

    # This custom exit function ensures that the `embed` function returns from
    # where we are embedded, and Python doesn't close `sys.stdin` like
    # the default `exit` from `_sitebuiltins.Quitter` does.

    def __call__(self) -> NoReturn:
        raise ReplExit

    def __repr__(self) -> str:
        # (Same message as the built-in Python REPL.)
        return "Use exit() or Ctrl-D (i.e. EOF) to exit"


class ReplExit(Exception):
    """
    Exception raised by ptpython's exit function.
    """


@overload
def embed(
    globals: dict[str, Any] | None = ...,
    locals: dict[str, Any] | None = ...,
    configure: Callable[[PythonRepl], None] | None = ...,
    vi_mode: bool = ...,
    history_filename: str | None = ...,
    title: str | None = ...,
    startup_paths: Sequence[str | Path] | None = ...,
    patch_stdout: bool = ...,
    patch_stdout_raw: bool = ...,
    return_asyncio_coroutine: Literal[False] = ...,
    *,
    apply_config: bool | str = ...,
    apply_startup: bool = ...,
) -> None: ...


@overload
def embed(
    globals: dict[str, Any] | None = ...,
    locals: dict[str, Any] | None = ...,
    configure: Callable[[PythonRepl], None] | None = ...,
    vi_mode: bool = ...,
    history_filename: str | None = ...,
    title: str | None = ...,
    startup_paths: Sequence[str | Path] | None = ...,
    patch_stdout: bool = ...,
    patch_stdout_raw: bool = ...,
    return_asyncio_coroutine: Literal[True] = ...,
    *,
    apply_config: bool | str = ...,
    apply_startup: bool = ...,
) -> Coroutine[Any, Any, None]: ...


def embed(
    globals: dict[str, Any] | None = None,
    locals: dict[str, Any] | None = None,
    configure: Callable[[PythonRepl], None] | None = None,
    vi_mode: bool = False,
    history_filename: str | None = None,
    title: str | None = None,
    startup_paths: Sequence[str | Path] | None = None,
    patch_stdout: bool = False,
    patch_stdout_raw: bool = False,
    return_asyncio_coroutine: bool = False,
    *,
    apply_config: bool | str = False,
    apply_startup: bool = False,
) -> None | Coroutine[Any, Any, None]:
    """
    Call this to embed  Python shell at the current point in your program.
    It's similar to `IPython.embed` and `bpython.embed`::

        from ptpython.repl import embed
        embed(globals(), locals())

    :param vi_mode: Boolean. Use Vi instead of Emacs key bindings.
    :param configure: Callable that will be called with the `PythonRepl` as a first
                      argument, to trigger configuration.
    :param title: Title to be displayed in the terminal titlebar. (None or string.)
    :param patch_stdout: When true, patch `sys.stdout` so that background
        threads that are printing will print nicely above the prompt.
    :param patch_stdout_raw: When true, patch_stdout will not escape/remove
        vt100 terminal escape sequences.
    :param apply_config: Control config-file loading.

        - ``False`` (default): no config loading, no side-effects.
        - ``True``: auto-discover config via ``$PTPYTHON_CONFIG_HOME`` or XDG
          default.  Silently skip when the file is missing.
        - ``str``: use this explicit path.  Silently skip when missing.

        When both *apply_config* and *configure* are given, the config file
        is loaded **first**, then *configure(repl)* is called (so the callback
        can override anything set by the config file).
    :param apply_startup: When ``True``, prepend ``$PYTHONSTARTUP`` (if set)
        to *startup_paths*.  When ``False`` (default), only explicitly-passed
        *startup_paths* are used.
    """
    # Handle apply_startup: prepend $PYTHONSTARTUP if requested.
    if apply_startup:
        pythonstartup = os.environ.get("PYTHONSTARTUP")
        if pythonstartup:
            startup_paths = [pythonstartup] + list(startup_paths or [])

    # Default globals/locals
    if globals is None:
        globals = {
            "__name__": "__main__",
            "__package__": None,
            "__doc__": None,
            "__builtins__": builtins,
        }

    locals = locals or globals

    def get_globals() -> dict[str, Any]:
        return globals

    def get_locals() -> dict[str, Any]:
        return locals

    # Create REPL.
    repl = PythonRepl(
        get_globals=get_globals,
        get_locals=get_locals,
        vi_mode=vi_mode,
        history_filename=history_filename,
        startup_paths=startup_paths,
    )

    if title:
        repl.terminal_title = title

    # Apply config file (before the configure callback, so the callback
    # can override config-file settings).
    if apply_config:
        config_path: str | None = None
        if isinstance(apply_config, str):
            config_path = os.path.expanduser(apply_config)
        else:
            config_path = _discover_config_file()
        if config_path and os.path.exists(config_path):
            run_config(repl, config_path, quiet=True)

    if configure:
        configure(repl)

    # Start repl.
    patch_context: ContextManager[None] = (
        patch_stdout_context(raw=patch_stdout_raw) if patch_stdout else DummyContext()
    )

    if return_asyncio_coroutine:

        async def coroutine() -> None:
            with patch_context:
                await repl.run_async()

        return coroutine()  # type: ignore
    else:
        with patch_context:
            repl.run()
        return None
