"""compat_env：新变量优先、旧前缀回退、空串视为未设置。"""

from __future__ import annotations

from app.compat_env import getenv


def test_new_name_wins(monkeypatch) -> None:
    monkeypatch.setenv("MONEYHELPER_DB_PATH", "/new.db")
    monkeypatch.setenv("XIAOMAN_DB_PATH", "/old.db")
    assert getenv("MONEYHELPER_DB_PATH") == "/new.db"


def test_legacy_name_fallback(monkeypatch) -> None:
    monkeypatch.delenv("MONEYHELPER_DB_PATH", raising=False)
    monkeypatch.setenv("XIAOMAN_DB_PATH", "/old.db")
    assert getenv("MONEYHELPER_DB_PATH") == "/old.db"


def test_empty_new_name_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("MONEYHELPER_DB_PATH", "")
    monkeypatch.setenv("XIAOMAN_DB_PATH", "/old.db")
    assert getenv("MONEYHELPER_DB_PATH") == "/old.db"


def test_default_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("MONEYHELPER_DB_PATH", raising=False)
    monkeypatch.delenv("XIAOMAN_DB_PATH", raising=False)
    assert getenv("MONEYHELPER_DB_PATH", "/default.db") == "/default.db"


def test_rejects_unknown_prefix() -> None:
    import pytest

    with pytest.raises(ValueError):
        getenv("DB_PATH")
