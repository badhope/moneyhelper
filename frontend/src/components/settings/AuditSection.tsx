import { useCallback, useEffect, useState } from "react";
import { RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm";
import { listAudit, clearAudit, type AuditItem } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { Table } from "@/components/ui/table";
import { fmtDate } from "@/lib/format";
import { Section } from "./shared";
import { errMsg } from "@/lib/utils";

const ACTION_TONE: Record<string, string> = {
  WRITE: "text-blue-600 bg-blue-50/70",
  READ_SENSITIVE: "text-amber-600 bg-amber-50/70",
  AUTH: "text-red-600 bg-red-50/70",
};

/** 审计日志：写操作 / 敏感读 / 鉴权 记录，可筛选与清空 */
export function AuditSection() {
  const { t } = useI18n();
  const [items, setItems] = useState<AuditItem[] | null>(null);
  const [filter, setFilter] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const { toast } = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await listAudit(200, filter || undefined));
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load]);

  const doClear = async () => {
    try {
      const r = await clearAudit();
      toast(`${t("settings.auditCleared")}（${r.deleted} 条）`, "ok");
      setClearOpen(false);
      void load();
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  return (
    <Section
      title={t("settings.navAudit")}
      icon={<ShieldCheck className="w-4 h-4 text-muted-foreground" />}
      desc={t("settings.auditDesc")}
    >
      <div className="flex items-center justify-between mb-2 gap-2">
        <div className="flex items-center gap-1.5">
          {(["", "WRITE", "READ_SENSITIVE", "AUTH"] as const).map((a) => (
            <button
              key={a || "all"}
              onClick={() => setFilter(a)}
              className={`px-2 py-0.5 text-xs rounded-full border transition-colors ${
                filter === a ? "border-primary/50 bg-primary/10 text-primary" : "border-border text-muted-foreground"
              }`}
            >
              {a || t("settings.auditAll")}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5">
          <Button size="sm" variant="outline" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} />
            {t("settings.refresh")}
          </Button>
          <Button size="sm" variant="outline" onClick={() => setClearOpen(true)}>
            <Trash2 className="w-3.5 h-3.5 mr-1.5" />
            {t("settings.auditClear")}
          </Button>
        </div>
      </div>

      {items && items.length === 0 ? (
        <div className="text-xs text-muted-foreground py-6 text-center">{t("settings.auditEmpty")}</div>
      ) : (
        <div className="rounded-lg border border-border overflow-auto max-h-96">
          <Table size="xs">
            <thead className="bg-muted/40 text-muted-foreground sticky top-0">
              <tr>
                <th className="px-2 py-1.5 text-left">{t("settings.auditTime")}</th>
                <th className="px-2 py-1.5 text-left">{t("settings.auditAction")}</th>
                <th className="px-2 py-1.5 text-left">{t("settings.auditPath")}</th>
                <th className="px-2 py-1.5 text-left">{t("settings.auditActor")}</th>
              </tr>
            </thead>
            <tbody>
              {(items ?? []).map((a) => (
                <tr key={a.id} className="border-t border-border/60">
                  <td className="px-2 py-1.5 whitespace-nowrap text-muted-foreground">{fmtDate(a.ts)}</td>
                  <td className="px-2 py-1.5">
                    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${ACTION_TONE[a.action] || ""}`}>
                      {a.action}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 font-mono text-xs">{a.method} {a.path}</td>
                  <td className="px-2 py-1.5 text-muted-foreground">{a.actor || "—"}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      )}
      <ConfirmDialog
        open={clearOpen}
        onOpenChange={setClearOpen}
        title={t("settings.auditClear")}
        description={t("settings.auditClearConfirm")}
        confirmText={t("settings.confirm")}
        danger
        onConfirm={() => void doClear()}
      />
    </Section>
  );
}