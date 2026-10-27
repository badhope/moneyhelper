import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, Loader2, Package, Search, Sparkles, Star, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Section, inputCls } from "./shared";

interface MarketItem {
  id: string;
  name: string;
  kind: string;
  category: string;
  source: string;
  url: string;
  stars: number;
  description: string;
  installed: boolean;
}

const KIND_LABEL: Record<string, string> = {
  skills: "Skill",
  roles: "角色",
  rules: "规则",
  hooks: "Hook",
  prompts: "提示词",
  mcp: "MCP",
};

/**
 * 插件市场：内置一批热门开源 skill / agent / 规则 / MCP，一键安装到本地。
 *
 * 与「下载第三方代码」的边界：市场条目只写配置（不执行第三方脚本）；
 * MCP 安装后默认停用，由用户显式启用，避免离线环境被外部服务拖慢。
 */
export function MarketplaceSection() {
  const { t } = useI18n();
  const { toast } = useToast();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [urlKind, setUrlKind] = useState("skills");
  const [installingRemote, setInstallingRemote] = useState(false);

  const list = useQuery({
    queryKey: ["/api/studio/market/list"],
    queryFn: () => api<{ items: MarketItem[]; categories: string[] }>("/api/studio/market/list"),
  });
  const items = list.data?.items ?? [];
  const categories = list.data?.categories ?? [];

  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: ["/api/studio/market/list"] });
    await qc.invalidateQueries({ queryKey: ["/api/studio/overview"] });
  };

  const install = async (id: string) => {
    setBusy(id);
    try {
      const r = await api<{ ok: boolean; error?: string }>("/api/studio/market/install", {
        method: "POST",
        body: JSON.stringify({ id }),
      });
      if (!r.ok) throw new Error(r.error || t("studio.installFail"));
      await refresh();
      toast(t("studio.installed"), "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(null);
    }
  };

  const uninstall = async (id: string) => {
    setBusy(id);
    try {
      await api(`/api/studio/market/${encodeURIComponent(id)}`, { method: "DELETE" });
      await refresh();
      toast(t("studio.uninstalled"), "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(null);
    }
  };

  const installAll = async () => {
    setBusy("__all__");
    try {
      const r = await api<{ ok: boolean; saved: unknown[]; mcp_configured: string[]; errors: unknown[] }>(
        "/api/studio/market/install-recommended",
        { method: "POST" },
      );
      await refresh();
      const n = r.saved?.length ?? 0;
      toast(t("studio.installAllDone", { n, mcp: r.mcp_configured?.length ?? 0 }), "ok");
      if (r.errors?.length) toast(t("studio.installPartial", { n: r.errors.length }), "error");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(null);
    }
  };

  const installUrl = async () => {
    const u = url.trim();
    if (!u) return;
    setInstallingRemote(true);
    try {
      const r = await api<{ ok: boolean; saved: { name: string }[]; errors: { file: string; error: string }[] }>(
        "/api/studio/import/url",
        { method: "POST", body: JSON.stringify({ url: u, kind: urlKind }) },
      );
      const n = r.saved?.length ?? 0;
      if (n) toast(t("studio.urlInstalled", { n }), "ok");
      if (r.errors?.length) {
        toast(`${r.errors[0].file}: ${r.errors[0].error}`, "error");
      }
      if (!n && !r.errors?.length) toast(t("studio.importEmpty"), "error");
      await refresh();
      setUrl("");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setInstallingRemote(false);
    }
  };

  const filtered = useMemo(
    () =>
      items.filter(
        (i) =>
          (cat === "all" || i.category === cat) &&
          (!q.trim() ||
            i.name.toLowerCase().includes(q.toLowerCase()) ||
            i.description.toLowerCase().includes(q.toLowerCase())),
      ),
    [items, cat, q],
  );

  return (
    <Section
      title={t("settings.navMarket")}
      icon={<Package className="w-4 h-4 text-muted-foreground" />}
      desc={t("studio.marketDesc")}
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => void installAll()} disabled={busy !== null}>
            {busy === "__all__" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
            {t("studio.installRecommended")}
          </Button>
          <span className="text-[11px] text-muted-foreground">{t("studio.marketCount", { n: items.length })}</span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-40 flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              className={`${inputCls} pl-8`}
              placeholder={t("studio.marketSearch")}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <select className={`${inputCls} w-auto`} value={cat} onChange={(e) => setCat(e.target.value)}>
            <option value="all">{t("studio.marketAll")}</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-wrap items-end gap-2 rounded-lg border border-dashed border-border p-2.5">
          <div className="min-w-40 flex-1">
            <label className="block text-[11px] text-muted-foreground">{t("studio.urlLabel")}</label>
            <input
              className={inputCls}
              placeholder="https://github.com/.../SKILL.md"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              spellCheck={false}
            />
          </div>
          <select className={`${inputCls} w-auto`} value={urlKind} onChange={(e) => setUrlKind(e.target.value)}>
            {Object.entries(KIND_LABEL)
              .filter(([k]) => k !== "mcp")
              .map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
          </select>
          <Button size="sm" variant="outline" onClick={() => void installUrl()} disabled={installingRemote || !url.trim()}>
            {installingRemote ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
            {t("studio.urlInstall")}
          </Button>
        </div>

        {list.isPending ? (
          <p className="py-3 text-center text-xs text-muted-foreground">{t("studio.loading")}</p>
        ) : (
          <ul className="grid gap-2 sm:grid-cols-2">
            {filtered.map((item) => (
              <li key={item.id} className="flex flex-col rounded-lg border border-border p-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5 text-[13px] font-medium">
                      {item.name}
                      <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                        {KIND_LABEL[item.kind] ?? item.kind}
                      </span>
                      {item.stars > 0 && (
                        <span className="inline-flex items-center gap-0.5 text-[10px] text-amber-600">
                          <Star className="h-2.5 w-2.5 fill-current" />
                          {item.stars >= 1000 ? `${Math.round(item.stars / 1000)}k` : item.stars}
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">{item.description}</p>
                    {item.source !== "internal" && (
                      <a
                        href={item.url || item.source}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="mt-0.5 block truncate text-[10.5px] text-primary/70 hover:underline"
                      >
                        {item.source}
                      </a>
                    )}
                  </div>
                  <Button
                    size="sm"
                    variant={item.installed ? "outline" : "default"}
                    className={cn("h-7 shrink-0 px-2 text-[11px]")}
                    disabled={busy !== null}
                    onClick={() => void (item.installed ? uninstall(item.id) : install(item.id))}
                  >
                    {busy === item.id ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : item.installed ? (
                      <Trash2 className="h-3 w-3" />
                    ) : (
                      <Download className="h-3 w-3" />
                    )}
                    {item.installed ? t("studio.uninstall") : t("studio.install")}
                  </Button>
                </div>
                {item.installed && (
                  <div className="mt-1 inline-flex items-center gap-1 text-[10.5px] text-emerald-600">
                    <Check className="h-3 w-3" /> {t("studio.alreadyInstalled")}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Section>
  );
}
