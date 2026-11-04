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
  if (v == null || Number.isNaN(v)) return "-";
  const sign = v < 0 ? "" : withSign ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

/** 红涨绿跌：正值红（涨/盈），负值绿（跌/亏） */
export function pnlClass(v: number | undefined | null): string {
  if (v == null || Number.isNaN(v) || v === 0) return "text-muted-foreground";
  return v > 0 ? "text-up" : "text-down";
}

/** 日期友好显示（随语言） */
export function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(moneyLocale === "zh" ? "zh-CN" : "en-US", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

/** 月份显示：2026-09 -> zh "2026年9月" / en "Sep 2026" */
export function fmtMonth(month: string): string {
  const [y, m] = month.split("-");
  const n = Number(m);
  if (!y || Number.isNaN(n)) return month;
  if (moneyLocale === "zh") return `${y}年${n}月`;
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${names[n - 1]} ${y}`;
}

/** token 数量显示：1234 -> "1.2k"，保持窄栏不换行（harness 上下文仪表用）。 */
export function fmtTokens(n: number | undefined | null): string {
  const v = Number(n ?? 0);
  if (!Number.isFinite(v) || v <= 0) return "0";
  if (v < 1000) return String(Math.round(v));
  if (v < 1_000_000) return `${(v / 1000).toFixed(v < 10_000 ? 1 : 0)}k`;
  return `${(v / 1_000_000).toFixed(1)}M`;
}
