import { useState, type ReactNode } from "react";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/lib/toast";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { errMsg } from "@/lib/utils";

/**
 * 设置区 AI 建议卡（统一交互）：生成 → 预览 → 采用/重生成。
 * 只产出建议、不落库；采用动作由调用方决定（填表单 / 写配置）。
 * 四个设置区（Agent / 预算 / 规则 / 晨报）共用本组件，保证按钮文案、位置、
 * 加载态与错误提示完全一致。
 */
export function AiSuggestCard<T>({
  title,
  hint,
  endpoint,
  payload = {},
  onAdopt,
  renderSuggestion,
}: {
  title: string;
  hint: string;
  /** 生成端点，如 "/api/budgets/suggest" */
  endpoint: string;
  payload?: Record<string, unknown>;
  /** 用户点「采用」时调用（通常是 set 表单字段 / setConfig） */
  onAdopt: (s: T) => void;
  /** 预览渲染：接收建议数据，返回展示内容 */
  renderSuggestion: (s: T) => ReactNode;
}) {
  const { t } = useI18n();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const [sugg, setSugg] = useState<T | null>(null);

  const generate = async () => {
    setBusy(true);
    setSugg(null);
    try {
      const d = await api<{ ok: boolean; suggestion?: T; error?: string }>(endpoint, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (d.ok && d.suggestion) {
        setSugg(d.suggestion);
      } else {
        toast(String(d.error || t("settings.aiFail")), "error");
      }
    } catch (e) {
      toast(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-dashed border-primary/30 bg-primary/5 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm">{title}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>
        </div>
        <Button variant="outline" size="sm" className="shrink-0" onClick={() => void generate()} disabled={busy}>
          <Sparkles className="w-3.5 h-3.5" />
          {busy ? t("settings.aiBusy") : sugg ? t("settings.aiAgain") : t("settings.aiGen")}
        </Button>
      </div>
      {sugg != null && (
        <div className="mt-2 rounded-md border border-border bg-card p-2.5">
          {renderSuggestion(sugg)}
          <div className="mt-2 flex gap-1.5">
            <Button size="sm" onClick={() => onAdopt(sugg)}>
              {t("settings.aiAdopt")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => void generate()}>
              {t("settings.aiAgain")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
