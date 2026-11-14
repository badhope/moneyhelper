import { useState } from "react";
import { KeyRound, ShieldCheck, ShieldAlert, ShieldOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getToken, setToken } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { useBootstrap } from "@/lib/store";
import { cn } from "@/lib/utils";
import { Section, inputCls, labelCls } from "./shared";

/**
 * 访问口令：本地保存 token + 明确显示服务端当前鉴权模式。
 *
 * 之前只有一个输入框和一句"后端 API_TOKEN 相同时才生效"，用户填完无法判断
 * 到底生没生效。现在按 /api/health 的 auth_mode 显示三种状态：
 *   token    → 服务端要求口令，下面可校验是否匹配
 *   accounts → 已启用账号体系，口令不适用（用登录）
 *   local    → 本机免登录，口令只在对外暴露时才需要
 */
export function TokenSection() {
  const { t } = useI18n();
  const { toast } = useToast();
  const { bootstrap } = useBootstrap();
  const [tokenInput, setTokenInput] = useState(getToken());

  const rawMode = bootstrap?.health?.auth_mode;
  const mode: "token" | "accounts" | "local" =
    rawMode === "token" || rawMode === "accounts" ? rawMode : "local";
  const configured = Boolean(getToken());

  const modeView = {
    token: {
      icon: ShieldCheck,
      tone: "text-emerald-700 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
      title: t("settings.tokenModeToken"),
      hint: t("settings.tokenModeTokenHint"),
    },
    accounts: {
      icon: ShieldAlert,
      tone: "text-amber-700 dark:text-amber-400 bg-amber-500/10 border-amber-500/30",
      title: t("settings.tokenModeAccounts"),
      hint: t("settings.tokenModeAccountsHint"),
    },
    local: {
      icon: ShieldOff,
      tone: "text-muted-foreground bg-muted border-border",
      title: t("settings.tokenModeLocal"),
      hint: t("settings.tokenModeLocalHint"),
    },
  }[mode];

  const ModeIcon = modeView.icon;

  return (
    <Section title={t("settings.navToken")} icon={<KeyRound className="w-4 h-4 text-muted-foreground" />}>
      <div className={cn("mb-3 flex items-start gap-2 rounded-lg border px-3 py-2", modeView.tone)}>
        <ModeIcon className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="min-w-0">
          <div className="text-[13px] font-medium">{modeView.title}</div>
          <div className="mt-0.5 text-[11.5px] leading-relaxed opacity-85">{modeView.hint}</div>
        </div>
      </div>

      <div className="flex items-end gap-2">
        <div className="min-w-0 flex-1">
          <label className={labelCls} htmlFor="tokensecti-1">{t("settings.tokenInput")}</label>
          <input id="tokensecti-1"
            className={inputCls}
            type="password"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder={t("settings.tokenPh")}
            autoComplete="off"
          />
        </div>
        <Button
          size="sm"
          onClick={() => {
            setToken(tokenInput.trim());
            toast(t("settings.tokenUpdated"), "ok");
          }}
        >
          {t("settings.save")}
        </Button>
        {configured && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setToken("");
              setTokenInput("");
              toast(t("settings.tokenCleared"), "ok");
            }}
          >
            {t("settings.tokenClear")}
          </Button>
        )}
      </div>
      <div className="mt-2 text-xs text-muted-foreground">{t("settings.tokenHintShort")}</div>
    </Section>
  );
}
