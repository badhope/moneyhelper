"""老库补列：`CREATE TABLE IF NOT EXISTS` 不会改老表，这里逐项 ALTER。"""

from __future__ import annotations

from ..logging_utils import get_logger
from . import _core

log = get_logger(__name__)


async def _migrate_add_columns() -> None:
    """老库增量迁移：为已有表补新列（CREATE TABLE IF NOT EXISTS 不会改老表）。"""
    assert _core._db is not None
    cols = {
        # 会话列表深化：置顶与归档（旧库补列，默认都不置顶、不归档）
        "sessions": {
            "pinned": "INTEGER NOT NULL DEFAULT 0",
            "archived": "INTEGER NOT NULL DEFAULT 0",
        },
        "subscriptions": {"due_day": "TEXT NOT NULL DEFAULT ''"},
        "debts": {"due_day": "TEXT NOT NULL DEFAULT ''"},
        # 问答来源可溯源：route/llm 落库后历史回答也能显示真实来源（此前只能显示等级）
        "runs": {
            "route": "TEXT NOT NULL DEFAULT ''",
            "llm": "TEXT NOT NULL DEFAULT ''",
            "route_reason": "TEXT NOT NULL DEFAULT ''",
            "tools": "TEXT NOT NULL DEFAULT ''",
            "actions": "TEXT NOT NULL DEFAULT '[]'",
            # 已发送消息回看附件：只存 id/文件名/类型，正文仍在 attachments 表
            "attachments_json": "TEXT NOT NULL DEFAULT '[]'",
            # harness：按轮 token 计量（模型真实回传，无模型时保持 0）
            "tokens_in": "INTEGER NOT NULL DEFAULT 0",
            "tokens_out": "INTEGER NOT NULL DEFAULT 0",
        },
        # 主动遗忘：记录每次被注入/使用的时间，便于按未使用时长清理
        "user_memory": {"last_used": "TEXT NOT NULL DEFAULT ''"},
        # 知识库：附件可标记为「入库」，问答时按 BM25 检索其片段
        "attachments": {
            "indexed": "INTEGER NOT NULL DEFAULT 0",
            "mime": "TEXT NOT NULL DEFAULT ''",
            "data": "TEXT NOT NULL DEFAULT ''",
        },
        # 审计哈希链：旧库补列；历史行没有哈希，验链时作为 legacy 前缀跳过
        "audit_logs": {
            "prev_hash": "TEXT NOT NULL DEFAULT ''",
            "entry_hash": "TEXT NOT NULL DEFAULT ''",
        },
        # 切片 7b：用户显式选择的工作租户（全局租户切换）
        "users": {"active_tenant_id": "INTEGER"},
        # 切片 8：付款可关联报销单或应付单；应付付款生成付款凭证草稿
        "payments": {"payable_id": "INTEGER", "gl_entry_id": "INTEGER"},
        # 切片 9：银行流水可自动生成凭证，用 gl_entry_id 记下归属（兼作幂等标记）
        "bank_transactions": {"gl_entry_id": "INTEGER"},
    }
    # transactions 表：新增 owner_id（交易归属成员）与 is_shared（是否共享）
    tx_cols = await _core._db.execute("PRAGMA table_info(transactions)")
    tx_existing = {row["name"] for row in await tx_cols.fetchall()}
    if "owner_id" not in tx_existing:
        await _core._db.execute(
            "ALTER TABLE transactions ADD COLUMN owner_id INTEGER REFERENCES members(id)"
        )
    if "is_shared" not in tx_existing:
        await _core._db.execute(
            "ALTER TABLE transactions ADD COLUMN is_shared INTEGER NOT NULL DEFAULT 1"
        )

    for table, adds in cols.items():
        cur = await _core._db.execute(f"PRAGMA table_info({table})")
        existing = {row["name"] for row in await cur.fetchall()}
        for col, decl in adds.items():
            if col not in existing:
                await _core._db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

    # 付款唯一性按来源拆分：报销付款 claim_id>0；应付付款 payable_id 非空。
    # 旧库原索引是全表 UNIQUE(tenant_id,claim_id)，必须替换成部分索引，
    # 否则所有应付付款都会以 claim_id=0 互相冲突。
    await _core._db.execute("DROP INDEX IF EXISTS idx_payment_tenant_claim")
    await _core._db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_tenant_claim"
        " ON payments(tenant_id, claim_id) WHERE claim_id > 0"
    )
    await _core._db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_tenant_payable"
        " ON payments(tenant_id, payable_id) WHERE payable_id IS NOT NULL"
    )


# 需要按租户隔离的表。四张"业务字段作主键"的表要重建（复合主键），
# 其余表只需加 user_id 列。
