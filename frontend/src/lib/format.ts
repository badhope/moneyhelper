// 展示层格式化：金额 / 百分比 / 涨跌色（中国市场惯例：涨红跌绿）/ 大数缩写（随语言：zh 用万/亿，en 用 k/M/B）
// 语言由 i18n.setLang 同步（模块级 locale，避免所有调用点改签名）。

let moneyLocale: "zh" | "en" = "en";

export function setMoneyLocale(l: "zh" | "en") {
  moneyLocale = l;
}

export function getMoneyLocale(): "zh" | "en" {
  return moneyLocale;
}

/** 金额：v 为数字；signed 为真时正数加 "+"；compact 为真时大数缩写（zh：万/亿；en：k/M/B）。 */
export function fmtMoney(v: number | undefined | null, signed = false, compact = false): string {
  if (v == null || Number.isNaN(v)) return "-";
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : signed ? "+" : "";
  let body: string;
  if (compact && moneyLocale === "zh") {
    // 中文数量级：万（1e4）/ 亿（1e8）
    if (abs >= 1e8) body = `${(abs / 1e8).toFixed(2)}亿`;
    else if (abs >= 1e4) body = `${(abs / 1e4).toFixed(1)}万`;
    else body = abs.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  } else if (compact) {
    // 英文数量级：k（1e3）/ M（1e6）/ B（1e9）。
    // 此前阈值沿用中文的 1e4/1e8、除数却是 1e6/1e9：12345 显示成 ¥0.0M，
    // 英文用户看到的工资/房租/市值整体少 100 倍——直接误导决策的错误。
    if (abs >= 1e9) body = `${(abs / 1e9).toFixed(2)}B`;
    else if (abs >= 1e6) body = `${(abs / 1e6).toFixed(1)}M`;
    else if (abs >= 1e3) body = `${(abs / 1e3).toFixed(1)}k`;
    else body = abs.toLocaleString("en-US", { maximumFractionDigits: 2 });
  } else {
    body = abs.toLocaleString(moneyLocale === "zh" ? "zh-CN" : "en-US", { maximumFractionDigits: 2 });
  }
  return `${sign}¥${body}`;
}

export function fmtPct(v: number | undefined | null, withSign = false): string {
  if (v == null || Number.isNaN(v) || !Number.isFinite(v)) return "-";
  // -0 与「四舍五入后归零的负数」（-0.004 → "-0.00"）都按 0 显示：
  // 负零是真实的渲染事故（回测/行情接口都给过），不是审美问题。
  const n = v === 0 || Object.is(v, -0) ? 0 : v;
  const rounded = Number(n.toFixed(2));
  const safe = rounded === 0 ? 0 : rounded;
  const sign = safe < 0 ? "" : withSign ? "+" : "";
  return `${sign}${safe.toFixed(2)}%`;
}

/** 红涨绿跌：正值红（涨/盈），负值绿（跌/亏） */
export function pnlClass(v: number | undefined | null): string {
  if (v == null || Number.isNaN(v) || v === 0) return "text-muted-foreground";
  return v > 0 ? "text-up" : "text-down";
}

/** 日期友好显示（随语言）。非法/空输入回退到 "-"，绝不显示 "Invalid Date"。
 *  必须带年份：审计/溯源/消息列表里跨年记录只显示月日会造成误读。 */
export function fmtDate(iso: string): string {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return "-";
  try {
    return new Intl.DateTimeFormat(moneyLocale === "zh" ? "zh-CN" : "en-US", {
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(d);
  } catch {
    return "-";
  }
}

/** 纯日期显示（随语言）：只用于本来就是"某一天"的字段（采购日、发票日、到期日）。
 *  不能复用 fmtDate：它带时分，而 "2026-11-10" 会被解析成 UTC 零点，
 *  在东八区显示成 08:00，看起来像有具体时间。 */
export function fmtDay(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || "").trim());
  if (!m) return iso ? fmtDate(iso) : "-";
  const [, y, mo, d] = m;
  if (moneyLocale === "zh") return `${y}/${Number(mo)}/${Number(d)}`;
  try {
    return new Intl.DateTimeFormat("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    }).format(new Date(Date.UTC(Number(y), Number(mo) - 1, Number(d))));
  } catch {
    return `${y}-${mo}-${d}`;
  }
}

/** 月份显示：2026-09 -> zh "2026年9月" / en "Sep 2026" */
export function fmtMonth(month: string): string {
  const [y, m] = month.split("-");
  const n = Number(m);
  // 越界月份（"2026-13"）走原串回退：否则日期构造会滚到下一年，
  // 用户看到 "2027年1月" 而不是原始输入。
  if (!y || Number.isNaN(n) || n < 1 || n > 12) return month;
  const d = new Date(Number(y), n - 1, 1);
  if (Number.isNaN(d.getTime())) return month;
  return new Intl.DateTimeFormat(
    moneyLocale === "zh" ? "zh-CN" : "en-US",
    moneyLocale === "zh"
      ? { year: "numeric", month: "long" }
      : { year: "numeric", month: "short" },
  ).format(d);
}

/** token 数量显示：1234 -> "1.2k"，保持窄栏不换行（harness 上下文仪表用）。 */
export function fmtTokens(n: number | undefined | null): string {
  const v = Number(n ?? 0);
  if (!Number.isFinite(v) || v <= 0) return "0";
  if (v < 1000) return String(Math.round(v));
  if (v < 1_000_000) return `${(v / 1000).toFixed(v < 10_000 ? 1 : 0)}k`;
  return `${(v / 1_000_000).toFixed(1)}M`;
}
