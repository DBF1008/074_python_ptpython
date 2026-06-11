"""
Tests for embed() config-loading and startup-discovery features.
"""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from ptpython.repl import (
    PythonRepl,
    _discover_config_file,
    embed,
    run_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config_file(directory: Path, body: str) -> Path:
    """Write a config.py into *directory* and return its path."""
    config = directory / "config.py"
    config.write_text(textwrap.dedent(body), encoding="utf-8")
    return config


def _make_repl_mock() -> MagicMock:
    """Return a lightweight mock that quacks like PythonInput."""
    repl = MagicMock()
    repl.show_signature = False
    repl.show_docstring = False
    return repl


# ===================================================================
# _discover_config_file()
# ===================================================================


class TestDiscoverConfigFile:
    def test_env_var_with_existing_file(self, tmp_path, monkeypatch):
        """$PTPYTHON_CONFIG_HOME is respected when config.py exists."""
        config_dir = tmp_path / "cfg"
        config_dir.mkdir()
        (config_dir / "config.py").write_text("# config", encoding="utf-8")

        monkeypatch.setenv("PTPYTHON_CONFIG_HOME", str(config_dir))
        result = _discover_config_file()
        assert result == str(config_dir / "config.py")

    def test_env_var_without_file_returns_none(self, tmp_path, monkeypatch):
        """$PTPYTHON_CONFIG_HOME set but no config.py → None."""
        config_dir = tmp_path / "cfg"
        config_dir.mkdir()

        monkeypatch.setenv("PTPYTHON_CONFIG_HOME", str(config_dir))
        assert _discover_config_file() is None

    def test_no_env_var_falls_back_to_xdg(self, tmp_path, monkeypatch):
        """Without $PTPYTHON_CONFIG_HOME, fall back to appdirs/XDG."""
        config_dir = tmp_path / "xdg" / "ptpython"
        config_dir.mkdir(parents=True)
        (config_dir / "config.py").write_text("# xdg", encoding="utf-8")

        monkeypatch.delenv("PTPYTHON_CONFIG_HOME", raising=False)

        # Mock the lazy appdirs import inside _discover_config_file
        fake_appdirs = MagicMock()
        fake_appdirs.user_config_dir = MagicMock(return_value=str(config_dir))

        with patch.dict(sys.modules, {"appdirs": fake_appdirs}):
            result = _discover_config_file()

        assert result == str(config_dir / "config.py")

    def test_no_env_no_file_returns_none(self, tmp_path, monkeypatch):
        """Neither env var nor default location has config.py → None."""
        monkeypatch.delenv("PTPYTHON_CONFIG_HOME", raising=False)

        # Mock appdirs to return a directory without config.py
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        fake_appdirs = MagicMock()
        fake_appdirs.user_config_dir = MagicMock(return_value=str(empty_dir))

        # Patch the lazy import inside _discover_config_file
        with patch.dict(sys.modules, {"appdirs": fake_appdirs}):
            assert _discover_config_file() is None


# ===================================================================
# run_config(quiet=...)
# ===================================================================


class TestRunConfig:
    def test_quiet_missing_file_no_block(self, tmp_path, monkeypatch):
        """quiet=True: missing file returns silently (no input() call)."""
        repl = _make_repl_mock()
        missing = str(tmp_path / "nonexistent.py")

        # Patch input() to detect if it gets called
        with patch("builtins.input") as mock_input:
            run_config(repl, missing, quiet=True)
            mock_input.assert_not_called()

    def test_nonquiet_missing_file_blocks(self, tmp_path):
        """quiet=False (default): missing explicit file prints + blocks."""
        repl = _make_repl_mock()
        missing = str(tmp_path / "nonexistent.py")

        with patch("builtins.input") as mock_input:
            run_config(repl, missing, quiet=False)
            mock_input.assert_called_once()

    def test_quiet_error_no_block(self, tmp_path):
        """quiet=True: config that raises doesn't block on Enter."""
        config = _make_config_file(
            tmp_path,
            """\
            def configure(repl):
                raise RuntimeError("boom")
            """,
        )
        repl = _make_repl_mock()

        with patch("builtins.input") as mock_input:
            run_config(repl, str(config), quiet=True)
            mock_input.assert_not_called()

    def test_quiet_loads_config(self, tmp_path):
        """quiet=True still loads a valid config file."""
        config = _make_config_file(
            tmp_path,
            """\
            def configure(repl):
                repl.show_signature = True
            """,
        )
        repl = _make_repl_mock()
        run_config(repl, str(config), quiet=True)
        assert repl.show_signature is True

    def test_default_config_missing_returns_silently(self):
        """run_config(repl) with no config_file and missing default → silent return."""
        repl = _make_repl_mock()
        with patch("os.path.exists", return_value=False):
            with patch("builtins.input") as mock_input:
                run_config(repl)
                mock_input.assert_not_called()


# ===================================================================
# embed() — default behavior (no config loading)
# ===================================================================


class TestEmbedDefaultBehavior:
    @patch("ptpython.repl.PythonRepl")
    def test_default_no_config_loading(self, MockRepl):
        """Default embed() does NOT call run_config or discover config."""
        mock_repl = MagicMock()
        MockRepl.return_value = mock_repl

        with patch("ptpython.repl.run_config") as mock_run_config, \
             patch("ptpython.repl._discover_config_file") as mock_discover:
            embed()
            mock_run_config.assert_not_called()
            mock_discover.assert_not_called()

    @patch("ptpython.repl.PythonRepl")
    def test_default_no_startup_discovery(self, MockRepl, monkeypatch):
        """Default embed() ignores $PYTHONSTARTUP when apply_startup=False."""
        mock_repl = MagicMock()
        MockRepl.return_value = mock_repl
        monkeypatch.setenv("PYTHONSTARTUP", "/tmp/some_startup.py")

        embed()

        # startup_paths passed to PythonRepl should NOT include PYTHONSTARTUP
        init_kwargs = MockRepl.call_args
        # startup_paths should be None (not passed)
        if init_kwargs.kwargs:
            assert init_kwargs.kwargs.get("startup_paths") is None
        else:
            # Positional args — startup_paths is the 5th positional arg
            # But embed passes it as kwarg, so check kwargs
            assert "startup_paths" not in init_kwargs.args


# ===================================================================
# embed(apply_config=True) — auto-discover
# ===================================================================


class TestEmbedApplyConfigTrue:
    @patch("ptpython.repl.PythonRepl")
    def test_loads_existing_config(self, MockRepl, tmp_path, monkeypatch):
        """apply_config=True loads config.py when it exists."""
        mock_repl = MagicMock()
        MockRepl.return_value = mock_repl

        config_dir = tmp_path / "cfg"
        config_dir.mkdir()
        _make_config_file(config_dir, "def configure(repl):\n    repl.show_signature = True\n")

        monkeypatch.setenv("PTPYTHON_CONFIG_HOME", str(config_dir))

        with patch("ptpython.repl.run_config") as mock_run_config:
            embed(apply_config=True)
            mock_run_config.assert_called_once()
            args, kwargs = mock_run_config.call_args
            assert args[0] is mock_repl
            assert str(config_dir / "config.py") in args[1]
            assert kwargs.get("quiet") is True

    @patch("ptpython.repl.PythonRepl")
    def test_silent_when_missing(self, MockRepl, tmp_path, monkeypatch):
        """apply_config=True with no config file → no error, no run_config call."""
        mock_repl = MagicMock()
        MockRepl.return_value = mock_repl

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        monkeypatch.setenv("PTPYTHON_CONFIG_HOME", str(empty_dir))

        with patch("ptpython.repl.run_config") as mock_run_config:
            embed(apply_config=True)
            mock_run_config.assert_not_called()


# ===================================================================
# embed(apply_config=str) — explicit path
# ===================================================================


class TestEmbedApplyConfigStr:
    @patch("ptpython.repl.PythonRepl")
    def test_loads_explicit_path(self, MockRepl, tmp_path):
        """apply_config='/path/to/config.py' loads that exact file."""
        mock_repl = MagicMock()
        MockRepl.return_value = mock_repl

        config = _make_config_file(tmp_path, "def configure(repl):\n    pass\n")

        with patch("ptpython.repl.run_config") as mock_run_config:
            embed(apply_config=str(config))
            mock_run_config.assert_called_once()
            args, kwargs = mock_run_config.call_args
            assert args[1] == str(config)
            assert kwargs.get("quiet") is True

    @patch("ptpython.repl.PythonRepl")
    def test_silent_when_explicit_missing(self, MockRepl, tmp_path):
        """apply_config with nonexistent path → silently skip."""
        mock_repl = MagicMock()
        MockRepl.return_value = mock_repl

        with patch("ptpython.repl.run_config") as mock_run_config:
            embed(apply_config=str(tmp_path / "does_not_exist.py"))
            mock_run_config.assert_not_called()


# ===================================================================
# embed() — composition: apply_config + configure callback
# ===================================================================


class TestEmbedComposition:
    @patch("ptpython.repl.PythonRepl")
    def test_config_first_then_callback(self, MockRepl, tmp_path, monkeypatch):
        """Config file loads first, then configure callback runs (can override)."""
        call_order = []

        mock_repl = MagicMock()
        MockRepl.return_value = mock_repl

        config = _make_config_file(
            tmp_path,
            """\
            def configure(repl):
                repl._order.append("config")
            """,
        )

        def my_callback(repl):
            repl._order.append("callback")

        # Use a real list on the mock to track order
        mock_repl._order = []

        monkeypatch.setenv("PTPYTHON_CONFIG_HOME", str(tmp_path))

        # We need run_config to actually execute the config file
        with patch("ptpython.repl.run_config", wraps=run_config):
            embed(apply_config=str(config), configure=my_callback)

        assert mock_repl._order == ["config", "callback"]

    @patch("ptpython.repl.PythonRepl")
    def test_callback_overrides_config(self, MockRepl, tmp_path):
        """Configure callback can override settings from config file."""
        mock_repl = MagicMock()
        mock_repl.show_signature = False
        MockRepl.return_value = mock_repl

        config = _make_config_file(
            tmp_path,
            """\
            def configure(repl):
                repl.show_signature = True
            """,
        )

        def my_callback(repl):
            repl.show_signature = False

        with patch("ptpython.repl.run_config", wraps=run_config):
            embed(apply_config=str(config), configure=my_callback)

        assert mock_repl.show_signature is False


# ===================================================================
# embed(apply_startup=True)
# ===================================================================


class TestEmbedApplyStartup:
    @patch("ptpython.repl.PythonRepl")
    def test_prepends_pythonstartup(self, MockRepl, monkeypatch):
        """apply_startup=True prepends $PYTHONSTARTUP to startup_paths."""
        mock_repl = MagicMock()
        MockRepl.return_value = mock_repl

        monkeypatch.setenv("PYTHONSTARTUP", "/path/to/startup.py")

        embed(apply_startup=True)

        kwargs = MockRepl.call_args.kwargs
        assert kwargs["startup_paths"] == ["/path/to/startup.py"]

    @patch("ptpython.repl.PythonRepl")
    def test_prepends_before_explicit_paths(self, MockRepl, monkeypatch):
        """apply_startup=True: $PYTHONSTARTUP comes before explicit startup_paths."""
        mock_repl = MagicMock()
        MockRepl.return_value = mock_repl

        monkeypatch.setenv("PYTHONSTARTUP", "/path/to/startup.py")

        embed(apply_startup=True, startup_paths=["/explicit/script.py"])

        kwargs = MockRepl.call_args.kwargs
        assert kwargs["startup_paths"] == [
            "/path/to/startup.py",
            "/explicit/script.py",
        ]

    @patch("ptpython.repl.PythonRepl")
    def test_false_ignores_pythonstartup(self, MockRepl, monkeypatch):
        """apply_startup=False (default): $PYTHONSTARTUP is ignored."""
        mock_repl = MagicMock()
        MockRepl.return_value = mock_repl

        monkeypatch.setenv("PYTHONSTARTUP", "/path/to/startup.py")

        embed(apply_startup=False, startup_paths=["/explicit/script.py"])

        kwargs = MockRepl.call_args.kwargs
        assert kwargs["startup_paths"] == ["/explicit/script.py"]

    @patch("ptpython.repl.PythonRepl")
    def test_no_env_var_no_effect(self, MockRepl, monkeypatch):
        """apply_startup=True with no $PYTHONSTARTUP → startup_paths unchanged."""
        mock_repl = MagicMock()
        MockRepl.return_value = mock_repl

        monkeypatch.delenv("PYTHONSTARTUP", raising=False)

        embed(apply_startup=True, startup_paths=["/explicit/script.py"])

        kwargs = MockRepl.call_args.kwargs
        assert kwargs["startup_paths"] == ["/explicit/script.py"]


# ===================================================================
# embed() — keyword-only enforcement
# ===================================================================


class TestEmbedKeywordOnly:
    def test_apply_config_is_keyword_only(self):
        """apply_config and apply_startup must be passed as keyword arguments."""
        with pytest.raises(TypeError):
            # 11 positional args, then apply_config as 12th positional
            embed(None, None, None, False, None, None, None, False, False, False, True)

    def test_apply_startup_is_keyword_only(self):
        """apply_startup must be passed as keyword argument."""
        with pytest.raises(TypeError):
            embed(None, None, None, False, None, None, None, False, False, False, False, True)
