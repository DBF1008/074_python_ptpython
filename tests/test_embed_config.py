from __future__ import annotations

import os
from unittest.mock import MagicMock, call, patch

import pytest

from ptpython.repl import embed, get_default_config_file


# ---------------------------------------------------------------------------
# get_default_config_file()
# ---------------------------------------------------------------------------

class TestGetDefaultConfigFile:
    def test_uses_ptpython_config_home_env(self, monkeypatch, tmp_path):
        config_dir = str(tmp_path / "custom_cfg")
        monkeypatch.setenv("PTPYTHON_CONFIG_HOME", config_dir)
        result = get_default_config_file()
        assert result == os.path.join(config_dir, "config.py")

    def test_falls_back_to_appdirs(self, monkeypatch):
        monkeypatch.delenv("PTPYTHON_CONFIG_HOME", raising=False)
        with patch("ptpython.repl.appdirs.user_config_dir", return_value="/fake/appdirs") as m:
            with patch("os.path.exists", return_value=False):
                result = get_default_config_file()
        m.assert_called_once_with("ptpython", "prompt_toolkit")
        assert result == os.path.join("/fake/appdirs", "config.py")

    def test_legacy_fallback_when_default_missing(self, monkeypatch):
        monkeypatch.delenv("PTPYTHON_CONFIG_HOME", raising=False)
        legacy = os.path.join(os.path.expanduser("~/.ptpython"), "config.py")

        def exists_side(path):
            if path == legacy:
                return True
            return False

        with patch("ptpython.repl.appdirs.user_config_dir", return_value="/nonexistent"):
            with patch("os.path.exists", side_effect=exists_side):
                result = get_default_config_file()
        assert result == legacy

    def test_prefers_default_over_legacy(self, monkeypatch, tmp_path):
        config_dir = str(tmp_path / "cfg")
        os.makedirs(config_dir, exist_ok=True)
        config_file = os.path.join(config_dir, "config.py")
        with open(config_file, "w") as f:
            f.write("")

        monkeypatch.setenv("PTPYTHON_CONFIG_HOME", config_dir)
        result = get_default_config_file()
        assert result == config_file


# ---------------------------------------------------------------------------
# embed() — load_config
# ---------------------------------------------------------------------------

@pytest.fixture()
def _no_repl_run():
    """Prevent the REPL event loop from actually starting."""
    with patch("ptpython.repl.PythonRepl.run"):
        yield


@pytest.fixture()
def _no_startup_exec():
    """Prevent startup-path scripts from being executed."""
    with patch("ptpython.repl.PythonRepl._load_start_paths"):
        yield


class TestEmbedLoadConfig:
    @pytest.mark.usefixtures("_no_repl_run", "_no_startup_exec")
    def test_load_config_false_does_not_call_run_config(self):
        with patch("ptpython.repl.run_config") as mock_rc:
            embed(load_config=False)
        mock_rc.assert_not_called()

    @pytest.mark.usefixtures("_no_repl_run", "_no_startup_exec")
    def test_load_config_true_calls_run_config(self, tmp_path):
        cfg = tmp_path / "config.py"
        cfg.write_text("def configure(repl): repl._test_marker = True\n")

        with patch("ptpython.repl.get_default_config_file", return_value=str(cfg)):
            with patch("ptpython.repl.run_config") as mock_rc:
                embed(load_config=True)
        mock_rc.assert_called_once()
        args = mock_rc.call_args
        assert args[0][1] == str(cfg)

    @pytest.mark.usefixtures("_no_repl_run", "_no_startup_exec")
    def test_load_config_true_skips_missing_file(self):
        with patch("ptpython.repl.get_default_config_file", return_value="/no/such/file.py"):
            with patch("ptpython.repl.run_config") as mock_rc:
                embed(load_config=True)
        mock_rc.assert_not_called()

    @pytest.mark.usefixtures("_no_repl_run", "_no_startup_exec")
    def test_configure_callback_runs_after_config_file(self, tmp_path):
        cfg = tmp_path / "config.py"
        cfg.write_text("")

        call_order: list[str] = []

        original_run_config = MagicMock(side_effect=lambda *a, **kw: call_order.append("run_config"))

        def my_configure(repl):
            call_order.append("configure")

        with patch("ptpython.repl.get_default_config_file", return_value=str(cfg)):
            with patch("ptpython.repl.run_config", original_run_config):
                embed(load_config=True, configure=my_configure)

        assert call_order == ["run_config", "configure"]


# ---------------------------------------------------------------------------
# embed() — load_startup
# ---------------------------------------------------------------------------

class TestEmbedLoadStartup:
    @pytest.mark.usefixtures("_no_repl_run")
    def test_load_startup_false_ignores_pythonstartup(self, monkeypatch, tmp_path):
        startup = tmp_path / "startup.py"
        startup.write_text("STARTED = True\n")
        monkeypatch.setenv("PYTHONSTARTUP", str(startup))

        with patch("ptpython.repl.PythonRepl._load_start_paths") as mock_load:
            embed(load_startup=False)

        if mock_load.called:
            repl = mock_load.call_args[0][0] if mock_load.call_args[0] else None
        # The key assertion: with load_startup=False, startup_paths passed to
        # PythonRepl should NOT contain the PYTHONSTARTUP path.
        with patch("ptpython.repl.PythonRepl.__init__", return_value=None) as mock_init:
            with patch("ptpython.repl.PythonRepl.run"):
                embed(load_startup=False)
        _, kwargs = mock_init.call_args
        paths = kwargs.get("startup_paths") or []
        assert str(startup) not in [str(p) for p in paths]

    @pytest.mark.usefixtures("_no_repl_run")
    def test_load_startup_true_prepends_pythonstartup(self, monkeypatch, tmp_path):
        startup = tmp_path / "startup.py"
        startup.write_text("")
        monkeypatch.setenv("PYTHONSTARTUP", str(startup))

        with patch("ptpython.repl.PythonRepl.__init__", return_value=None) as mock_init:
            with patch("ptpython.repl.PythonRepl.run"):
                embed(load_startup=True, startup_paths=["/extra/path.py"])
        _, kwargs = mock_init.call_args
        paths = [str(p) for p in kwargs["startup_paths"]]
        assert paths[0] == str(startup)
        assert "/extra/path.py" in paths

    @pytest.mark.usefixtures("_no_repl_run")
    def test_load_startup_true_without_env_var(self, monkeypatch):
        monkeypatch.delenv("PYTHONSTARTUP", raising=False)

        with patch("ptpython.repl.PythonRepl.__init__", return_value=None) as mock_init:
            with patch("ptpython.repl.PythonRepl.run"):
                embed(load_startup=True)
        _, kwargs = mock_init.call_args
        paths = kwargs.get("startup_paths")
        assert paths is None


# ---------------------------------------------------------------------------
# embed() — default behaviour unchanged
# ---------------------------------------------------------------------------

class TestEmbedDefaults:
    @pytest.mark.usefixtures("_no_repl_run", "_no_startup_exec")
    def test_default_embed_does_not_load_config_or_startup(self, monkeypatch, tmp_path):
        startup = tmp_path / "startup.py"
        startup.write_text("")
        monkeypatch.setenv("PYTHONSTARTUP", str(startup))

        with patch("ptpython.repl.run_config") as mock_rc:
            with patch("ptpython.repl.PythonRepl.__init__", return_value=None) as mock_init:
                with patch("ptpython.repl.PythonRepl.run"):
                    embed()
        mock_rc.assert_not_called()
        _, kwargs = mock_init.call_args
        paths = kwargs.get("startup_paths")
        assert paths is None
