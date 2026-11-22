"""回答依据：把本轮真正用到的知识库片段与网页链接整理成可复核来源。

原则与数字溯源一致：只列真实存在的东西。知识库按回答同一套 BM25 检索取命中，
网页只取回答正文里出现的 http(s) 链接；没有就不返回，不猜来源。
"""

from __future__ import annotations

import re
from typing import Any

from . import db, knowledge
from .logging_utils import get_logger

log = get_logger(__name__)

_URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"\'，。；：！？、）】》]+", re.I)
_TRAILING = ".,;:!?，。；：！？、）)]}"
_MAX_KB = 3
_MAX_WEB = 3


def _host(url: str) -> str:
    try:
        from urllib.parse import urlparse

        return urlparse(url).hostname or url
    except Exception:  # noqa: BLE001 — 展示用兜底
        return url


def web_sources(answer: str) -> list[dict[str, Any]]:
    """从回答正文里提取外链；去重、去掉本机地址，最多 3 条。"""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for raw in _URL_RE.findall(answer or ""):
        url = raw.rstrip(_TRAILING)
        if not url.lower().startswith(("http://", "https://")):
            continue
        host = _host(url)
        if host in {"127.0.0.1", "localhost", "0.0.0.0"}:
            continue
        key = url.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        out.append({"kind": "web", "title": host, "url": url, "detail": url})
        if len(out) >= _MAX_WEB:
            break
    return out


async def knowledge_sources(question: str) -> list[dict[str, Any]]:
    """按与回答相同的 BM25 口径取知识库命中；同一文档只保留最高分片段。"""
    try:
        settings = await db.get_settings()
        if (settings.get("knowledge_enabled") or "on") == "off":
            return []
        docs = await db.list_indexed_attachments()
        if not docs:
            return []
        chunks: list[dict[str, Any]] = []
        for d in docs:
            for piece in knowledge.chunk_text(str(d.get("content") or "")):
                chunks.append(
                    {
                        "id": d.get("id"),
                        "filename": d.get("filename"),
                        "content": piece,
                    }
                )
        hits = knowledge.rank_chunks(question, chunks, top_k=_MAX_KB * 2)
    except Exception:  # noqa: BLE001 — 来源整理失败不影响回答
        log.exception("qa_sources.knowledge_failed")
        return []

    out: list[dict[str, Any]] = []
    seen_docs: set[Any] = set()
    for h in hits:
        doc_id = h.get("id")
        if doc_id in seen_docs:
            continue
        seen_docs.add(doc_id)
        body = " ".join(str(h.get("content") or "").split())
        out.append(
            {
                "kind": "knowledge",
                "title": str(h.get("filename") or "知识库"),
                "detail": body[:180],
                "attachment_id": doc_id,
                "score": h.get("score"),
            }
        )
        if len(out) >= _MAX_KB:
            break
    return out


async def collect_sources(question: str, answer: str) -> list[dict[str, Any]]:
    """知识库 + 网页，按知识库优先排序。"""
    kb = await knowledge_sources(question)
    web = web_sources(answer)
    return [*kb, *web]
