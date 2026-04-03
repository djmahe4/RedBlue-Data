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

    def test_as_dict_includes_new_fields(self, monkeypatch):
        for key in ("MIN_WORDS", "OLLAMA_ENABLED", "OLLAMA_MODEL"):
            monkeypatch.delenv(key, raising=False)

        cfg = get_config([])
        d = cfg.as_dict()
        assert "min_words" in d
        assert "use_ollama_validation" in d
        assert "ollama_model" in d


class TestMinWordsConfig:
    def test_default_min_words(self, monkeypatch):
        monkeypatch.delenv("MIN_WORDS", raising=False)
        cfg = get_config([])
        assert cfg.min_words == 20

    def test_cli_min_words(self, monkeypatch):
        monkeypatch.delenv("MIN_WORDS", raising=False)
        cfg = get_config(["--min_words", "50"])
        assert cfg.min_words == 50

    def test_env_min_words(self, monkeypatch):
        monkeypatch.setenv("MIN_WORDS", "10")
        cfg = get_config([])
        assert cfg.min_words == 10

    def test_cli_overrides_env_min_words(self, monkeypatch):
        monkeypatch.setenv("MIN_WORDS", "10")
        cfg = get_config(["--min_words", "5"])
        assert cfg.min_words == 5


class TestOllamaConfig:
    def test_ollama_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_ENABLED", raising=False)
        cfg = get_config([])
        assert cfg.use_ollama_validation is False

    def test_ollama_enabled_via_cli(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_ENABLED", raising=False)
        cfg = get_config(["--use_ollama"])
        assert cfg.use_ollama_validation is True

    def test_ollama_enabled_via_env(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_ENABLED", "true")
        cfg = get_config([])
        assert cfg.use_ollama_validation is True

    def test_default_ollama_model(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        cfg = get_config([])
        assert cfg.ollama_model == "llama3.2"

    def test_ollama_model_via_cli(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        cfg = get_config(["--ollama_model", "mistral"])
        assert cfg.ollama_model == "mistral"

    def test_ollama_model_via_env(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "codellama")
        cfg = get_config([])
        assert cfg.ollama_model == "codellama"

