import { useEffect, useState } from "react";
import { Brain } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { store } from "@/lib/store";
import { useMutate } from "@/lib/use-mutate";
import { useI18n } from "@/lib/i18n";
import type { BootstrapData } from "@/lib/types";
import { Segmented } from "@/components/ui/segmented";
import { Switch } from "@/components/ui/switch";
import { AlertBanner } from "@/components/ui/alert";
import { Section, Row, inputCls, labelCls, PRESET_PROVIDERS, type ProviderKey } from "./shared";
import { LocalModelSection } from "./LocalModelSection";

/** AI 配置（启用开关 / 供应商预设 / base URL / key / 模型 / 模型点亮），走独立保存 */
export function AiSection({
  form,
  onField,
  onToggle,
  health,
  modelCatalog,
  enabledModels,
  onSaved,
}: {
  form: Record<string, string>;
  onField: (k: string, v: string) => void;
  onToggle: (k: string) => void;
  health: BootstrapData["health"];
  modelCatalog?: BootstrapData["model_catalog"];
  enabledModels?: string[];
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const [providerSel, setProviderSel] = useState<ProviderKey>("custom");
  // 现场拉取：base+key 打 /models，返回什么就让人从下拉里挑，不再靠手打模型名
  const [remoteModels, setRemoteModels] = useState<{ id: string; owned_by: string }[]>([]);
  const [probing, setProbing] = useState(false);
  const [probeErr, setProbeErr] = useState("");
  const catalog = modelCatalog ?? [];
  // 本地勾选状态：点亮/禁用候选模型（不立即保存，点「保存 AI 配置」时统一写入）
  const [enabledSet, setEnabledSet] = useState<Set<string>>(
    () => new Set(enabledModels ?? []),
  );
  useEffect(() => {
    setEnabledSet(new Set(enabledModels ?? []));
  }, [enabledModels]);

  const ai = useMutate<undefined, void>({
    fn: async () => {
      const res = await api<{ ok: boolean; errors: string[] }>("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          settings: {
            ai_base_url: (form.ai_base_url ?? "").trim(),
            ai_api_key: (form.ai_api_key ?? "").trim(),
            ai_model: (form.ai_model ?? "").trim(),
            enabled_models: Array.from(enabledSet).join(","),
            agent_tool_turns: String(Math.max(1, Math.min(30, Number(form.agent_tool_turns) || 5))),
          },
        }),
      });
      if (res.errors.length) throw new Error(`${t("settings.saveFail")}: ${res.errors.join("; ")}`);
      await store.refreshBootstrap();
      store.bump();
      return undefined;
    },
    key: "settings.aiSaved",
    onSettled: (_res, e) => {
      if (!e) onSaved();
    },
  });

  return (
    <Section
      title={t("settings.navAi")}
      icon={<Brain className="w-4 h-4 text-muted-foreground" />}
      desc={t("settings.aiDesc")}
    >
      <div className="space-y-3">
        <Row label={t("settings.aiEnable")} hint={t("settings.aiEnableHint")}>
          <Switch
            checked={form.ai_enabled === "on"}
            onChange={() => {
              // 不走 onToggle：那个走 refreshBootstrap 会把刚粘进来的 API Key 冲掉
              // （实测 bug：填完 key 再点启用，key 输入框直接空掉，保存时静默丢 key）
              const v = form.ai_enabled === "on" ? "off" : "on";
              onField("ai_enabled", v);
              void api("/api/settings", {
                method: "PUT",
                body: JSON.stringify({ settings: { ai_enabled: v } }),
              });
            }}
            label={t("settings.aiEnable")}
          />
        </Row>
        <Row label={t("settings.aiProvider")} hint={t("settings.aiProviderHint")}>
          <Segmented
            value={providerSel}
            onChange={(v) => {
              setProviderSel(v);
              if (v !== "custom") {
                const p = PRESET_PROVIDERS[v];
                onField("ai_base_url", p.base);
                onField("ai_model", p.model);
              }
            }}
            options={[
              { value: "qs", label: "内置模型" },
              { value: "deepseek", label: "DeepSeek" },
              { value: "doubao", label: "豆包" },
              { value: "qwen", label: "通义" },
              { value: "custom", label: t("settings.aiCustom") },
            ]}
          />
        </Row>
        <AlertBanner tone="warn" className="text-xs">{t("settings.aiPrivacy")}</AlertBanner>
        <div>
          <label className={labelCls} htmlFor="aisection-1">{t("settings.aiBaseUrl")} <span className="text-xs opacity-70">（{t("settings.aiBaseOptional")}）</span></label>
          <input id="aisection-1"
            className={inputCls}
            value={form.ai_base_url ?? ""}
            onChange={(e) => onField("ai_base_url", e.target.value)}
            placeholder={t("settings.aiBasePh")}
            spellCheck={false}
          />
        </div>
        <div>
          <label className={labelCls} htmlFor="aisection-2">{t("settings.aiKey")} <span className="text-xs opacity-70">（{t("settings.aiKeyHint")}）</span></label>
          <input id="aisection-2"
            className={inputCls}
            type="password"
            value={form.ai_api_key === "********" ? "" : (form.ai_api_key ?? "")}
            onChange={(e) => onField("ai_api_key", e.target.value)}
            placeholder={form.ai_api_key === "********" ? t("settings.aiKeyMasked") : t("settings.aiKeyPh")}
            autoComplete="off"
            spellCheck={false}
          />
        </div>
        <div>
          <label className={labelCls} htmlFor="aisection-3">{t("settings.aiModel")} <span className="text-xs opacity-70">（{t("settings.aiModelOptional")}）</span></label>
          <input id="aisection-3"
            className={inputCls}
            value={form.ai_model ?? ""}
            onChange={(e) => onField("ai_model", e.target.value)}
            placeholder={t("settings.aiModelPh")}
            spellCheck={false}
          />
        </div>
        <div className="rounded-lg border border-input/70 p-2.5 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-muted-foreground">连上端点后拉一次可用模型，直接从下拉里挑</span>
            <Button
              variant="outline"
              size="sm"
              type="button"
              disabled={probing}
              onClick={async () => {
                setProbing(true);
                setProbeErr("");
                try {
                  const r = await api<{ ok: boolean; count?: number; models?: { id: string; owned_by: string }[]; error?: string }>(
                    "/api/models/probe",
                    {
                      method: "POST",
                      body: JSON.stringify({
                        base_url: (form.ai_base_url ?? "").trim(),
                        api_key: form.ai_api_key === "********" ? "" : (form.ai_api_key ?? "").trim(),
                      }),
                    },
                  );
                  if (!r.ok) {
                    setRemoteModels([]);
                    setProbeErr(r.error || "拉取失败");
                  } else {
                    setRemoteModels(r.models ?? []);
                    const list = r.models ?? [];
                    // 便宜的优先：GLM Flash 单价最低，其次任何 flash，最后才取第一个
                    const cheap =
                      list.find((m) => /glm.*flash/i.test(m.id)) ??
                      list.find((m) => /flash/i.test(m.id)) ??
                      list[0];
                    if (cheap) onField("ai_model", cheap.id);
                  }
                } catch (e) {
                  setProbeErr(e instanceof Error ? e.message : String(e));
                } finally {
                  setProbing(false);
                }
              }}
            >
              {probing ? "拉取中…" : "拉取可用模型"}
            </Button>
          </div>
          {remoteModels.length > 0 && (
            <select
              className={inputCls}
              value={form.ai_model ?? ""}
              onChange={(e) => onField("ai_model", e.target.value)}
              aria-label="选择模型"
            >
              {remoteModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.id}{m.owned_by ? `（${m.owned_by}）` : ""}
                </option>
              ))}
            </select>
          )}
          {remoteModels.length > 0 && (
            <div className="text-xs text-muted-foreground">拉到 {remoteModels.length} 个模型，已默认选中最省的一档（flash）</div>
          )}
          {probeErr && <div className="text-xs text-destructive">{probeErr}</div>}
        </div>
        {catalog.length > 0 && (
          <div className="pt-2 border-t border-border/60">
            <div className="mb-1 text-xs font-medium text-foreground/90">{t("settings.enabledModels")}</div>
            <p className="mb-2 text-xs text-muted-foreground/70">{t("settings.enabledModelsHint")}</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
              {catalog.map((m) => {
                const on = enabledSet.has(m.model);
                return (
                  <label
                    key={m.model}
                    className={`flex items-center justify-between gap-2 rounded-lg border px-2.5 py-1.5 text-xs cursor-pointer transition-colors ${
                      on ? "border-primary/40 bg-primary/5" : "border-input/70 bg-transparent opacity-70"
                    }`}
                  >
                    <span className="flex flex-col min-w-0">
                      <span className="font-medium text-foreground/90">{m.name}</span>
                      <span className="text-xs text-muted-foreground/70 truncate">{m.provider}</span>
                    </span>
                    <Switch
                      checked={on}
                      onChange={() => {
                        setEnabledSet((prev) => {
                          const next = new Set(prev);
                          if (on) next.delete(m.model);
                          else next.add(m.model);
                          return next;
                        });
                      }}
                      label={m.name}
                    />
                  </label>
                );
              })}
            </div>
          </div>
        )}
        <LocalModelSection
          baseUrl={form.ai_base_url ?? ""}
          apiKey={form.ai_api_key ?? ""}
          model={form.ai_model ?? ""}
          onPick={(patch) => {
            if (patch.ai_base_url !== undefined) onField("ai_base_url", patch.ai_base_url);
            if (patch.ai_model !== undefined) onField("ai_model", patch.ai_model);
            if (patch.ai_api_key !== undefined) onField("ai_api_key", patch.ai_api_key);
          }}
        />
        <div className="pt-2 border-t border-border/60">
          <div className="mb-2 text-xs font-medium text-foreground/90">{t("settings.agentBehavior")}</div>
          <p className="mb-2 text-xs text-muted-foreground/70">{t("settings.agentBehaviorHint")}</p>
          <div className="space-y-2">
            <Row label={t("settings.agentPlan")} hint={t("settings.agentPlanHint")}>
              <Switch checked={form.agent_plan !== "off"} onChange={() => onToggle("agent_plan")} label={t("settings.agentPlan")} />
            </Row>
            <Row label={t("settings.agentReflect")} hint={t("settings.agentReflectHint")}>
              <Switch checked={form.agent_reflect !== "off"} onChange={() => onToggle("agent_reflect")} label={t("settings.agentReflect")} />
            </Row>
            <Row label={t("settings.agentTurns")} hint={t("settings.agentTurnsHint")}>
              <input
                className={inputCls + " w-24 text-center"}
                type="number"
                min={1}
                max={30}
                value={form.agent_tool_turns ?? "5"}
                onChange={(e) => onField("agent_tool_turns", e.target.value)}
                aria-label={t("settings.agentTurns")}
              />
            </Row>
          </div>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            {t("settings.current")}: {health.llm_configured ? `${t("settings.aiOn")}（${health.model}）` : t("settings.aiOff")}
          </span>
          <Button variant="outline" size="sm" onClick={() => ai.mutate(undefined)} disabled={ai.isPending}>
            {t("settings.saveAi")}
          </Button>
        </div>
      </div>
    </Section>
  );
}
