"""本机 vault 口令：没设 VAULT_PASSPHRASE 时自动生成并持久化（0600）。"""

from __future__ import annotations

import importlib
import os
import stat

from app import main_lifespan


def test_local_vault_passphrase_generates_and_persists(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("VAULT_PASSPHRASE", raising=False)
    # data_dir 是函数内局部 import，直接替换 db_paths 里的同名函数
    db_paths = importlib.import_module("app.db.db_paths")
    monkeypatch.setattr(db_paths, "data_dir", lambda: tmp_path)

    first = main_lifespan._local_vault_passphrase()
    assert len(first) >= 8
    key_file = tmp_path / ".vault_key"
    assert key_file.exists()
    assert stat.S_IMODE(os.stat(key_file).st_mode) == 0o600
    # 第二次必须读回同一个，否则重启后旧密文全解不开
    assert main_lifespan._local_vault_passphrase() == first
