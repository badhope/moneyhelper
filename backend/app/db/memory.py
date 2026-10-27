"""记忆域：user_memory + reflections。"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from ._core import (
    _clamp_limit,
    _conn,
    _mark_user_data,
    fetch_all,
)
from .tenant import current_user_id

# --------------------------------------------------------------------------
# 长期记忆（user_memory：agent 记住用户长期信息）
# --------------------------------------------------------------------------


async def list_memory() -> list[dict[str, Any]]:
    """当前租户的长期记忆。"""
    from .tenant import current_user_id

    return await fetch_all(
        "SELECT * FROM user_memory WHERE user_id=? ORDER BY updated_at DESC, id DESC",
        (current_user_id(),),
    )


def memory_retrieve(
    query: str, rows: list[dict[str, Any]], top_k: int = 5
) -> list[dict[str, Any]]:
    """BM25 关键词检索（rank-bm25 库打分，无 embedding Key 的确定性语义检索降级）。

    Moneyhelper 记忆为少量长文本（几十~几百条），用 BM25 打分足够：按查询词频/逆文档
    频率给每条记忆打分取 top_k，命中即返回并排序。打分数学交给 rank-bm25
    （其 idf 带负值修正，比手写实现更稳）；中文双字+单字分词是领域定制，
    保留自实现。当后续接入 embedding API 时，可替换为本函数同签名
    （query→embeddings→余弦相似度）的向量实现，无缝升级。
    返回命中的记忆条目；空查询返回空。
    """
    q = str(query or "").strip().lower()
    if not q or not rows:
        return []

    # 中文按双字 + 单字切分（双字利于语义，单字兜底避免"买"与"买房子"错配），英文按词
    def _tokens(text: str) -> list[str]:
        text = str(text).lower()
        toks: list[str] = []
        for seg in re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", text):
            if re.fullmatch(r"[\u4e00-\u9fff]+", seg):
                for i in range(len(seg) - 1):
                    toks.append(seg[i : i + 2])
                for ch in seg:
                    toks.append(ch)
            else:
                toks.append(seg)
        return toks

    from rank_bm25 import BM25L

    corpus = [r.get("content") or "" for r in rows]
    # 用 BM25L 而非 BM25Okapi：记忆语料很小（几~几百条），Okapi 的 idf 公式在
    # n≈N 时会得到 0 甚至负值，导致命中全部归零被过滤；BM25L 的 idf 带 +1，
    # 恒为正，与真实语料规模下的检索预期一致。
    bm25 = BM25L([_tokens(c) for c in corpus])
    scores = bm25.get_scores(_tokens(q))
    scored = sorted(zip(scores, rows, strict=True), key=lambda x: x[0], reverse=True)
    return [r for s, r in scored[:top_k] if s > 0]


async def add_memory(content: str, kind: str = "fact") -> dict[str, Any]:
    """写入一条长期记忆；内容完全相同则只刷新时间戳（天然去重）。"""
    content = str(content or "").strip()
    if not content:
        raise ValueError("记忆内容不能为空")
    if len(content) > 500:
        content = content[:500]
    kind = str(kind or "fact").strip()[:20] or "fact"
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = await _conn()
    cur = await conn.execute(
        "SELECT id FROM user_memory WHERE user_id=? AND content=? LIMIT 1",
        (current_user_id(), content),
    )
    row = await cur.fetchone()
    if row:
        await conn.execute(
            "UPDATE user_memory SET updated_at=?, kind=? WHERE user_id=? AND id=?",
            (now, kind, current_user_id(), row["id"]),
        )
        await conn.commit()
        return {"ok": True, "id": row["id"], "deduped": True}
    await conn.execute(
        "INSERT INTO user_memory(user_id,content,kind,created_at,updated_at)"
        " VALUES(?,?,?,?,?)",
        (current_user_id(), content, kind, now, now),
    )
    await _mark_user_data(conn)
    await conn.commit()
    cur = await conn.execute("SELECT last_insert_rowid() AS id")
    row = await cur.fetchone()
    return {"ok": True, "id": row["id"]}


async def delete_memory(mem_id: int) -> dict[str, Any]:
    conn = await _conn()
    cur = await conn.execute(
        "DELETE FROM user_memory WHERE user_id=? AND id=?", (current_user_id(), mem_id)
    )
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "deleted": cur.rowcount}


async def clear_memory() -> dict[str, Any]:
    conn = await _conn()
    cur = await conn.execute(
        "DELETE FROM user_memory WHERE user_id=?", (current_user_id(),)
    )
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "deleted": cur.rowcount}


async def delete_memory_by_kind(kind: str) -> dict[str, Any]:
    """按 kind 精确匹配批量删除 user_memory（用于同月订阅提醒去重 + 其他分类清理）。"""
    if not kind:
        return {"ok": False, "reason": "empty kind"}
    conn = await _conn()
    cur = await conn.execute(
        "DELETE FROM user_memory WHERE user_id=? AND kind=?", (current_user_id(), kind)
    )
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "deleted": cur.rowcount}


async def touch_memory(mem_id: int) -> dict[str, Any]:
    """记忆被注入/使用时刷新 last_used（主动遗忘：只淘汰长期未用）。"""
    conn = await _conn()
    await conn.execute(
        "UPDATE user_memory SET last_used=? WHERE user_id=? AND id=?",
        (
            datetime.now().astimezone().isoformat(timespec="seconds"),
            current_user_id(),
            int(mem_id),
        ),
    )
    await conn.commit()
    return {"ok": True}


async def forget_memory(older_than_days: int = 180) -> dict[str, Any]:
    """主动遗忘：删除超过 N 天未被使用的记忆。last_used 为空视为最近录入不删。

    返回删除条数；用于设置页「清理久未使用的记忆」。
    """
    conn = await _conn()
    import datetime as _dt

    cutoff = (
        _dt.datetime.now().astimezone() - _dt.timedelta(days=int(older_than_days))
    ).isoformat(timespec="seconds")
    cur = await conn.execute(
        "DELETE FROM user_memory WHERE user_id=? AND last_used != '' AND last_used < ?",
        (current_user_id(), cutoff),
    )
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "deleted": cur.rowcount or 0}


async def stale_memory_count(older_than_days: int = 180) -> int:
    """统计超过 N 天未使用的记忆条数（供前端提示）。"""
    import datetime as _dt

    cutoff = (
        _dt.datetime.now().astimezone() - _dt.timedelta(days=int(older_than_days))
    ).isoformat(timespec="seconds")
    rows = await fetch_all(
        "SELECT COUNT(*) AS n FROM user_memory"
        " WHERE user_id=? AND last_used != '' AND last_used < ?",
        (current_user_id(), cutoff),
    )
    return int(rows[0]["n"]) if rows else 0


# --------------------------------------------------------------------------
# 经验库（reflections：P1 反思/踩坑复盘）
# --------------------------------------------------------------------------


async def add_reflection(
    tool: str, args: dict[str, Any], error: str, lesson: str
) -> dict[str, Any]:
    """记录一次工具失败的「踩坑点」。同一 (tool, lesson) 近场合并去重。"""
    tool = str(tool or "").strip()[:60]
    error = str(error or "").strip()[:500]
    lesson = str(lesson or "").strip()[:400]
    if not tool:
        raise ValueError("tool 不能为空")
    conn = await _conn()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    # 相同工具 + 相同教训 → 去重（仅刷新时间），避免一条错误刷屏几十条
    dup = await (
        await conn.execute(
            "SELECT id FROM reflections WHERE tool=? AND lesson=? AND resolved_at='' LIMIT 1",
            (tool, lesson),
        )
    ).fetchone()
    if dup:
        await conn.execute(
            "UPDATE reflections SET created_at=?, args_json=? WHERE id=?",
            (now, json.dumps(args or {}, ensure_ascii=False)[:800], dup["id"]),
        )
        await conn.commit()
        return {"ok": True, "id": dup["id"], "deduped": True}
    cur = await conn.execute(
        "INSERT INTO reflections(tool,args_json,error,lesson,created_at)"
        " VALUES(?,?,?,?,?)",
        (tool, json.dumps(args or {}, ensure_ascii=False)[:800], error, lesson, now),
    )
    await conn.commit()
    return {"ok": True, "id": cur.lastrowid, "deduped": False}


async def list_reflections(limit: int = 50) -> list[dict[str, Any]]:
    """列出未解决的踩坑点（新→旧）。"""
    rows = await fetch_all(
        "SELECT id, tool, args_json, error, lesson, created_at, resolved_at"
        " FROM reflections WHERE resolved_at='' ORDER BY created_at DESC, id DESC LIMIT ?",
        (_clamp_limit(limit),),
    )
    for r in rows:
        try:
            r["args"] = json.loads(r.pop("args_json") or "{}")
        except Exception:  # noqa: BLE001
            r["args"] = {}
    return rows


async def resolve_reflection(ref_id: int) -> dict[str, Any]:
    """标记某条踩坑已解决（后来成功），不再提示。"""
    conn = await _conn()
    await conn.execute(
        "UPDATE reflections SET resolved_at=? WHERE id=?",
        (datetime.now().astimezone().isoformat(timespec="seconds"), int(ref_id)),
    )
    await conn.commit()
    return {"ok": True}


async def clear_reflections() -> dict[str, Any]:
    conn = await _conn()
    cur = await conn.execute("DELETE FROM reflections")
    await conn.commit()
    return {"ok": True, "deleted": cur.rowcount or 0}
