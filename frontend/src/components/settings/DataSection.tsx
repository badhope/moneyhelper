import { useState } from "react";
import { Download, FileText, ShieldCheck, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm";
import { api } from "@/lib/api";
import { BRAND } from "@/lib/brand";
import { store } from "@/lib/store";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import type { BootstrapData, DashboardData } from "@/lib/types";
import { Section } from "./shared";

/** 数据与备份（数据源 / 恢复示例 / 导出加密备份 / 导入备份），状态与处理逻辑已下沉 */
export function DataSection({
  dashboard,
  bootstrap,
  onRestoreDemo,
}: {
  dashboard: DashboardData | null;
  bootstrap: BootstrapData;
  onRestoreDemo: () => void;
}) {
  const { t, lang } = useI18n();
  const { toast } = useToast();
  const [resetOpen, setResetOpen] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const [pendingImport, setPendingImport] = useState<{ file: File; encrypted: boolean } | null>(null);
  const [backupPass, setBackupPass] = useState("");

  const exportBackup = async () => {
    try {
      const pass = backupPass.trim();
      if (!pass && !window.confirm(t("settings.exportPlainWarn"))) {
        return;
      }
      const data = await api<Record<string, unknown>>(pass ? `/api/export?passphrase=${encodeURIComponent(pass)}` : "/api/export");
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${BRAND.name}-backup-${new Date().toISOString().slice(0, 10)}${pass ? "-encrypted" : ""}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
      toast(pass ? t("settings.backupEncrypted") : t("settings.backupDownloaded"), "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  /** 导出单文件 HTML 报告：自包含、离线可看、可打印为 PDF。
   *  与备份不同，这是「给人看的」成品，不加密、不含密钥。 */
  const exportReport = async () => {
    try {
      const a = document.createElement("a");
      a.href = `/api/export/report?lang=${encodeURIComponent(lang ?? "zh")}`;
      a.download = `${BRAND.name}-report-${new Date().toISOString().slice(0, 10)}.html`;
      a.click();
      toast(t("settings.reportDownloaded"), "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const importBackup = async (file: File) => {
    try {
      const parsed = JSON.parse(await file.text()) as Record<string, unknown>;
      const encrypted = (parsed as { encrypted?: boolean }).encrypted === true;
      if (encrypted && !backupPass.trim()) {
        toast(t("settings.backupNeedPass"), "error");
        return;
      }
      const body = encrypted ? { ...parsed, passphrase: backupPass.trim() } : parsed;
      const r = await api<{ counts: Record<string, number> }>("/api/import/backup", {
        method: "POST",
        body: JSON.stringify(body),
      });
      const c = r.counts;
      const parts = [
        `${t("settings.pos")} ${c.positions ?? 0}`,
        `${t("settings.tx")} ${c.transactions ?? 0}`,
        `${t("settings.sub")} ${c.subscriptions ?? 0}`,
        `${t("settings.debt")} ${c.debts ?? 0}`,
      ].filter((p) => Number(p.split(" ")[1]) > 0);
      toast(
        parts.length ? t("settings.restoreDone", { p: parts.join(", ") }) : t("settings.restoreDoneEmpty"),
        "ok",
      );
      await store.refreshBootstrap();
      await store.refreshDashboard();
      await store.refreshSessions();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const clearHistory = async () => {
    try {
      await api("/api/history/clear", { method: "POST" });
      await store.refreshSessions();
      toast(t("settings.clearDone"), "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  return (
    <Section title={t("settings.navData")} icon={<ShieldCheck className="w-4 h-4 text-muted-foreground" />}>
      <div className="space-y-2">
        <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>{t("settings.srcQuotes")}</span><span className="text-right text-foreground">{dashboard?.source.quotes ?? "--"}</span>
          <span>{t("settings.srcPortfolio")}</span><span className="text-right text-foreground">{dashboard ? t("settings.srcLocal") : "--"}</span>
          <span>{t("settings.srcModel")}</span>
          <span className="text-right text-foreground">
            {bootstrap.health.llm_configured ? bootstrap.health.model : t("settings.modelNone")}
          </span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0 text-xs text-muted-foreground">
            {dashboard?.source.seeded ? t("settings.demoNote") : t("settings.realNote")}
          </div>
          <Button variant="outline" size="sm" onClick={() => setResetOpen(true)}>
            {t("settings.loadDemoData")}
          </Button>
        </div>
        <div className="flex items-center justify-between gap-2 border-t border-border/60 pt-2">
          <div className="min-w-0 text-xs text-muted-foreground">{t("settings.clearHistoryDesc")}</div>
          <Button
            variant="outline"
            size="sm"
            className="shrink-0 border-danger/40 text-danger hover:bg-danger/10 hover:text-danger"
            onClick={() => setClearOpen(true)}
          >
            <Trash2 className="w-3.5 h-3.5" /> {t("settings.clearHistory")}
          </Button>
        </div>
        <div className="mt-1 border-t border-border/60 pt-3 text-[12px] font-medium text-foreground/70">
          {t("settings.backupSection")}
        </div>
        <div className="space-y-1.5">
          <input
            type="password"
            value={backupPass}
            onChange={(e) => setBackupPass(e.target.value)}
            placeholder={t("settings.backupPassPh")}
            aria-label={t("settings.backupPassPh")}
            className="w-full rounded-lg border border-input bg-background px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-ring"
            maxLength={64}
          />
          <p className="text-xs text-muted-foreground/70">{t("settings.backupPassHint")}</p>
        </div>
        <div className="flex items-center justify-between gap-2">
          <div className="text-xs text-muted-foreground">{t("settings.exportHint")}</div>
          <Button variant="outline" size="sm" onClick={() => void exportBackup()}>
            <Download className="w-3.5 h-3.5" /> {t("settings.exportBackup")}
          </Button>
        </div>
        <div className="flex items-center justify-between gap-2">
          <div className="text-xs text-muted-foreground">{t("settings.reportHint")}</div>
          <Button variant="outline" size="sm" onClick={() => void exportReport()}>
            <FileText className="w-3.5 h-3.5" /> {t("accounts.export")}
          </Button>
        </div>
        <div className="flex items-center justify-between gap-2 pt-3 border-t border-border/60">
          <div className="text-xs text-muted-foreground">
            {t("settings.importHint")}
          </div>
          <label className="inline-flex h-8 shrink-0 cursor-pointer items-center justify-center gap-2 whitespace-nowrap rounded-md border border-border bg-transparent px-3 text-xs font-medium transition-colors hover:bg-accent hover:text-accent-foreground">
            <Upload className="w-3.5 h-3.5" /> {t("settings.importBackup")}
            <input
              type="file"
              accept=".json,application/json"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (!f) return;
                // 选择文件时先探测是否加密：明文备份走专门的更强警告弹窗
                void f.text()
                  .then((txt) => {
                    let encrypted = false;
                    try {
                      encrypted = (JSON.parse(txt) as { encrypted?: boolean }).encrypted === true;
                    } catch {
                      // 非法 JSON 交给后端返回 400，仍按明文路径确认
                    }
                    setPendingImport({ file: f, encrypted });
                  })
                  .catch(() => setPendingImport({ file: f, encrypted: false }));
              }}
            />
          </label>
        </div>
      </div>

      <ConfirmDialog
        open={resetOpen}
        onOpenChange={setResetOpen}
        title={t("settings.restoreDemoTitle")}
        description={t("settings.restoreDemoDesc")}
        confirmText={t("settings.restoreDemo")}
        danger
        onConfirm={() => {
          setResetOpen(false);
          void onRestoreDemo();
        }}
      />

      <ConfirmDialog
        open={clearOpen}
        onOpenChange={setClearOpen}
        title={t("settings.clearHistoryTitle")}
        description={t("settings.clearHistoryDesc")}
        confirmText={t("settings.clearHistoryConfirm")}
        danger
        onConfirm={() => {
          setClearOpen(false);
          void clearHistory();
        }}
      />

      <ConfirmDialog
        open={pendingImport !== null}
        onOpenChange={(o) => {
          if (!o) setPendingImport(null);
        }}
        title={t(pendingImport?.encrypted ? "settings.restoreTitle" : "settings.restorePlainTitle")}
        description={t(pendingImport?.encrypted ? "settings.restoreDesc" : "settings.restorePlainDesc")}
        confirmText={t("settings.restoreDemo")}
        danger
        onConfirm={() => {
          const f = pendingImport;
          setPendingImport(null);
          if (f) void importBackup(f.file);
        }}
      />
    </Section>
  );
}
