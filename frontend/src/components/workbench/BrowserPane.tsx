import { useEffect, useState } from "react";
import {
  ArrowUpRight, Globe2, Loader2, RefreshCw, Search, Sparkles,
} from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { hostLabel, normalizeBrowserUrl } from "@/lib/workbench";

const QUICK_SITES = [
  { name: "东方财富", url: "https://quote.eastmoney.com/", note: "A 股行情 / 自选" },
  { name: "新浪财经", url: "https://finance.sina.com.cn/", note: "财经新闻 / 全球市场" },
  { name: "雪球", url: "https://xueqiu.com/", note: "社区讨论 / 组合" },
  { name: "财联社", url: "https://www.cls.cn/", note: "快讯 / 电报" },
];

/** 右侧浏览器：地址栏 + iframe。
 *
 * 为什么不是「真浏览器」：这是网页里的右栏，没有标签页与扩展；只做一件事——
 * 回答里的外部链接、用户输入的网址，不离开当前对话就能看。很多站点会发
 * X-Frame-Options 禁止嵌入，所以永远保留「新窗口」出口并明说原因。
 */
export function BrowserPane({
  request,
}: {
  request: { url: string; id: number } | null;
}) {
  const { t } = useI18n();
  const [url, setUrl] = useState("");
  const [address, setAddress] = useState("");
  const [nonce, setNonce] = useState(0);
  const [loading, setLoading] = useState(false);
  const [invalid, setInvalid] = useState(false);

  useEffect(() => {
    if (!request?.url) return;
    setUrl(request.url);
    setAddress(request.url);
    setLoading(true);
    setNonce((n) => n + 1);
  }, [request?.id, request?.url]);

  // iframe 的 onLoad 在部分广告/埋点很重的站点可能迟迟不触发；给一个兜底，
  // 避免「正在载入」转圈到永远，让用户以为右栏卡死。
  useEffect(() => {
    if (!loading) return;
    const timer = window.setTimeout(() => setLoading(false), 12_000);
    return () => window.clearTimeout(timer);
  }, [loading, nonce, url]);

  const go = (raw: string) => {
    const next = normalizeBrowserUrl(raw);
    if (!next) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    setAddress(next);
    setUrl(next);
    setLoading(true);
    setNonce((n) => n + 1);
  };

  const external = (target: string) => {
    if (!target) return;
    window.open(target, "_blank", "noopener,noreferrer");
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 border-b border-border/60 px-2.5 py-2">
        <form
          className="flex items-center gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            go(address);
          }}
        >
          <div className="relative min-w-0 flex-1">
            <Globe2 className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder={t("workbench.urlPlaceholder")}
              aria-label={t("workbench.url")}
              inputMode="url"
              className="h-8 w-full rounded-md border border-border bg-background pl-7 pr-2 text-[11.5px] outline-none transition-colors placeholder:text-muted-foreground/70 focus:border-primary/50"
            />
          </div>
          <button
            type="submit"
            aria-label={t("workbench.go")}
            title={t("workbench.go")}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground transition-opacity hover:opacity-90"
          >
            <Search className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            disabled={!url}
            onClick={() => {
              setLoading(true);
              setNonce((n) => n + 1);
            }}
            aria-label={t("workbench.reload")}
            title={t("workbench.reload")}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40"
          >
            <RefreshCw className={loading ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
          </button>
          <button
            type="button"
            disabled={!url}
            onClick={() => external(url)}
            aria-label={t("workbench.external")}
            title={t("workbench.external")}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40"
          >
            <ArrowUpRight className="h-3.5 w-3.5" />
          </button>
        </form>
        {invalid ? (
          <p className="mt-1.5 text-[10.5px] text-red-600 dark:text-red-400">{t("workbench.urlInvalid")}</p>
        ) : url ? (
          <p className="mt-1.5 truncate text-[10.5px] text-muted-foreground" title={url}>
            {hostLabel(url)}
          </p>
        ) : null}
      </div>

      <div className="relative min-h-0 flex-1 bg-muted/20">
        {!url ? (
          <div className="h-full overflow-y-auto scroll-thin p-4">
            <div className="mb-4 flex items-start gap-2">
              <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10">
                <Sparkles className="h-3.5 w-3.5 text-primary" />
              </span>
              <div>
                <p className="text-[13px] font-medium">{t("workbench.browserStart")}</p>
                <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                  {t("workbench.browserStartHint")}
                </p>
              </div>
            </div>
            <p className="mb-2 text-[10.5px] uppercase tracking-wide text-muted-foreground">
              {t("workbench.quickSites")}
            </p>
            <div className="grid grid-cols-1 gap-1.5">
              {QUICK_SITES.map((s) => (
                <button
                  key={s.url}
                  type="button"
                  onClick={() => {
                    setAddress(s.url);
                    setUrl(s.url);
                    setLoading(true);
                    setNonce((n) => n + 1);
                  }}
                  className="group flex items-center gap-2.5 rounded-lg border border-border bg-card px-2.5 py-2 text-left transition-colors hover:border-primary/30 hover:bg-accent/60"
                >
                  <Globe2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground group-hover:text-primary" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[12px] font-medium">{s.name}</span>
                    <span className="block truncate text-[10.5px] text-muted-foreground">{s.note}</span>
                  </span>
                  <ArrowUpRight className="h-3 w-3 shrink-0 text-muted-foreground/60" />
                </button>
              ))}
            </div>
            <p className="mt-4 rounded-md border border-dashed border-border px-2.5 py-2 text-[10.5px] leading-relaxed text-muted-foreground">
              {t("workbench.iframeHint")}
            </p>
          </div>
        ) : (
          <>
            {loading && (
              <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-center justify-center gap-2 border-b border-border/60 bg-background/80 py-1.5 text-[10.5px] text-muted-foreground backdrop-blur">
                <Loader2 className="h-3 w-3 animate-spin" /> {t("workbench.loadingPage")}
              </div>
            )}
            {/* 同源页面（例如本应用自身）不给 allow-same-origin：否则脚本 + 同源
                组合能摸到父窗口，右栏就成了 DOM 逃逸口。 */}
            <iframe
              key={`${url}-${nonce}`}
              title={t("workbench.browser")}
              src={url}
              sandbox={
                (() => {
                  try {
                    return new URL(url).origin === window.location.origin
                      ? "allow-scripts allow-forms allow-popups"
                      : "allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox";
                  } catch {
                    return "";
                  }
                })()
              }
              referrerPolicy="no-referrer"
              onLoad={() => setLoading(false)}
              className="h-full w-full border-0 bg-white"
            />
          </>
        )}
      </div>
      {url && (
        <div className="shrink-0 border-t border-border/60 px-2.5 py-1.5 text-[10px] leading-relaxed text-muted-foreground">
          {t("workbench.iframeHint")}
        </div>
      )}
    </div>
  );
}
