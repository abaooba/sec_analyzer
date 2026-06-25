"""Tests for config's environment loading.

The behavior under test is `_load_env_files`: it loads `.env` files by an
explicit absolute path (so configuration is independent of the current working
directory) and never overrides a value already present in the real environment.
These tests use throwaway `.env` files under `tmp_path`, so they are fully
offline and never read the developer's real `.env`.
"""

import os

from backend.app import config


def test_load_env_files_loads_value_by_explicit_path(tmp_path):
    """An existing file is loaded into os.environ regardless of the cwd."""
    env_file = tmp_path / ".env"
    env_file.write_text("SEC_ANALYZER_TEST_A=loaded_from_file\n")
    os.environ.pop("SEC_ANALYZER_TEST_A", None)
    try:
        loaded = config._load_env_files(env_file)
        assert loaded == [env_file]
        assert os.environ["SEC_ANALYZER_TEST_A"] == "loaded_from_file"
    finally:
        os.environ.pop("SEC_ANALYZER_TEST_A", None)


def test_load_env_files_skips_missing_paths(tmp_path):
    """A non-existent path is skipped (not loaded, not in the returned list)."""
    missing = tmp_path / "absent.env"
    assert config._load_env_files(missing) == []


def test_load_env_files_does_not_override_real_env(tmp_path):
    """A value already set in os.environ is not clobbered by the .env file."""
    env_file = tmp_path / ".env"
    env_file.write_text("SEC_ANALYZER_TEST_B=from_file\n")
    os.environ["SEC_ANALYZER_TEST_B"] = "from_real_env"
    try:
        config._load_env_files(env_file)
        assert os.environ["SEC_ANALYZER_TEST_B"] == "from_real_env"
    finally:
        os.environ.pop("SEC_ANALYZER_TEST_B", None)


def test_load_env_files_first_path_wins(tmp_path):
    """When multiple files set the same var, the first one loaded wins
    (load_dotenv won't override an already-set value) — this is why the
    repo-root .env takes precedence over the legacy backend/app/.env."""
    first = tmp_path / "first.env"
    second = tmp_path / "second.env"
    first.write_text("SEC_ANALYZER_TEST_C=first\n")
    second.write_text("SEC_ANALYZER_TEST_C=second\n")
    os.environ.pop("SEC_ANALYZER_TEST_C", None)
    try:
        loaded = config._load_env_files(first, second)
        assert loaded == [first, second]
        assert os.environ["SEC_ANALYZER_TEST_C"] == "first"
    finally:
        os.environ.pop("SEC_ANALYZER_TEST_C", None)
