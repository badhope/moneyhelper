import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Award, BookOpen, Bot, Brain, BrainCog, FileText, GitCompareArrows, KeyRound, Lock, Package, Plug, Shield, Users, Newspaper, PiggyBank, ScrollText, ShieldCheck, SlidersHorizontal, Sparkles, UserCog, Wallet, Wand2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useDashboard } from "@/lib/store";
import { useI18n } from "@/lib/i18n";
import { useIsDesktop } from "@/lib/use-media-query";
import { useSettingsForm, type SectionId } from "@/components/settings/use-settings-form";
import { PrefsSection } from "@/components/settings/PrefsSection";
import { RulesSection } from "@/components/settings/RulesSection";
import { BudgetSection } from "@/components/settings/BudgetSection";
import { AiSection } from "@/components/settings/AiSection";
import { ReportSection } from "@/components/settings/ReportSection";
import { MemorySection } from "@/components/settings/MemorySection";
import { DataSection } from "@/components/settings/DataSection";
import { TokenSection } from "@/components/settings/TokenSection";
import { LogsSection } from "@/components/settings/LogsSection";
import { AuditSection } from "@/components/settings/AuditSection";
import { ProvenanceSection } from "@/components/settings/ProvenanceSection";
import { FamilySection } from "@/components/settings/FamilySection";
import { Button } from "@/components/ui/button";
import { AgentSection } from "@/components/settings/AgentSection";
import { PluginsSection } from "@/components/settings/PluginsSection";
import { PromptSection } from "@/components/settings/PromptSection";
import { KnowledgeSection } from "@/components/settings/KnowledgeSection";
import { EvalSection } from "@/components/settings/EvalSection";
import { AssetManager } from "@/components/settings/AssetManager";
import { PermissionsSection } from "@/components/settings/PermissionsSection";
import { MarketplaceSection } from "@/components/settings/MarketplaceSection";
import { InternalToolsSection } from "@/components/settings/InternalToolsSection";
import { PrimaryRoleSection } from "@/components/settings/PrimaryRoleSection";

const SECTIONS: { id: SectionId; labelKey: string; icon: typeof Wallet }[] = [
  { id: "prefs", labelKey: "settings.navPrefs", icon: SlidersHorizontal },
  { id: "rules", labelKey: "settings.navRules", icon: Wallet },
  { id: "budget", labelKey: "settings.navBudget", icon: PiggyBank },
  { id: "ai", labelKey: "settings.navAi", icon: Brain },
  { id: "roles", labelKey: "settings.navRoles", icon: UserCog },
  { id: "skills", labelKey: "settings.navSkills", icon: Sparkles },
  { id: "agent", labelKey: "settings.navAgent", icon: Bot },
  { id: "plugins", labelKey: "settings.navPlugins", icon: Plug },
  { id: "market", labelKey: "settings.navMarket", icon: Package },
  { id: "prompt", labelKey: "settings.navPrompt", icon: FileText },
  { id: "constraints", labelKey: "settings.navConstraints", icon: Shield },
  { id: "hooks", labelKey: "settings.navHooks", icon: Wand2 },
  { id: "permissions", labelKey: "settings.navPermissions", icon: Lock },
  { id: "internalTools", labelKey: "settings.navInternalTools", icon: BrainCog },
  { id: "knowledge", labelKey: "settings.navKnowledge", icon: BookOpen },
  { id: "report", labelKey: "settings.navReport", icon: Newspaper },
  { id: "memory", labelKey: "settings.navMemory", icon: BrainCog },
  { id: "data", labelKey: "settings.navData", icon: ShieldCheck },
  { id: "token", labelKey: "settings.navToken", icon: KeyRound },
  { id: "logs", labelKey: "settings.navLogs", icon: ScrollText },
  { id: "audit", labelKey: "settings.navAudit", icon: ShieldCheck },
  { id: "provenance", labelKey: "settings.navProvenance", icon: GitCompareArrows },
  { id: "family", labelKey: "settings.navFamily", icon: Users },
  { id: "eval", labelKey: "settings.navEval", icon: Award },
];

const SECTION_GROUPS: { key: string; ids: SectionId[] }[] = [
  { key: "settings.groupGeneral", ids: ["prefs", "rules", "budget", "family"] },
  {
    key: "settings.groupAi",
    ids: ["ai", "roles", "skills", "agent", "plugins", "market", "prompt", "constraints", "hooks", "permissions", "internalTools", "knowledge", "report", "memory"],
  },
  { key: "settings.groupData", ids: ["data", "token", "logs", "audit", "provenance"] },
  { key: "settings.groupEval", ids: ["eval"] },
];

export function SettingsView({ onDirtyChange }: { onDirtyChange?: (dirty: boolean) => void } = {}) {
  const { t } = useI18n();
  const { dashboard } = useDashboard();
  const isDesktop = useIsDesktop();
  const { bootstrap, form, saveMutate, toggleMutate, reset, set, toggle, resetForm, dirty } = useSettingsForm();

  // 把「有未保存修改」上报给 App：关闭设置页时若为 true 要先确认，避免改动静默丢失。
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);

  // active tab 状态很小，直接放组件内即可
  const [active, setActive] = useState<SectionId>("prefs");
  if (!bootstrap) {
    return <div className="p-8 text-center text-sm text-muted-foreground">{t("settings.loading")}</div>;
  }

  const sectionButton = (s: (typeof SECTIONS)[number]) => {
    const Icon = s.icon;
    const on = active === s.id;
    return (
      <button
        key={s.id}
        type="button"
        aria-current={on ? "page" : undefined}
        onClick={() => setActive(s.id)}
        className={cn(
          "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          on
            ? "bg-foreground/[0.07] font-medium text-foreground"
            : "text-foreground/75 hover:bg-foreground/[0.05] hover:text-foreground",
        )}
      >
        <Icon className="h-4 w-4 shrink-0" />
        <span className="truncate">{t(s.labelKey)}</span>
      </button>
    );
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col md:flex-row">
      {/* 手机：横向分段条（滚动），当前段高亮。一次只显示一段内容，
          不再把 13 个入口折叠成三层——那需要两次点击才能到达目标页。 */}
      {!isDesktop && (
        <div className="shrink-0 overflow-x-auto border-b border-border/70 scroll-thin">
          <div className="flex min-w-max gap-1 px-3 py-2">
            {SECTIONS.map((s) => {
              const Icon = s.icon;
              const on = active === s.id;
              return (
                <button
                  key={s.id}
                  type="button"
                  aria-current={on ? "page" : undefined}
                  onClick={() => setActive(s.id)}
                  className={cn(
                    "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-[12.5px] transition-colors",
                    on
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground hover:text-foreground",
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {t(s.labelKey)}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* 桌面：左侧分组导航（固定，不随内容滚动） */}
      {isDesktop && (
        <nav
          aria-label={t("nav.main")}
          className="w-56 shrink-0 overflow-y-auto scroll-thin border-r border-border/70 px-2 py-3"
        >
          {SECTION_GROUPS.map((g) => {
            const ids = new Set<SectionId>(g.ids);
            const items = SECTIONS.filter((s) => ids.has(s.id));
            return (
              <div key={g.key} className="mb-2">
                <div className="px-3 pb-1 pt-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  {t(g.key)}
                </div>
                <div className="space-y-0.5">{items.map(sectionButton)}</div>
              </div>
            );
          })}
        </nav>
      )}

      <motion.div
        key={active}
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.15, ease: "easeOut" }}
        className="min-h-0 min-w-0 flex-1 overflow-y-auto scroll-thin px-4 py-4 sm:px-6 space-y-3"
      >
        {active === "prefs" && (
          <PrefsSection
            form={form}
            setColorScheme={(v) => {
              set("color_scheme", v);
              toggleMutate.mutate({ k: "color_scheme", v });
            }}
            setDefaultTab={(v) => {
              set("default_tab", v);
              toggleMutate.mutate({ k: "default_tab", v });
            }}
            onToggle={toggle}
          />
        )}

        {active === "rules" && <RulesSection form={form} onField={set} />}

        {active === "budget" && <BudgetSection />}

        {active === "ai" && (
          <AiSection
            form={form}
            onField={set}
            onToggle={toggle}
            health={bootstrap.health}
            modelCatalog={bootstrap.model_catalog}
            enabledModels={bootstrap.enabled_models}
            onSaved={() => set("monthly_income", bootstrap.settings.monthly_income)}
          />
        )}

        {active === "report" && (
          <ReportSection form={form} onField={set} scheduler={bootstrap.scheduler} />
        )}

        {active === "roles" && (
          <div className="space-y-3">
            <PrimaryRoleSection />
            <AssetManager
              kind="roles"
              titleKey="settings.navRoles"
              descKey="studio.rolesDesc"
              hintKey="studio.rolesHint"
            />
          </div>
        )}

        {active === "skills" && (
          <AssetManager
            kind="skills"
            titleKey="settings.navSkills"
            descKey="studio.skillsDesc"
            hintKey="studio.skillsHint"
          />
        )}

        {active === "agent" && <AgentSection />}

        {active === "plugins" && <PluginsSection />}

        {active === "market" && <MarketplaceSection />}

        {active === "prompt" && (
          <div className="space-y-3">
            <PromptSection />
            <AssetManager kind="prompts" titleKey="settings.navPrompt" descKey="studio.promptsDesc" />
          </div>
        )}

        {active === "constraints" && (
          <AssetManager
            kind="rules"
            titleKey="settings.navConstraints"
            descKey="studio.rulesDesc"
            hintKey="studio.rulesHint"
          />
        )}

        {active === "hooks" && (
          <AssetManager
            kind="hooks"
            titleKey="settings.navHooks"
            descKey="studio.hooksDesc"
            hintKey="studio.hooksHint"
          />
        )}

        {active === "permissions" && <PermissionsSection />}

        {active === "internalTools" && <InternalToolsSection />}

        {active === "knowledge" && <KnowledgeSection />}

        {active === "memory" && <MemorySection />}

        {active === "data" && (
          <DataSection dashboard={dashboard} bootstrap={bootstrap} onRestoreDemo={() => void reset.mutate(undefined)} />
        )}

        {active === "token" && <TokenSection />}

        {active === "logs" && <LogsSection />}

        {active === "audit" && <AuditSection />}

        {active === "provenance" && <ProvenanceSection />}

        {active === "family" && <FamilySection />}

        {active === "eval" && <EvalSection />}

        {dirty && (
          <div className="sticky bottom-0 z-10 -mx-1 flex items-center justify-between gap-3 border-t border-border bg-background/95 px-3 py-2 backdrop-blur">
            <span className="text-xs text-muted-foreground">{t("settings.unsavedHint")}</span>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => resetForm()}
                disabled={saveMutate.isPending}
              >
                {t("settings.discard")}
              </Button>
              <Button size="sm" onClick={() => void saveMutate.mutate(undefined)} disabled={saveMutate.isPending}>
                {saveMutate.isPending ? t("settings.saving") : t("settings.saveSettings")}
              </Button>
            </div>
          </div>
        )}
      </motion.div>
    </div>
  );
}
