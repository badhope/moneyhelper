/** 手机扫码后的配对页：把 fragment 里的一次性令牌换成设备 cookie。 */

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Loader2, Smartphone, XCircle } from "lucide-react";
import { BrandLogo, BRAND } from "@/lib/brand";
import { pairRemote } from "@/lib/api";

function readPair(): { sid: string; token: string } {
  const hash = window.location.hash.replace(/^#/, "");
  const params = new URLSearchParams(hash);
  return {
    sid: params.get("s") || params.get("sid") || "",
    token: params.get("t") || params.get("token") || "",
  };
}

export function RemotePairView() {
  const zh = (navigator.language || "zh").toLowerCase().startsWith("zh");
  const pair = useMemo(readPair, []);
  const expired = useMemo(() => new URLSearchParams(window.location.search).get("expired") === "1", []);
  const [state, setState] = useState<"pairing" | "ok" | "error">("pairing");
  const [message, setMessage] = useState("");
  const [device, setDevice] = useState("");

  useEffect(() => {
    // 令牌已在客户端读走，先清掉地址栏，避免截图/复制时把凭据带出去
    try {
      window.history.replaceState({}, "", "/remote");
    } catch {
      /* ignore */
    }
    if (!pair.sid || !pair.token) {
      setState("error");
      setMessage(
        expired
          ? zh
            ? "远程连接已被电脑端停止，或已过期。请让电脑重新生成二维码。"
            : "The desktop stopped this remote session, or it expired. Generate a new QR code on the desktop."
          : zh
            ? "链接不完整，请在电脑上重新生成二维码。"
            : "This link is incomplete. Generate a new QR code on the desktop.",
      );
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const r = await pairRemote(pair.sid, pair.token);
        if (cancelled) return;
        setDevice(r.device_name || "");
        setState("ok");
        window.setTimeout(() => window.location.replace(r.redirect || "/?remote=1"), 700);
      } catch (e) {
        if (cancelled) return;
        setState("error");
        setMessage(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pair, expired, zh]);

  return (
    <div className="flex min-h-[100dvh] flex-col bg-background text-foreground">
      <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-6 py-10">
        <div className="mb-8 flex items-center gap-2">
          <BrandLogo size={28} />
          <div>
            <div className="text-sm font-semibold">{BRAND.name}</div>
            <div className="text-[11px] text-muted-foreground">{zh ? BRAND.tagline : "Remote control"}</div>
          </div>
        </div>

        <div className="rounded-2xl border border-border bg-card p-6 shadow-sm">
          {state === "pairing" && (
            <>
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
              <h1 className="mt-4 text-lg font-semibold">{zh ? "正在接入工作台…" : "Connecting…"}</h1>
              <p className="mt-2 text-[12px] leading-relaxed text-muted-foreground">
                {zh ? "正在校验一次性链接，成功后会在本机写入远程设备凭据。" : "Verifying the one-time link and storing a device credential."}
              </p>
            </>
          )}

          {state === "ok" && (
            <>
              <CheckCircle2 className="h-8 w-8 text-emerald-500" />
              <h1 className="mt-4 text-lg font-semibold">{zh ? "已接入" : "Connected"}</h1>
              <p className="mt-2 text-[12px] leading-relaxed text-muted-foreground">
                {(zh ? "正在打开工作台" : "Opening the workspace") + (device ? ` · ${device}` : "") + "…"}
              </p>
            </>
          )}

          {state === "error" && (
            <>
              <XCircle className="h-8 w-8 text-destructive" />
              <h1 className="mt-4 text-lg font-semibold">{zh ? "这条链接不能用了" : "This link no longer works"}</h1>
              <p className="mt-2 text-[12px] leading-relaxed text-muted-foreground">{message}</p>
              <p className="mt-4 text-[11px] leading-relaxed text-muted-foreground">
                {zh
                  ? "回到电脑上打开「远程控制」，点「刷新二维码」后重新扫码。旧链接会在刷新时立即失效。"
                  : "Go back to Remote Control on the desktop, refresh the QR code, and scan again. Old links expire immediately."}
              </p>
            </>
          )}
        </div>

        <div className="mt-6 flex items-center gap-2 text-[10.5px] text-muted-foreground">
          <Smartphone className="h-3.5 w-3.5" />
          {zh ? "手机只是控制面，数据与执行都留在电脑上。" : "The phone is a control surface. Data and execution stay on the desktop."}
        </div>
      </div>
    </div>
  );
}
