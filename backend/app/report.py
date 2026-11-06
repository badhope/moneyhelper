"""可交互 HTML 报告：把总览数据导成单文件、离线可看、可打印的报表。

为什么不用 PDF：PDF 生成要额外依赖（wkhtmltopdf/weasyprint），在用户机器上
装不上就等于功能不存在；而单个 HTML 文件双击即开、能打印成 PDF、图表可悬停、
数据不外发——对本地优先的产品是更合适的选择。

设计约束：
  - **零外部依赖**：不引 CDN、不加载字体、不调 JS 库；图表用内联 SVG 手绘，
    交互用原生 <details>/CSS hover。断网也能完整查看。
  - **可打印**：@media print 下隐藏交互控件、保留数据，A4 分页不截断表格。
  - **不注入**：所有文本经 html.escape，用户数据（项目名/类目）不可执行脚本。
  - 数字口径直接取自 dashboard / 各计算模块，本模块只负责排版，不重算。
"""

from __future__ import annotations

import html
from typing import Any

MAX_ROWS = 60


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _money(v: Any) -> str:
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        return "—"
    return (f"{n:,.2f}").rstrip("0").rstrip(".") if n % 1 else f"{n:,.0f}"


def _pct(v: Any) -> str:
    try:
        return f"{float(v or 0):.2f}%"
    except (TypeError, ValueError):
        return "—"


def _bar_chart(rows: list[tuple[str, float]], width: int = 640, bar_h: int = 22) -> str:
    """盈亏条形图（内联 SVG）：负值向左、正值向右，零轴居中。

    三列固定布局：名称 | 图形区 | 数值。数值放最右侧固定列，
    不跟随条端——否则负值的数值会溢出到左侧压住标的名称。
    """
    if not rows:
        return '<p class="muted">无数据</p>'
    max_abs = max(abs(v) for _, v in rows) or 1.0
    name_w, value_w, pad = 140, 64, 8
    height = bar_h * len(rows) + pad * 2
    plot_w = width - name_w - value_w - pad * 2
    zero_x = name_w + pad + plot_w / 2
    scale = (plot_w / 2) / max_abs
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="bar chart">',
        f'<line x1="{zero_x:.1f}" y1="0" x2="{zero_x:.1f}" y2="{height}" '
        'stroke="#cbd5e1" stroke-width="1"/>',
    ]
    for i, (name, val) in enumerate(rows):
        y = pad + i * bar_h
        w = abs(val) * scale
        x = zero_x if val >= 0 else zero_x - w
        color = "#dc2626" if val >= 0 else "#059669"
        parts.append(
            f'<rect x="{x:.1f}" y="{y + 6}" width="{max(w, 0.5):.1f}" '
            f'height="{bar_h - 12}" rx="3" fill="{color}"/>'
        )
        parts.append(
            f'<text x="{name_w}" y="{y + bar_h - 6}" font-size="11" fill="#334155" '
            f'text-anchor="end">{_e(name[:18])}</text>'
        )
        parts.append(
            f'<text x="{width - pad}" y="{y + bar_h - 6}" font-size="11" fill="#475569" '
            f'text-anchor="end">{_money(val)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _share_bars(rows: list[tuple[str, float]], width: int = 640, bar_h: int = 22) -> str:
    """占比条（内联 SVG）：从 0 起算的正向条形，附带百分比。

    与盈亏图不同，占比没有负值，因此不需要零轴居中——用满宽度更能看出结构。
    """
    if not rows:
        return '<p class="muted">无数据</p>'
    label_w, pad = 150, 8
    height = bar_h * len(rows) + pad * 2
    plot_w = width - label_w - pad * 2 - 56
    max_pct = max(p for _, p in rows) or 1.0
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="allocation chart">'
    ]
    for i, (name, pct) in enumerate(rows):
        y = pad + i * bar_h
        w = pct / max_pct * plot_w
        parts.append(
            f'<rect x="{label_w + pad}" y="{y + 6}" width="{max(w, 0.5):.1f}" '
            f'height="{bar_h - 12}" rx="3" fill="#0d9488" opacity="0.85"/>'
        )
        parts.append(
            f'<text x="{label_w}" y="{y + bar_h - 6}" font-size="11" fill="#334155" '
            f'text-anchor="end">{_e(name[:20])}</text>'
        )
        parts.append(
            f'<text x="{label_w + pad + w + 6:.1f}" y="{y + bar_h - 6}" '
            f'font-size="11" fill="#475569">{pct:.1f}%</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _line_chart(points: list[float], width: int = 640, height: int = 160) -> str:
    """折线图（内联 SVG）：用于净值/权益曲线趋势。"""
    if len(points) < 2:
        return '<p class="muted">数据点不足</p>'
    lo, hi = min(points), max(points)
    span = (hi - lo) or 1.0
    pad = 12
    step = (width - pad * 2) / (len(points) - 1)
    coords = []
    for i, v in enumerate(points):
        x = pad + i * step
        y = height - pad - (v - lo) / span * (height - pad * 2)
        coords.append(f"{x:.1f},{y:.1f}")
    area = f"M{pad:.1f},{height - pad} L{' L'.join(coords)} L{width - pad:.1f},{height - pad} Z"
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="line chart">'
        f'<path d="{area}" fill="#0d9488" opacity="0.10"/>'
        f'<polyline points="{" ".join(coords)}" fill="none" stroke="#0d9488" '
        'stroke-width="2" stroke-linejoin="round"/>'
        f'<text x="{width - pad}" y="14" font-size="10" fill="#64748b" '
        f'text-anchor="end">最高 {_money(hi)}</text>'
        f'<text x="{width - pad}" y="{height - 2}" font-size="10" fill="#64748b" '
        f'text-anchor="end">最低 {_money(lo)}</text>'
        "</svg>"
    )


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join(
        "<tr>{}</tr>".format("".join(f"<td>{_e(c)}</td>" for c in r)) for r in rows[:MAX_ROWS]
    )
    return f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


_CSS = """
:root{--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--bg:#fff;--accent:#0d9488}
*{box-sizing:border-box}
body{margin:0;padding:32px;font:14px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:var(--ink);background:var(--bg)}
.wrap{max-width:960px;margin:0 auto}
header{border-bottom:2px solid var(--ink);padding-bottom:12px;margin-bottom:24px}
h1{margin:0 0 4px;font-size:24px;letter-spacing:-.01em}
h2{margin:28px 0 10px;font-size:16px;border-left:3px solid var(--accent);padding-left:8px}
.muted{color:var(--muted);font-size:12px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0}
.kpi{border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.kpi b{display:block;font-size:19px;font-variant-numeric:tabular-nums}
.kpi span{color:var(--muted);font-size:12px}
table{width:100%;border-collapse:collapse;font-size:13px;margin:8px 0}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--muted);font-weight:600;font-size:12px}
td:nth-child(n+2){font-variant-numeric:tabular-nums}
details{border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:10px 0}
summary{cursor:pointer;font-weight:600;font-size:13px}
.caveat{background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:10px 12px;font-size:12.5px;margin:12px 0}
.caveat li{margin:4px 0}
footer{margin-top:32px;padding-top:12px;border-top:1px solid var(--line);color:var(--muted);font-size:11.5px}
@media print{
  body{padding:0}
  details{display:block}
  details>summary{display:none}
  h2{break-after:avoid}
  table{break-inside:auto}
  tr{break-inside:avoid}
  .noprint{display:none}
}
"""


def build_report(
    *,
    dashboard: dict[str, Any],
    accounts: dict[str, Any] | None = None,
    actions: dict[str, Any] | None = None,
    title: str = "财务报告",
    lang: str = "zh",
    generated_at: str = "",
) -> str:
    """生成自包含 HTML 报告字符串。

    输入都是已算好的结构（dashboard / 合并账户 / 决策中心），本函数不重算指标。
    """
    en = str(lang).lower().startswith("en")
    t = (lambda zh, e: e) if en else (lambda zh, e: zh)

    totals = dashboard.get("totals") or {}
    cashflow = dashboard.get("cashflow") or {}
    positions = dashboard.get("positions") or []
    flags = dashboard.get("flags") or []

    kpis = [
        (t("总市值", "Market value"), _money(totals.get("total_market_value"))),
        (t("累计盈亏", "Total P&L"), _money(totals.get("total_pnl"))),
        (t("累计收益率", "Total return"), _pct(totals.get("total_pnl_pct"))),
        (t("本月结余", "Monthly net"), _money(cashflow.get("net"))),
        (t("储蓄率", "Savings rate"), _pct(cashflow.get("savings_rate"))),
    ]
    if accounts:
        kpis.append((t("合并净资产", "Merged net worth"),
                     _money(accounts.get("total_net_worth"))))

    pnl_rows = [(str(p.get("name") or p.get("symbol") or ""), float(p.get("pnl") or 0))
                for p in positions if p.get("kind") != "现金"]

    pos_rows = [
        [p.get("name") or p.get("symbol"), p.get("kind"), _money(p.get("market_value")),
         _money(p.get("pnl")), _pct(p.get("pnl_pct"))]
        for p in positions
    ]

    cat_rows = [[c.get("category"), _money(c.get("amount"))]
                for c in (cashflow.get("by_category") or [])]

    action_rows = [
        [a.get("domain_label"), a.get("title"), a.get("detail")]
        for a in ((actions or {}).get("items") or [])
    ]

    caveats = list((accounts or {}).get("caveats") or [])
    if flags:
        caveats.append(t(
            "报告中的风险标记来自本地确定性规则，不构成投资建议。",
            "Risk flags come from local deterministic rules and are not investment advice.",
        ))

    parts: list[str] = [
        "<!doctype html>",
        '<html lang="%s">' % ("en" if en else "zh-CN"),
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>{_e(title)}</title>",
        f"<style>{_CSS}</style>",
        "</head><body><div class='wrap'>",
        "<header><h1>{}</h1><p class='muted'>{}{}</p></header>".format(_e(title), _e(t("生成于 ", "Generated ")), _e(generated_at or t("—", "—"))),
    ]

    parts.append("<div class='kpis'>")
    for label, value in kpis:
        parts.append(f"<div class='kpi'><b>{_e(value)}</b><span>{_e(label)}</span></div>")
    parts.append("</div>")

    if caveats:
        parts.append("<div class='caveat'><strong>{}</strong><ul>".format(_e(t("口径说明", "How to read this"))))
        parts.append("".join(f"<li>{_e(c)}</li>" for c in caveats))
        parts.append("</ul></div>")

    if action_rows:
        parts.append("<h2>{}</h2>".format(_e(t("现在该做什么", "What to do next"))))
        parts.append(_table([t("领域", "Area"), t("建议", "Action"), t("依据", "Why")],
                            action_rows))

    parts.append("<h2>{}</h2>".format(_e(t("持仓盈亏贡献", "P&L contribution"))))
    parts.append(_bar_chart(pnl_rows))

    if pos_rows:
        parts.append("<h2>{}</h2>".format(_e(t("持仓明细", "Holdings"))))
        parts.append(_table([t("标的", "Instrument"), t("类型", "Kind"),
                             t("市值", "Value"), t("盈亏", "P&L"), t("收益率", "Return")],
                            pos_rows))

    # 资产占比：按市值排序的横向占比条，比「按持仓顺序连线」有意义——
    # 持仓之间没有时间或顺序关系，连成折线是伪信息。
    if pos_rows:
        total_mv = sum(float(p.get("market_value") or 0) for p in positions)
        if total_mv > 0:
            share_rows = sorted(
                [(str(p.get("name") or p.get("symbol") or ""),
                  float(p.get("market_value") or 0) / total_mv * 100.0) for p in positions],
                key=lambda x: x[1], reverse=True,
            )
            parts.append("<h2>{}</h2>".format(_e(t("资产占比", "Allocation share"))))
            parts.append(_share_bars(share_rows))

    if cat_rows:
        parts.append("<h2>{}</h2>".format(_e(t("本月支出构成", "Spending by category"))))
        parts.append(_table([t("类目", "Category"), t("金额", "Amount")], cat_rows))

    if accounts and accounts.get("sources"):
        parts.append("<h2>{}</h2>".format(_e(t("账户来源", "Account sources"))))
        parts.append(_table(
            [t("账户", "Account"), t("净值", "Net worth"),
             t("计入合计", "Counted"), t("说明", "Note")],
            [[s.get("name"), _money(s.get("net_worth")),
              t("是", "Yes") if s.get("counted") else t("否（未折算）", "No (not converted)"),
              s.get("detail")] for s in accounts["sources"]],
        ))

    parts.append(
        "<footer>{}<br>{}</footer>".format(
            _e(t("本报告为单文件离线 HTML：不含外部脚本、不上传任何数据。",
                 "Single-file offline HTML: no external scripts, no data leaves your machine.")),
            _e(t("可浏览器「打印 → 另存为 PDF」得到归档版本。",
                 "Use Print → Save as PDF to archive.")),
        )
    )
    parts.append("</div></body></html>")
    return "".join(parts)
