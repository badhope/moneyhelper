import { useState } from "react";
import { FileText, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useBootstrap, store } from "@/lib/store";
import { api } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { Section, inputCls } from "./shared";

/**
 * 系统提示词：覆盖 agents/supervisor/instructions.md 的内置默认值。
 *
 * 之前提示词写死在 backend/app/agents/<agent>/instructions.md，改一句要动代码 + 重新打包。
 * 这里填的内容会替换财务分支的系统提示（留空 = 用文件默认），长度上限 4000 字。
 */
export function PromptSection() {
  const { t } = useI18n();
  const { toast } = useToast();
  const { bootstrap } = useBootstrap();
  const saved = bootstrap?.settings.custom_system_prompt ?? "";
  const [value, setValue] = useState(saved);
  const [saving, setSaving] = useState(false);

  const dirty = value !== saved;

  const save = async () => {
    setSaving(true);
    try {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({ settings: { custom_system_prompt: value } }),
      });
      await store.refreshBootstrap();
      toast(t("prompt.saved"), "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section
      title={t("prompt.baseTitle")}
      icon={<FileText className="w-4 h-4 text-muted-foreground" />}
      desc={t("prompt.desc")}
    >
      <div className="space-y-2">
        <textarea
          className={`${inputCls} min-h-56 font-mono text-[12.5px] leading-relaxed`}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={t("prompt.ph")}
          maxLength={4000}
          spellCheck={false}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => void save()} disabled={!dirty || saving}>
            {saving ? t("prompt.saving") : t("settings.save")}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setValue("")}
            disabled={!value}
          >
            <RotateCcw className="h-3.5 w-3.5" /> {t("prompt.reset")}
          </Button>
          <span className="text-[11px] text-muted-foreground">
            {t("prompt.counter", { n: value.length })}
          </span>
          {dirty && <span className="text-[11px] text-amber-600">{t("settings.unsavedShort")}</span>}
        </div>
        <p className="rounded-lg bg-muted/50 px-3 py-2 text-[11.5px] leading-relaxed text-muted-foreground">
          {t("prompt.note")}
        </p>
      </div>
    </Section>
  );
}
