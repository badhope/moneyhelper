"""只读分享：创建不可猜测的分享 token，公网访问固定快照，可撤销/过期。"""

from __future__ import annotations

import html
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import db
from ..artifact_export import body_html as _body_html
from ..artifact_export import body_text as _body_text
from ..artifact_export import safe_url as _safe_url
from ..auth import get_current_user

router = APIRouter()


def _render_share(item: dict[str, Any]) -> str:
    payload = item.get("payload") or {}
    runs = payload.get("runs") if isinstance(payload.get("runs"), list) else []
    title = html.escape(str(item.get("title") or "只读会话"))
    cards: list[str] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        q = _body_text(run.get("question") or "")
        a = _body_text(run.get("answer") or "")
        srcs = run.get("sources") if isinstance(run.get("sources"), list) else []
        links: list[str] = []
        for src in srcs[:6]:
            if not isinstance(src, dict):
                continue
            label = html.escape(str(src.get("title") or "来源"))
            url = _safe_url(str(src.get("url") or ""))
            if url:
                links.append(f'<a href="{url}" rel="noopener noreferrer nofollow">{label}</a>')
            else:
                links.append(f"<span>{label}</span>")
        src_html = (
            '<div class="sources"><strong>依据</strong>' + " ".join(f"<span class=chip>{x}</span>" for x in links) + "</div>"
            if links
            else ""
        )
        cards.append(
            f'<article class="turn"><div class="q">{q}</div>'
            f'<div class="a">{_body_html(run.get("answer") or "")}</div>{src_html}</article>'
        )
    if not cards:
        cards.append('<p class="empty">这个分享暂无问答内容。</p>')
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{title} · Moneyhelper 只读分享</title>
<style>
:root{{color-scheme:light dark;--bg:#f8f6f1;--card:#fff;--ink:#1d2824;--muted:#65716b;--line:#dde4df;--brand:#0f5c4a}}
@media(prefers-color-scheme:dark){{:root{{--bg:#111917;--card:#18221f;--ink:#e8f0ec;--muted:#9aada5;--line:#2b3934;--brand:#72d6be}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif}}
main{{max-width:860px;margin:0 auto;padding:32px 20px 64px}}
header{{display:flex;align-items:center;gap:12px;margin-bottom:10px}}header .mark{{width:34px;height:34px;border-radius:12px;background:var(--brand);color:#fff;display:grid;place-items:center;font-weight:700}}
h1{{font-size:22px;margin:0}} .meta{{color:var(--muted);font-size:12px;margin-bottom:22px}}
article{{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px 20px;margin:0 0 16px}}
.q{{font-weight:650;font-size:17px;margin-bottom:12px}}.a p{{margin:0 0 10px}}.a ul,.a ol{{margin:0 0 10px 22px}}.a li{{margin:3px 0}}.a h2,.a h3,.a h4{{font-size:17px;margin:14px 0 8px}}.a code{{background:var(--bg);border:1px solid var(--line);border-radius:5px;padding:1px 4px;font-size:13px}}.a pre{{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:12px;overflow-x:auto}}.a pre code{{border:0;padding:0}}
.sources{{margin-top:16px;padding-top:12px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}}.chip{{display:inline-block;margin:4px 6px 0 0;padding:3px 8px;border:1px solid var(--line);border-radius:999px}}
.chip a{{color:var(--brand);text-decoration:none}}.empty{{color:var(--muted)}}footer{{margin-top:28px;color:var(--muted);font-size:12px;text-align:center}}
</style></head><body><main>
<header><span class="mark">M</span><h1>{title}</h1></header>
<div class="meta">只读快照 · 创建于 {html.escape(str(item.get("created_at") or ""))} · 到期 {html.escape(str(item.get("expires_at") or ""))}</div>
{''.join(cards)}
<footer>由 Moneyhelper 生成 · 只读页面不可编辑，不会加载你的账本或模型</footer>
</main></body></html>"""


@router.post("/api/shares")
async def create_share(payload: dict[str, Any] = Body(...), _=Depends(get_current_user)) -> dict[str, Any]:
    thread_id = str(payload.get("thread_id") or "").strip()
    if not thread_id or len(thread_id) > 128:
        raise HTTPException(status_code=400, detail="thread_id invalid")
    runs = await db.list_runs(thread_id, limit=100)
    if not runs:
        raise HTTPException(status_code=400, detail="这个会话还没有问答，无法分享")
    sessions = await db.list_sessions()
    title = next((str(s.get("title") or "") for s in sessions if s.get("thread_id") == thread_id), "只读会话")
    snapshot = []
    for run in reversed(runs):
        snapshot.append(
            {
                "question": run.get("question") or "",
                "answer": run.get("answer") or "",
                "sources": run.get("sources") or [],
                "created_at": run.get("created_at") or "",
            }
        )
    try:
        days = int(payload.get("expire_days") or 7)
    except (TypeError, ValueError):
        days = 7
    return await db.create_share(thread_id, title, {"runs": snapshot}, expire_days=days)


@router.delete("/api/shares/{token}")
async def delete_share(token: str, _=Depends(get_current_user)) -> dict[str, Any]:
    ok = await db.revoke_share(token)
    if not ok:
        raise HTTPException(status_code=404, detail="分享不存在")
    return {"ok": True}


@router.get("/s/{token}", response_class=HTMLResponse)
async def public_share(token: str, request: Request) -> HTMLResponse:
    item = await db.get_share_public(token)
    if not item:
        return HTMLResponse(
            "<!doctype html><html lang=zh><meta charset=utf-8><meta name=robots content=noindex>"
            "<body style='font-family:sans-serif;padding:40px'><h2>分享不存在或已失效</h2>"
            "<p>链接可能已过期、被撤销，或地址不完整。</p></body></html>",
            status_code=404,
            headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
        )
    return HTMLResponse(
        _render_share(item),
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
    )
