"""
tests/test_config.py - Tests for the configuration system.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from config import Config, get_config, _parse_bool, _parse_extensions


class TestParseBool:
    def test_true_values(self):
        for v in ("1", "true", "True", "TRUE", "yes", "on"):
            assert _parse_bool(v) is True

    def test_false_values(self):
        for v in ("0", "false", "False", "no", "off", ""):
            assert _parse_bool(v) is False


class TestParseExtensions:
    def test_comma_separated(self):
        result = _parse_extensions("pdf,md,html")
        assert result == ["pdf", "md", "html"]

    def test_strips_dot(self):
        result = _parse_extensions(".pdf,.docx")
        assert result == ["pdf", "docx"]

    def test_strips_whitespace(self):
        result = _parse_extensions("pdf, md , html")
        assert result == ["pdf", "md", "html"]


class TestGetConfigDefaults:
    def test_defaults(self, monkeypatch):
        # Clear any env vars that might interfere
        for key in ("MAX_REPORTS", "MAX_FILE_SIZE_MB", "ALLOWED_EXTENSIONS",
                    "OUTPUT_DIR", "SOURCE_REPO", "INCREMENTAL", "FULL_RUN"):
            monkeypatch.delenv(key, raising=False)

        cfg = get_config([])
        assert cfg.max_reports == 30
        assert cfg.max_file_size_mb == 5.0
        assert "pdf" in cfg.allowed_extensions
        assert cfg.output_dir == "dataset"
        assert cfg.incremental is True
        assert cfg.full_run is False

    def test_cli_overrides_defaults(self, monkeypatch):
        for key in ("MAX_REPORTS", "MAX_FILE_SIZE_MB"):
            monkeypatch.delenv(key, raising=False)

        cfg = get_config(["--max_reports", "50", "--max_file_size_mb", "10"])
        assert cfg.max_reports == 50
        assert cfg.max_file_size_mb == 10.0

    def test_env_overrides_defaults(self, monkeypatch):
        monkeypatch.setenv("MAX_REPORTS", "99")
        monkeypatch.setenv("MAX_FILE_SIZE_MB", "7.5")
        monkeypatch.delenv("FULL_RUN", raising=False)

        cfg = get_config([])
        assert cfg.max_reports == 99
        assert cfg.max_file_size_mb == 7.5

    def test_cli_overrides_env(self, monkeypatch):
        monkeypatch.setenv("MAX_REPORTS", "99")

        cfg = get_config(["--max_reports", "5"])
        assert cfg.max_reports == 5

    def test_incremental_disabled_by_flag(self, monkeypatch):
        monkeypatch.delenv("INCREMENTAL", raising=False)
        cfg = get_config(["--no_incremental"])
        assert cfg.incremental is False

    def test_full_run_flag(self, monkeypatch):
        monkeypatch.delenv("FULL_RUN", raising=False)
        cfg = get_config(["--full_run"])
        assert cfg.full_run is True


class TestConfigAsDict:
    def test_as_dict_has_required_keys(self, monkeypatch):
        for key in ("MAX_REPORTS", "MAX_FILE_SIZE_MB", "ALLOWED_EXTENSIONS",
                    "OUTPUT_DIR", "SOURCE_REPO", "INCREMENTAL", "FULL_RUN"):
            monkeypatch.delenv(key, raising=False)

        cfg = get_config([])
        d = cfg.as_dict()
        for k in ("max_reports", "max_file_size_mb", "allowed_extensions",
                  "output_dir", "source_repo", "incremental", "full_run"):
            assert k in d
