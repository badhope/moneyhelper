import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, ShieldCheck, ShieldHalf, Unlock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Section } from "./shared";

interface Permissions {
  mode: "open" | "standard" | "strict";
  allow_chat_admin: boolean;
  allow_cli_admin: boolean;
  allow_remote_install: boolean;
}

const MODES = [
  { id: "open", labelKey: "studio.permOpen", descKey: "studio.permOpenDesc", icon: Unlock },
  { id: "standard", labelKey: "studio.permStandard", descKey: "studio.permStandardDesc", icon: ShieldHalf },
  { id: "strict", labelKey: "studio.permStrict", descKey: "studio.permStrictDesc", icon: Lock },
] as const;

const LOCKED_KEYS = [
  "approval_threshold",
  "ai_api_key",
  "api_token",
  "internal_tools_visibility",
  "destructive_confirm",
];

/**
 * 权限模式：全面放开 / 标准 / 严格。
 *
 * 「全面放开」= 大部分设置可改（含对话与 CLI 管理），但核心安全项始终锁定：
 * 审批阈值下限、密钥、访问口令、内置工具可见性、破坏性操作确认。锁定项在界面上
 * 明确标注「核心项」，点击会调用后端 core-guard 说明拒绝原因（不是隐藏了事）。
 */
export function PermissionsSection() {
  const { t } = useI18n();
  const { toast } = useToast();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const q = useQuery({
    queryKey: ["/api/studio/permissions"],
    queryFn: () =>
      api<{ permissions: Permissions; locked: string[] }>("/api/studio/permissions"),
  });
  const perms = q.data?.permissions;

  const save = async (patch: Partial<Permissions>) => {
    if (!perms) return;
    setBusy(true);
    try {
      const r = await api<{ ok: boolean; error?: string }>("/api/studio/permissions", {
        method: "PUT",
        body: JSON.stringify({ ...perms, ...patch }),
      });
      if (!r.ok) throw new Error(r.error || t("studio.saveFail"));
      await qc.invalidateQueries({ queryKey: ["/api/studio/permissions"] });
      await qc.invalidateQueries({ queryKey: ["/api/studio/overview"] });
      toast(t("studio.permSaved"), "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const explainLocked = async (key: string) => {
    try {
      const r = await api<{ allowed: boolean; error?: string }>("/api/studio/core-guard", {
        method: "POST",
        body: JSON.stringify({ key }),
      });
      toast(r.error || t("studio.coreLocked"), "error");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  return (
    <Section
      title={t("settings.navPermissions")}
      icon={<ShieldCheck className="w-4 h-4 text-muted-foreground" />}
      desc={t("studio.permDesc")}
    >
      <div className="space-y-3">
        <div className="grid gap-2 sm:grid-cols-3">
          {MODES.map((m) => {
            const Icon = m.icon;
            const on = perms?.mode === m.id;
            return (
              <button
                key={m.id}
                type="button"
                disabled={busy || !perms}
                aria-pressed={on}
                onClick={() => void save({ mode: m.id })}
                className={cn(
                  "rounded-lg border px-3 py-2.5 text-left transition-colors",
                  on ? "border-primary bg-primary/5" : "border-border hover:bg-accent",
                )}
              >
                <div className="flex items-center gap-1.5 text-[13px] font-medium">
                  <Icon className="h-3.5 w-3.5" /> {t(m.labelKey)}
                </div>
                <div className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                  {t(m.descKey)}
                </div>
              </button>
            );
          })}
        </div>

        <div className="space-y-1.5 border-t border-border/60 pt-2">
          {[
            { key: "allow_chat_admin" as const, labelKey: "studio.allowChat" },
            { key: "allow_cli_admin" as const, labelKey: "studio.allowCli" },
            { key: "allow_remote_install" as const, labelKey: "studio.allowRemote" },
          ].map((row) => (
            <div key={row.key} className="flex items-center justify-between gap-2">
              <span className="text-sm">{t(row.labelKey)}</span>
              <Switch
                checked={Boolean(perms?.[row.key])}
                disabled={busy || !perms || perms.mode !== "open"}
                onChange={(v) => void save({ [row.key]: v })}
                label={t(row.labelKey)}
              />
            </div>
          ))}
        </div>

        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
          <div className="flex items-center gap-1.5 text-xs font-medium text-amber-700 dark:text-amber-400">
            <Lock className="h-3.5 w-3.5" /> {t("studio.coreLockedTitle")}
          </div>
          <p className="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">
            {t("studio.coreLockedDesc")}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {LOCKED_KEYS.map((key) => (
              <Button
                key={key}
                size="sm"
                variant="outline"
                className="h-7 px-2 font-mono text-[10.5px]"
                onClick={() => void explainLocked(key)}
              >
                {key}
              </Button>
            ))}
          </div>
        </div>
      </div>
    </Section>
  );
}
