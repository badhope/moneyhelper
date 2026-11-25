import { useEffect, useState } from "react";
import { Download, Loader2, RefreshCw } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { Button } from "@/components/ui/button";

type UpdateInfo = {
  available: boolean;
  current: string;
  version: string | null;
  notes: string | null;
  date: string | null;
};

type Phase = "idle" | "checking" | "latest" | "available" | "installing" | "error";

function tauriInvoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const internals = (window as unknown as {
    __TAURI_INTERNALS__?: { invoke?: (c: string, a?: Record<string, unknown>) => Promise<T> };
  }).__TAURI_INTERNALS__;
  if (!internals?.invoke) throw new Error("not-tauri");
  return internals.invoke(cmd, args);
}

/** 桌面版检查/安装更新。浏览器里只展示提示，不假装能升级。 */
export function UpdateCard() {
  const { t } = useI18n();
  const desktop = Boolean(
    (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__,
  );
  const [phase, setPhase] = useState<Phase>("idle");
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [error, setError] = useState("");

  const check = async () => {
    setPhase("checking");
    setError("");
    try {
      const next = await tauriInvoke<UpdateInfo>("check_update");
      setInfo(next);
      setPhase(next.available ? "available" : "latest");
    } catch (e) {
      setError(String(e));
      setPhase("error");
    }
  };

  // 打开设置就静默探测一次：用户不必先点按钮才知道有新版本。
  useEffect(() => {
    if (desktop) void check();
    // check 只依赖 desktop；这里只跑一次，避免重渲染反复请求。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [desktop]);

  const install = async () => {
    setPhase("installing");
    setError("");
    try {
      await tauriInvoke<void>("install_update");
    } catch (e) {
      setError(String(e));
      setPhase("error");
    }
  };

  return (
    <div className="mt-3 rounded-lg border border-border/70 px-3 py-2.5">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-sm">
            <RefreshCw className="h-3.5 w-3.5 text-muted-foreground" />
            <span>{t("settings.updateTitle")}</span>
            <span className="text-muted-foreground">v{__APP_VERSION__}</span>
          </div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {!desktop
              ? t("settings.updateDesktopOnly")
              : phase === "available" && info?.version
                ? `${t("settings.updateAvailable")} ${info.version}`
                : phase === "latest"
                  ? t("settings.updateLatest")
                  : phase === "installing"
                    ? t("settings.updateInstalling")
                    : phase === "error"
                      ? `${t("settings.updateError")}${error ? `: ${error}` : ""}`
                      : t("settings.updateHint")}
          </div>
        </div>
        {desktop && phase !== "available" && phase !== "installing" && (
          <Button
            size="sm"
            variant="outline"
            className="shrink-0"
            disabled={phase === "checking"}
            onClick={check}
          >
            {phase === "checking" ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="mr-1 h-3.5 w-3.5" />
            )}
            {phase === "checking" ? t("settings.updateChecking") : t("settings.updateCheck")}
          </Button>
        )}
        {desktop && phase === "available" && (
          <Button size="sm" className="shrink-0" onClick={install}>
            <Download className="mr-1 h-3.5 w-3.5" />
            {t("settings.updateInstall")}
          </Button>
        )}
        {desktop && phase === "installing" && (
          <Button size="sm" className="shrink-0" disabled>
            <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            {t("settings.updateInstallingShort")}
          </Button>
        )}
      </div>
    </div>
  );
}
