"""审计底稿导出（M6.1）：把 provenance 链路渲染成一份可归档的 HTML 底稿。

为什么输出 HTML 而不是 PDF：
- 项目坚持零新增重依赖（PDF 库会带几十 MB 字体与 C 扩展，PyInstaller 体积再涨）
- HTML 在浏览器里可直接"打印为 PDF"，中文排版由系统字体保证
- 同一份 HTML 既能归档也能直接发给人看，比二进制 PDF 更可核查
若将来需要服务端直出 PDF，只需在 render_audit_report 之后接一个渲染器，数据层不用改。
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any

# 单份底稿的条目上限：底稿是给人看的，超过 5000 条应该按时间段分批导出
MAX_ENTRIES = 5000


def _esc(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _fmt_amount(v: Any) -> str:
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _diff_rows(before: dict | None, after: dict | None) -> list[tuple[str, str, str]]:
    """比较前后快照，只列出真正变化的字段。"""
    b = before or {}
    a = after or {}
    keys = sorted(set(b) | set(a))
    rows: list[tuple[str, str, str]] = []
    for k in keys:
        bv, av = b.get(k), a.get(k)
        if bv == av:
            continue
        rows.append((k, _esc(bv), _esc(av)))
    return rows


def render_audit_report(
    entries: list[dict[str, Any]],
    *,
    title: str = "Moneyhelper · 审计底稿",
    entity_type: str = "",
    entity_id: str = "",
    date_from: str = "",
    date_to: str = "",
    generated_by: str = "",
) -> str:
    """渲染审计底稿 HTML。所有动态内容都经过 html.escape，避免注入。"""
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    scope_parts = []
    if entity_type:
        scope_parts.append(f"实体类型：{_esc(entity_type)}")
    if entity_id:
        scope_parts.append(f"实体 ID：{_esc(entity_id)}")
    if date_from:
        scope_parts.append(f"起始：{_esc(date_from)}")
    if date_to:
        scope_parts.append(f"截止：{_esc(date_to)}")
    scope = " ｜ ".join(scope_parts) if scope_parts else "全部记录"
    truncated = len(entries) > MAX_ENTRIES
    shown = entries[:MAX_ENTRIES]

    rows_html = []
    for e in shown:
        diffs = _diff_rows(e.get("before"), e.get("after"))
        diff_html = (
            "<table class='diff'><thead><tr><th>字段</th><th>变更前</th><th>变更后</th></tr></thead><tbody>"
            + "".join(f"<tr><td>{_esc(k)}</td><td class='old'>{bv}</td><td class='new'>{av}</td></tr>" for k, bv, av in diffs)
            + "</tbody></table>"
            if diffs
            else "<span class='muted'>（无字段变化 / 仅记录动作）</span>"
        )
        meta = e.get("metadata")
        meta_html = f"<code>{_esc(json.dumps(meta, ensure_ascii=False))}</code>" if meta else "<span class='muted'>—</span>"
        rows_html.append(
            f"""
      <section class="entry">
        <header>
          <span class="badge src-{_esc(e.get('source') or 'unknown')}">{_esc(e.get('source') or 'unknown')}</span>
          <strong>{_esc(e.get('action'))}</strong>
          <span class="ts">{_esc(e.get('timestamp'))}</span>
          <span class="id">{_esc(e.get('id'))}</span>
        </header>
        <div class="kv">
          <div><span>实体</span>{_esc(e.get('entity_type'))} / {_esc(e.get('entity_id'))}</div>
          <div><span>操作人</span>{_esc(e.get('username') or '—')}</div>
          <div class="wide"><span>上下文</span>{meta_html}</div>
        </div>
        {diff_html}
      </section>"""
        )

    summary = (
        f"<p class='warn'>记录数超过 {MAX_ENTRIES} 条，本底稿仅包含前 {MAX_ENTRIES} 条。请缩小时间或实体范围后重新导出。</p>"
        if truncated
        else ""
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{_esc(title)}</title>
<style>
  :root {{ --ink:#1f2328; --muted:#6b7280; --line:#e5e7eb; --bg:#ffffff; --accent:#0d7a66; }}
  @media print {{ @page {{ margin: 16mm; }} .no-print {{ display:none; }} }}
  * {{ box-sizing: border-box; }}
  body {{ font: 13px/1.6 -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; color:var(--ink); background:var(--bg); margin:0; padding:32px; max-width:1000px; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  .sub {{ color:var(--muted); font-size:12px; }}
  .meta {{ border:1px solid var(--line); border-radius:8px; padding:12px 14px; margin:16px 0 20px; display:grid; gap:4px; font-size:12px; }}
  .meta b {{ color:var(--muted); font-weight:500; display:inline-block; min-width:72px; }}
  .entry {{ border:1px solid var(--line); border-radius:8px; padding:12px 14px; margin-bottom:10px; page-break-inside: avoid; }}
  .entry header {{ display:flex; flex-wrap:wrap; gap:8px; align-items:baseline; margin-bottom:6px; }}
  .badge {{ font-size:10px; text-transform:uppercase; letter-spacing:.04em; padding:1px 6px; border-radius:999px; background:#f3f4f6; color:#374151; }}
  .src-api {{ background:#e0f2fe; color:#075985; }}
  .src-agent {{ background:#ede9fe; color:#5b21b6; }}
  .src-mcp {{ background:#fef3c7; color:#92400e; }}
  .src-scheduler {{ background:#dcfce7; color:#166534; }}
  .ts, .id {{ color:var(--muted); font-size:11px; font-variant-numeric:tabular-nums; }}
  .id {{ margin-left:auto; font-family:ui-monospace, Consolas, monospace; }}
  .kv {{ display:grid; grid-template-columns:1fr 1fr; gap:2px 16px; font-size:12px; margin-bottom:8px; }}
  .kv .wide {{ grid-column:1 / -1; }}
  .kv span {{ color:var(--muted); margin-right:6px; }}
  table.diff {{ width:100%; border-collapse:collapse; font-size:12px; }}
  table.diff th {{ text-align:left; color:var(--muted); font-weight:500; border-bottom:1px solid var(--line); padding:3px 6px; }}
  table.diff td {{ padding:3px 6px; border-bottom:1px solid #f3f4f6; font-variant-numeric:tabular-nums; }}
  table.diff td:first-child {{ font-family:ui-monospace, Consolas, monospace; color:#374151; }}
  .old {{ color:#b91c1c; }}
  .new {{ color:#15803d; }}
  .muted {{ color:var(--muted); }}
  .warn {{ background:#fffbeb; border:1px solid #fde68a; color:#92400e; padding:8px 12px; border-radius:6px; font-size:12px; }}
  footer {{ margin-top:24px; padding-top:10px; border-top:1px solid var(--line); color:var(--muted); font-size:11px; }}
  code {{ font-family:ui-monospace, Consolas, monospace; font-size:11px; word-break:break-all; }}
  .toolbar {{ margin-bottom:16px; }}
  .toolbar button {{ font:inherit; padding:6px 14px; border-radius:6px; border:1px solid var(--accent); background:var(--accent); color:#fff; cursor:pointer; }}
</style>
</head>
<body>
  <div class="toolbar no-print"><button onclick="window.print()">打印 / 另存为 PDF</button></div>
  <h1>{_esc(title)}</h1>
  <div class="sub">生成时间 {_esc(now)} ｜ 记录 {len(shown)} 条</div>
  <div class="meta">
    <div><b>审计范围</b>{scope}</div>
    <div><b>导出人</b>{_esc(generated_by or '本机用户')}</div>
    <div><b>数据来源</b>本地 SQLite（provenance_log），未经任何外部服务</div>
  </div>
  {summary}
  {''.join(rows_html) if rows_html else "<p class='muted'>该范围内没有任何审计记录。</p>"}
  <footer>本底稿由 Moneyhelper 自动生成。每条记录对应一次金额相关操作，before/after 为操作前后快照；未变化的字段已省略。</footer>
</body>
</html>"""
