"""Tests for cache_manager.py"""
import json
import time
import pytest
from pathlib import Path


pytestmark = pytest.mark.unit


def test_set_and_get_returns_data(tmp_cache_dir):
    from src.cache_manager import get_cache, set_cache
    set_cache("test_key", {"summary": "hello", "attribution": "Groq"})
    result = get_cache("test_key")
    assert result is not None
    assert result["summary"] == "hello"


def test_get_missing_key_returns_none(tmp_cache_dir):
    from src.cache_manager import get_cache
    result = get_cache("nonexistent_key")
    assert result is None


def test_cached_at_timestamp_is_stored(tmp_cache_dir):
    from src.cache_manager import get_cache, set_cache
    set_cache("ts_key", {"summary": "x"})
    result = get_cache("ts_key")
    assert "cached_at" in result


def test_key_normalisation(tmp_cache_dir):
    """Keys with spaces and slashes are stored safely."""
    from src.cache_manager import get_cache, set_cache
    set_cache("United Kingdom_Depository Institution", {"summary": "uk"})
    result = get_cache("United Kingdom_Depository Institution")
    assert result["summary"] == "uk"


def test_corrupted_cache_returns_none(tmp_cache_dir):
    from src.cache_manager import get_cache
    cache_path = tmp_cache_dir / "cache" / "bad_key.json"
    cache_path.write_text("not valid json {{{{")
    result = get_cache("bad_key")
    assert result is None


def test_age_label_today(tmp_cache_dir):
    from src.cache_manager import set_cache, cache_age_label
    set_cache("fresh_key", {"summary": "fresh"})
    label = cache_age_label("fresh_key")
    assert label == "cached today"


def test_age_label_missing_key(tmp_cache_dir):
    from src.cache_manager import cache_age_label
    label = cache_age_label("does_not_exist")
    assert label == ""


def test_overwrite_existing_cache(tmp_cache_dir):
    from src.cache_manager import get_cache, set_cache
    set_cache("overwrite_key", {"summary": "first"})
    set_cache("overwrite_key", {"summary": "second"})
    result = get_cache("overwrite_key")
    assert result["summary"] == "second"
