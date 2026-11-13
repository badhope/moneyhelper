import { ArrowLeft, ChevronDown, Languages, Menu, Moon, Settings, SquarePen, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { BrandLogo, BRAND } from "@/lib/brand";
import { useI18n } from "@/lib/i18n";
import { useTheme } from "@/lib/theme";
import type { BootstrapData } from "@/lib/types";
import { TenantSwitcher } from "@/components/TenantSwitcher";

/**
 * 主区顶栏（ChatGPT 式）：高度 48px、无分割线。
 * 左：移动端导航 / 品牌，桌面端当前模型（可切换）。
 * 右：新建对话 + 语言 / 明暗 / 设置，全部弱化成图标。
 */
export function TopBar({
  onOpenSettings,
  onOpenNav,
  onNewSession,
  onBackToChat,
  modelName,
  modelCatalog,
  enabledModels,
  onSwitchModel,
  onTenantChanged,
}: {
  onOpenSettings?: () => void;
  /** 移动端：打开左侧导航抽屉（会话列表/新建/部门/收件箱） */
  onOpenNav?: () => void;
  onNewSession?: () => void;
  /** 非对话页时显示返回问答的入口 */
  onBackToChat?: () => void;
  modelName?: string;
  modelCatalog?: BootstrapData["model_catalog"];
  enabledModels?: string[];
  onSwitchModel?: (base: string, model: string) => void;
  /** 切换工作租户后回调（切片 7b）：用于刷新企业域数据 */
  onTenantChanged?: () => void;
}) {
  const { resolved, setTheme } = useTheme();
  const { lang, setLang, t } = useI18n();

  return (
    <header className="flex h-12 shrink-0 items-center justify-between gap-2 px-2 pt-[env(safe-area-inset-top)] sm:px-3">
      <div className="flex min-w-0 items-center gap-1">
        {/* 移动端菜单：始终可用——财务页里也要能打开会话抽屉 */}
        <button
          type="button"
          aria-label={t("sidebar.sessions")}
          onClick={onOpenNav}
          className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-foreground/70 transition-colors hover:bg-accent hover:text-foreground md:hidden"
        >
          <Menu className="h-5 w-5" />
        </button>
        {onBackToChat && (
          <button
            type="button"
            aria-label={t("app.backToChat")}
            onClick={onBackToChat}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg px-2 text-sm text-foreground/75 transition-colors hover:bg-accent hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
            <span className="hidden sm:inline">{t("app.backToChat")}</span>
          </button>
        )}
        <span className="flex min-w-0 items-center gap-2 md:hidden">
          <BrandLogo size={22} />
          <span className="truncate text-sm font-semibold">{BRAND.name}</span>
        </span>

        {/* 全局租户切换（切片 7b）：只有一个租户时不渲染 */}
        <TenantSwitcher onChanged={onTenantChanged} />

        {modelName ? (
          <label className="relative hidden min-w-0 items-center gap-1 rounded-lg px-2 py-1.5 text-[15px] font-medium text-foreground/85 transition-colors hover:bg-accent md:inline-flex">
            <span className="max-w-[18rem] truncate">{modelName}</span>
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <select
              value={modelName}
              onChange={(e) => {
                const val = e.target.value;
                const hit = (modelCatalog ?? []).find((m) => m.model === val);
                onSwitchModel?.(hit ? hit.base : "", val);
              }}
              aria-label={t("chat.switchModel")}
              title={t("chat.switchModelHint")}
              className="absolute inset-0 cursor-pointer opacity-0"
            >
              <option value={modelName}>{modelName}</option>
              {(enabledModels ?? [])
                .filter((m) => m !== modelName)
                .map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
            </select>
          </label>
        ) : null}
      </div>

      <div className="flex items-center gap-0.5">
        {onNewSession && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9 text-foreground/60 hover:text-foreground"
                aria-label={t("chat.newSession")}
                onClick={onNewSession}
              >
                <SquarePen className="h-[18px] w-[18px]" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("chat.newSession")}</TooltipContent>
          </Tooltip>
        )}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9 text-foreground/60 hover:text-foreground"
              aria-label={lang === "zh" ? "Switch to English" : "切换到中文"}
              onClick={() => setLang(lang === "zh" ? "en" : "zh")}
            >
              <Languages className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{lang === "zh" ? t("topbar.toEn") : t("topbar.toZh")}</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9 text-foreground/60 hover:text-foreground"
              aria-label={t("topbar.toggleTheme")}
              onClick={() => setTheme(resolved === "dark" ? "light" : "dark")}
            >
              {resolved === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            {resolved === "dark" ? t("topbar.toggleLight") : t("topbar.toggleDark")}
          </TooltipContent>
        </Tooltip>
        {onOpenSettings && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9 text-foreground/60 hover:text-foreground"
                aria-label={t("topbar.settings")}
                onClick={onOpenSettings}
              >
                <Settings className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("topbar.settings")}</TooltipContent>
          </Tooltip>
        )}
      </div>
    </header>
  );
}
