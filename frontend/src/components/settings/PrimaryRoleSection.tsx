import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, UserCog } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Section } from "./shared";

interface Role {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  builtin?: boolean;
  tools?: string[] | string;
  temperature?: number;
  instructions?: string;
}

/**
 * 主角色选择：决定内置系统提示里注入哪一份角色指令（其余角色仍作为分工说明存在）。
 * 切换立即生效（下一轮问答），不覆盖 Studio 的提示词与约束块。
 */
export function PrimaryRoleSection() {
  const { t } = useI18n();
  const { toast } = useToast();
  const qc = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const roles = useQuery({
    queryKey: ["/api/studio", "roles"],
    queryFn: () => api<{ assets: Role[] }>("/api/studio/roles").then((r) => r.assets ?? []),
  });
  const overview = useQuery({
    queryKey: ["/api/studio/overview"],
    queryFn: () => api<{ primary_role: string }>("/api/studio/overview"),
  });
  const primary = overview.data?.primary_role ?? "supervisor";
  const list = useMemo(
    () => (roles.data ?? []).filter((r) => r.enabled !== false),
    [roles.data],
  );

  const choose = async (id: string) => {
    setBusy(id);
    try {
      const r = await api<{ ok: boolean; error?: string }>("/api/studio/primary-role", {
        method: "POST",
        body: JSON.stringify({ role_id: id }),
      });
      if (!r.ok) throw new Error(r.error || t("studio.saveFail"));
      await qc.invalidateQueries({ queryKey: ["/api/studio/overview"] });
      toast(t("studio.primarySaved", { name: list.find((x) => x.id === id)?.name ?? id }), "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Section
      title={t("settings.navPrimaryRole")}
      icon={<UserCog className="w-4 h-4 text-muted-foreground" />}
      desc={t("studio.primaryDesc")}
    >
      <div className="grid gap-2 sm:grid-cols-2">
        {list.map((role) => {
          const on = role.id === primary;
          return (
            <button
              key={role.id}
              type="button"
              aria-pressed={on}
              disabled={busy !== null}
              onClick={() => void choose(role.id)}
              className={cn(
                "rounded-lg border px-3 py-2 text-left transition-colors",
                on ? "border-primary bg-primary/5" : "border-border hover:bg-accent",
              )}
            >
              <div className="flex items-center gap-1.5 text-[13px] font-medium">
                <Bot className="h-3.5 w-3.5" />
                {role.name}
                {role.builtin && (
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                    {t("studio.builtin")}
                  </span>
                )}
              </div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">{role.description}</div>
            </button>
          );
        })}
      </div>
      {list.length === 0 && (
        <p className="py-3 text-center text-xs text-muted-foreground">{t("studio.empty")}</p>
      )}
      <Button
        size="sm"
        variant="ghost"
        className="mt-2"
        onClick={() => void qc.invalidateQueries({ queryKey: ["/api/studio", "roles"] })}
      >
        {t("studio.refresh")}
      </Button>
    </Section>
  );
}
