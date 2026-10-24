import { useCallback, useEffect, useState } from "react";
import { Download, GitCompareArrows, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { listProvenance, type ProvenanceItem } from "@/lib/api";
import { getToken } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { fmtDate } from "@/lib/format";
import { Section, inputCls, labelCls } from "./shared";

/** 实体类型 → 展示名（与后端 record_provenance 的 entity_type 对齐） */
const ENTITY_LABEL: Record<string, string> = {
  position: "持仓",
  transaction: "流水",
  budget: "预算",
  goal: "目标",
  debt: "负债",
  subscription: "订阅",
  memory: "记忆",
  dept_report: "呈批件",
  settings: "设置",
  report: "晨报",
};

/**
 * 溯源链：每一次写操作前后的快照。
 *
 * 这是「数字可对质」的落地入口——用户能查到自己账本里每条记录是
 * 什么时候、由谁、以什么方式改的。此前只有后端接口，界面上看不到。
 */
export function ProvenanceSection() {
  const { t } = useI18n();
  const [items, setItems] = useState<ProvenanceItem[] | null>(null);
  const [entityType, setEntityType] = useState("");
  const [entityId, setEntityId] = useState("");
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(
        await listProvenance({
          entityType: entityType || undefined,
          entityId: entityId.trim() || undefined,
          limit: 100,
        }),
      );
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [entityType, entityId]);

  useEffect(() => {
    void load();
  }, [load]);

  const pretty = (raw: string | null) => {
    if (!raw) return "—";
    try {
      const v = JSON.parse(raw);
      if (v && typeof v === "object" && Object.keys(v).length === 0) return "（无）";
      return JSON.stringify(v, null, 1).slice(0, 600);
    } catch {
      return String(raw).slice(0, 300);
    }
  };

  /** 导出审计底稿：后端返回附件下载，这里用带 token 的 URL 直接触发浏览器保存。
   *  不能走 fetch + blob：HTML 里引用了打印按钮，独立文件打开体验更好。 */
  const exportReport = () => {
    const qs = new URLSearchParams();
    if (entityType) qs.set("entity_type", entityType);
    if (entityId.trim()) qs.set("entity_id", entityId.trim());
    const token = getToken();
    if (token) qs.set("token", token);
    const url = `/api/audit-report${qs.toString() ? `?${qs.toString()}` : ""}`;
    window.open(url, "_blank", "noopener");
  };

  return (
    <Section
      title={t("settings.navProvenance")}
      icon={<GitCompareArrows className="w-4 h-4 text-muted-foreground" />}
      desc={t("settings.provenanceDesc")}
    >
      <div className="@container mb-2 flex flex-wrap items-end gap-2">
        <div className="min-w-[140px] flex-1">
          <label className={labelCls}>{t("settings.provenanceType")}</label>
          <select
            className={inputCls}
            value={entityType}
            onChange={(e) => setEntityType(e.target.value)}
          >
            <option value="">{t("settings.auditAll")}</option>
            {Object.entries(ENTITY_LABEL).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="min-w-[140px] flex-1">
          <label className={labelCls}>{t("settings.provenanceId")}</label>
          <input
            className={inputCls}
            value={entityId}
            onChange={(e) => setEntityId(e.target.value)}
            placeholder="600519 / 12"
          />
        </div>
        <Button size="sm" variant="outline" onClick={() => void load()} disabled={loading}>
          <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} />
          {t("settings.refresh")}
        </Button>
        <Button size="sm" variant="outline" onClick={exportReport}>
          <Download className="w-3.5 h-3.5 mr-1.5" />
          {t("settings.exportAudit")}
        </Button>
      </div>

      {items && items.length === 0 ? (
        <div className="py-6 text-center text-xs text-muted-foreground">
          {t("settings.provenanceEmpty")}
        </div>
      ) : (
        <div className="space-y-1.5">
          {(items ?? []).map((p) => {
            const open = expanded === p.id;
            return (
              <div key={p.id} className="rounded-lg border border-border">
                <button
                  type="button"
                  aria-expanded={open}
                  onClick={() => setExpanded(open ? null : p.id)}
                  className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs hover:bg-accent/40"
                >
                  <span className="min-w-0 flex-1 truncate">
                    <span className="mr-1.5 font-medium">
                      {ENTITY_LABEL[p.entity_type] || p.entity_type}
                    </span>
                    {p.entity_id && (
                      <span className="mr-1.5 font-mono text-muted-foreground">{p.entity_id}</span>
                    )}
                    <span className="text-foreground/80">{p.action}</span>
                  </span>
                  <span className="shrink-0 text-muted-foreground">{fmtDate(p.timestamp)}</span>
                </button>
                {open && (
                  <div className="space-y-1.5 border-t border-border px-3 py-2 text-[11px]">
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
                      <span>来源：{p.source}</span>
                      <span>操作者：{p.username || "—"}</span>
                    </div>
                    <div>
                      <div className="mb-0.5 font-medium text-muted-foreground">改动前</div>
                      <pre className="max-h-40 overflow-auto rounded bg-muted/40 p-1.5 font-mono text-[10px] leading-relaxed">
                        {pretty(p.before_json)}
                      </pre>
                    </div>
                    <div>
                      <div className="mb-0.5 font-medium text-muted-foreground">改动后</div>
                      <pre className="max-h-40 overflow-auto rounded bg-muted/40 p-1.5 font-mono text-[10px] leading-relaxed">
                        {pretty(p.after_json)}
                      </pre>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      <p className="mt-2 text-[11px] text-muted-foreground">{t("settings.provenanceHint")}</p>
    </Section>
  );
}
