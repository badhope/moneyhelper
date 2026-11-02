import { SlidersHorizontal } from "lucide-react";
import { Segmented } from "@/components/ui/segmented";
import { Switch } from "@/components/ui/switch";
import { BRAND_DEFAULT_ACCENT, BRAND_PRESETS } from "@/lib/brand";
import { DEFAULT_PRESET, useTheme } from "@/lib/theme";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Section } from "./shared";

/** 偏好设置（主题 / 主题色 / 语音 / 语言 / 涨跌配色 / 默认首页）；开关类即改即存，配色与首页走底部批量保存 */
export function PrefsSection({
  form,
  setColorScheme,
  setDefaultTab,
  onToggle,
}: {
  form: Record<string, string>;
  setColorScheme: (v: string) => void;
  setDefaultTab: (v: string) => void;
  onToggle: (k: string, value?: string) => void;
}) {
  const { t, lang, setLang } = useI18n();
  const { theme: themeMode, setTheme, preset, setPreset } = useTheme();

  return (
    <Section title={t("settings.navPrefs")} icon={<SlidersHorizontal className="w-4 h-4 text-muted-foreground" />} desc={t("settings.prefsDesc")}>
      <div className="flex items-center justify-between">
        <span className="text-sm">{t("settings.theme")}</span>
        <Segmented
          value={themeMode}
          onChange={setTheme}
          options={[
            { value: "light", label: t("settings.light") },
            { value: "dark", label: t("settings.dark") },
            { value: "system", label: t("settings.system") },
          ]}
        />
      </div>
      {/* 品牌主题色：本机持久化（localStorage），不改服务端设置 */}
      <div className="mt-3">
        <div className="text-sm">{t("settings.brandColor")}</div>
        <div className="text-xs text-muted-foreground mt-0.5">{t("settings.brandColorHint")}</div>
        <div className="mt-2 flex flex-wrap items-center gap-2" role="radiogroup" aria-label={t("settings.brandColor")}>
          {[
            { id: DEFAULT_PRESET, color: BRAND_DEFAULT_ACCENT },
            ...BRAND_PRESETS.map((p) => ({ id: p.id, color: p.accent })),
          ].map((p) => (
            <button
              key={p.id}
              type="button"
              role="radio"
              aria-checked={preset === p.id}
              aria-label={t(`settings.preset.${p.id}`)}
              title={t(`settings.preset.${p.id}`)}
              onClick={() => setPreset(p.id)}
              className={cn(
                "h-7 w-7 rounded-full border-2 transition-transform",
                preset === p.id ? "border-foreground scale-110" : "border-transparent hover:scale-105",
              )}
              style={{ backgroundColor: p.color }}
            />
          ))}
        </div>
      </div>
      {/* 适老化：字号档位 + 高对比度。两项都即时生效（写根元素 data-*） */}
      <div className="mt-3 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm">{t("settings.textScale")}</div>
          <div className="text-xs text-muted-foreground mt-0.5">{t("settings.textScaleHint")}</div>
        </div>
        <Segmented
          value={form.text_scale ?? "normal"}
          onChange={(v) => onToggle("text_scale", v)}
          options={[
            { value: "normal", label: t("settings.textScaleNormal") },
            { value: "large", label: t("settings.textScaleLarge") },
            { value: "xlarge", label: t("settings.textScaleXLarge") },
          ]}
        />
      </div>
      <div className="mt-3 flex items-center justify-between">
        <div>
          <div className="text-sm">{t("settings.highContrast")}</div>
          <div className="text-xs text-muted-foreground mt-0.5">{t("settings.highContrastHint")}</div>
        </div>
        <Switch
          checked={form.high_contrast === "on"}
          onChange={() => onToggle("high_contrast")}
          label={t("settings.highContrast")}
        />
      </div>
      <div className="mt-3 flex items-center justify-between">
        <div>
          <div className="text-sm">{t("settings.voice")}</div>
          <div className="text-xs text-muted-foreground mt-0.5">{t("settings.voiceHint")}</div>
        </div>
        <Switch checked={form.voice_input === "on"} onChange={() => onToggle("voice_input")} label={t("settings.voice")} />
      </div>
      <div className="mt-3 flex items-center justify-between">
        <div>
          <div className="text-sm">{t("settings.voiceOutput")}</div>
          <div className="text-xs text-muted-foreground mt-0.5">{t("settings.voiceOutputHint")}</div>
        </div>
        <Switch checked={form.voice_output === "on"} onChange={() => onToggle("voice_output")} label={t("settings.voiceOutput")} />
      </div>
      <div className="mt-3 flex items-center justify-between">
        <div>
          <div className="text-sm">{t("settings.language")}</div>
          <div className="text-xs text-muted-foreground mt-0.5">{t("settings.languageHint")}</div>
        </div>
        <div className="flex gap-1.5">
          {(["en", "zh"] as const).map((l) => (
            <button
              key={l}
              type="button"
              onClick={() => setLang(l)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium border transition-colors",
                lang === l ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {l === "en" ? "English" : "中文"}
            </button>
          ))}
        </div>
      </div>
      {/* 涨跌颜色：A股红涨绿跌 / 海外绿涨红跌 */}
      <div className="mt-3 flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm">{t("settings.colorScheme")}</div>
          <div className="text-xs text-muted-foreground mt-0.5">{t("settings.colorSchemeHint")}</div>
        </div>
        <Segmented
          value={form.color_scheme ?? "cn"}
          onChange={setColorScheme}
          options={[
            { value: "cn", label: t("settings.cnScheme") },
            { value: "us", label: t("settings.usScheme") },
          ]}
        />
      </div>
      {/* 默认首页 */}
      <div className="mt-3 flex items-center justify-between">
        <div>
          <div className="text-sm">{t("settings.defaultTab")}</div>
          <div className="text-xs text-muted-foreground mt-0.5">{t("settings.defaultTabHint")}</div>
        </div>
        <Segmented
          value={form.default_tab ?? "chat"}
          onChange={setDefaultTab}
          options={[
            { value: "chat", label: t("nav.chat") },
            { value: "features", label: t("nav.features") },
          ]}
        />
      </div>
      {/* 版本号：来自后端单一真源（构建时注入），方便用户报问题时带上版本 */}
      <div className="mt-3 border-t border-border pt-2 text-[11px] text-muted-foreground">
        {t("settings.version")} {__APP_VERSION__}
      </div>
    </Section>
  );
}
