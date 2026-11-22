/** 远程控制面板：二维码 / 链接 / 设备会话 / 停止与刷新。 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Copy, Loader2, Radio, RefreshCw, Smartphone, Square, Wifi, WifiOff } from "lucide-react";
import { SidePanel } from "@/components/ui/side-panel";
import { Button } from "@/components/ui/button";
import { inputClsCompact } from "@/components/ui/field";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { copyText } from "@/lib/clipboard";
import {
  createRemoteSession,
  getRemoteConfig,
  refreshRemoteSession,
  startRemoteRelay,
  stopAllRemoteSessions,
  stopRemoteRelay,
  stopRemoteSession,
  updateRemoteConfig,
  type RemoteConfig,
  type RemoteLink,
  type RemoteSession,
} from "@/lib/api";

const HOUR_OPTIONS = [1, 12, 24, 72, 168];

function fmtTime(iso: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function sessionState(s: RemoteSession): "paired" | "waiting" | "expired" | "revoked" {
  if (s.revoked) return "revoked";
  if (s.expired) return "expired";
  return s.paired ? "paired" : "waiting";
}

export function RemoteControlPanel({
  open,
  onClose,
  onRemoteStarted,
}: {
  open: boolean;
  onClose: () => void;
  onRemoteStarted?: () => void;
}) {
  const { t } = useI18n();
  const { toast } = useToast();
  const [config, setConfig] = useState<RemoteConfig | null>(null);
  const [link, setLink] = useState<RemoteLink | null>(null);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [copied, setCopied] = useState(false);
  const [urlDraft, setUrlDraft] = useState("");
  const [hours, setHours] = useState(12);
  const [relayUrl, setRelayUrl] = useState("ws://127.0.0.1:8789");
  const [relayToken, setRelayToken] = useState("");
  const [relayBusy, setRelayBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true);
      try {
        const c = await getRemoteConfig();
        setConfig(c);
        setUrlDraft((prev) => (prev ? prev : c.public_url));
        setRelayUrl((prev) => (prev && prev !== "ws://127.0.0.1:8789" ? prev : c.relay_url || prev));
        setHours((prev) => (prev === 12 && c.session_hours !== 12 ? c.session_hours : prev));
        setError("");
        return c;
      } catch (e) {
        if (!quiet) setError(e instanceof Error ? e.message : String(e));
        return null;
      } finally {
        if (!quiet) setLoading(false);
      }
    },
    [],
  );

  const makeLink = useCallback(
    async (sid?: string) => {
      setCreating(true);
      setError("");
      try {
        const created = sid ? await refreshRemoteSession(sid) : await createRemoteSession({ hours });
        setLink(created);
        await load(true);
        onRemoteStarted?.();
        return created;
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return null;
      } finally {
        setCreating(false);
      }
    },
    [hours, load, onRemoteStarted],
  );

  // 打开面板：优先复用最新会话；已配对就展示设备，未配对就刷新出可用二维码。
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      const c = await load();
      if (cancelled || !c) return;
      const active = c.sessions.filter((s) => s.active);
      const paired = active.find((s) => s.paired);
      if (paired) {
        setLink(null);
        return;
      }
      const pending = active.find((s) => !s.paired);
      if (pending) {
        const refreshed = await makeLink(pending.sid);
        if (cancelled) return;
        if (refreshed) onRemoteStarted?.();
      }
    })();
    return () => {
      cancelled = true;
    };
    // makeLink 依赖 hours；打开时只跑一次，避免轮询把二维码刷掉
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // 面板开着时轮询：手机扫码后这里要自己变成「已连接」。
  useEffect(() => {
    if (!open) return;
    const timer = window.setInterval(() => {
      void load(true);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [open, load]);

  const current = useMemo(
    () => (link ? config?.sessions.find((s) => s.sid === link.sid) ?? null : null),
    [link, config],
  );
  const currentState = current ? sessionState(current) : link ? "waiting" : null;
  const activePaired = (config?.sessions ?? []).filter((s) => s.active && s.paired);

  const copy = () => {
    if (!link) return;
    if (copyText(link.pair_url)) {
      setCopied(true);
      toast(t("remote.linkCopied"), "ok");
      window.setTimeout(() => setCopied(false), 2000);
    } else {
      toast(t("remote.linkCopyFailed"), "error");
    }
  };

  const saveUrl = async () => {
    setLoading(true);
    try {
      const c = await updateRemoteConfig({ public_url: urlDraft.trim(), session_hours: hours });
      setConfig(c);
      toast(t("remote.saved"), "ok");
      // 地址变了，旧二维码仍是旧地址，直接刷新成新链接
      if (link) await makeLink(link.sid);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const startRelay = async () => {
    setRelayBusy(true);
    setError("");
    try {
      await startRemoteRelay({ relay_url: relayUrl.trim(), token: relayToken.trim() });
      setRelayToken("");
      setLink(null);
      await load(true);
      toast(t("remote.relayStarted"), "ok");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRelayBusy(false);
    }
  };

  const stopRelay = async () => {
    setRelayBusy(true);
    try {
      await stopRemoteRelay();
      setLink(null);
      await load(true);
      toast(t("remote.relayStopped"), "ok");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRelayBusy(false);
    }
  };

  const stop = async (sid?: string) => {
    const target = sid ?? link?.sid;
    if (!target) return;
    try {
      await stopRemoteSession(target);
      if (target === link?.sid) setLink(null);
      await load(true);
      toast(t("remote.stopped"), "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const stopAll = async () => {
    try {
      const r = await stopAllRemoteSessions();
      setLink(null);
      await load(true);
      toast(t("remote.allStopped").replace("{n}", String(r.revoked)), "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  return (
    <SidePanel open={open} onClose={onClose} title={t("remote.title")} icon={<Smartphone className="h-4 w-4" />}>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3.5">
        <p className="text-[11.5px] leading-relaxed text-muted-foreground">{t("remote.desc")}</p>

        {error && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-[12px] text-destructive">
            {error}
          </div>
        )}

        {config && !config.enabled && (
          <div className="rounded-lg border border-border bg-muted/30 px-3 py-2.5">
            <p className="text-[12px]">{t("remote.disabled")}</p>
            <Button
              className="mt-2 h-8"
              size="sm"
              onClick={async () => {
                try {
                  setConfig(await updateRemoteConfig({ enabled: true }));
                } catch (e) {
                  setError(e instanceof Error ? e.message : String(e));
                }
              }}
            >
              {t("remote.enable")}
            </Button>
          </div>
        )}

        <div className="grid gap-2 rounded-xl border border-border bg-card p-3">
          <label className="text-[11px] font-medium text-muted-foreground" htmlFor="remote-public-url">
            {t("remote.publicUrl")}
          </label>
          <div className="flex gap-2">
            <input
              id="remote-public-url"
              value={urlDraft}
              onChange={(e) => setUrlDraft(e.target.value)}
              placeholder="https://money.example.com"
              className={`${inputClsCompact} h-9 text-[12px]`}
            />
            <Button variant="outline" className="h-9 shrink-0" onClick={() => void saveUrl()} disabled={loading}>
              {t("remote.save")}
            </Button>
          </div>
          <p className="text-[10.5px] leading-relaxed text-muted-foreground">{t("remote.publicUrlHint")}</p>
          {(config?.warning || link?.warning) && (
            <p className="rounded-md bg-amber-500/10 px-2 py-1.5 text-[10.5px] leading-relaxed text-amber-700 dark:text-amber-300">
              {link?.warning || config?.warning}
            </p>
          )}
          <div className="flex items-center gap-2 pt-1">
            <span className="text-[11px] text-muted-foreground">{t("remote.sessionHours")}</span>
            <select
              value={hours}
              onChange={(e) => setHours(Number(e.target.value))}
              className="h-8 rounded-md border border-border bg-background px-2 text-[11.5px]"
            >
              {HOUR_OPTIONS.map((h) => (
                <option key={h} value={h}>
                  {h >= 24 ? `${h / 24} 天` : `${h} 小时`}
                </option>
              ))}
            </select>
            <span className="ml-auto text-[10.5px] text-muted-foreground">
              {t("remote.activeCount").replace("{n}", String(config?.active_count ?? 0))}
            </span>
          </div>
        </div>

        <div className="grid gap-2 rounded-xl border border-border bg-card p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
              <Radio className="h-3.5 w-3.5" />
              {t("remote.relayTitle")}
            </span>
            {config?.relay.active && (
              <span className="flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-700 dark:text-emerald-300">
                <Wifi className="h-3 w-3" />
                {t("remote.relayActive")}
              </span>
            )}
          </div>
          <p className="text-[10.5px] leading-relaxed text-muted-foreground">{t("remote.relayHint")}</p>
          <input
            value={relayUrl}
            onChange={(e) => setRelayUrl(e.target.value)}
            placeholder="ws://relay.example.com:8789"
            className={`${inputClsCompact} h-9 text-[12px]`}
            aria-label={t("remote.relayUrl")}
          />
          {!config?.relay.active && (
            <input
              value={relayToken}
              onChange={(e) => setRelayToken(e.target.value)}
              type="password"
              placeholder={config?.relay_token_set ? t("remote.relayTokenSaved") : t("remote.relayToken")}
              className={`${inputClsCompact} h-9 text-[12px]`}
              aria-label={t("remote.relayToken")}
            />
          )}
          {config?.relay.active ? (
            <div className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate rounded-md bg-emerald-500/10 px-2 py-1.5 text-[10.5px] text-emerald-700 dark:text-emerald-300">
                {config.relay.public_url}
              </span>
              <Button variant="outline" className="h-8 shrink-0 text-[11px]" onClick={() => void stopRelay()} disabled={relayBusy}>
                {relayBusy ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <WifiOff className="mr-1 h-3.5 w-3.5" />}
                {t("remote.relayStop")}
              </Button>
            </div>
          ) : (
            <Button className="h-9 text-[12px]" onClick={() => void startRelay()} disabled={relayBusy || !relayUrl.trim()}>
              {relayBusy ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Radio className="mr-1 h-3.5 w-3.5" />}
              {t("remote.relayStart")}
            </Button>
          )}
          {config?.relay.active && (
            <p className="text-[10.5px] leading-relaxed text-muted-foreground">{t("remote.relayGenerateHint")}</p>
          )}
        </div>

        {link ? (
          <div className="rounded-xl border border-border bg-card p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-[12px] font-medium">
                <Smartphone className="h-3.5 w-3.5" />
                {current?.device_name || t("remote.waitingDevice")}
              </span>
              <span
                className={`rounded-full px-2 py-0.5 text-[10px] ${
                  currentState === "paired"
                    ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                    : currentState === "expired" || currentState === "revoked"
                      ? "bg-destructive/10 text-destructive"
                      : "bg-amber-500/10 text-amber-700 dark:text-amber-300"
                }`}
              >
                {currentState === "paired"
                  ? t("remote.connected")
                  : currentState === "expired"
                    ? t("remote.expired")
                    : currentState === "revoked"
                      ? t("remote.revoked")
                      : t("remote.waiting")}
              </span>
            </div>

            {current?.paired ? (
              <div className="space-y-1 rounded-lg bg-muted/30 px-3 py-2.5 text-[11.5px]">
                <div className="flex justify-between gap-2">
                  <span className="text-muted-foreground">{t("remote.pairedAt")}</span>
                  <span>{fmtTime(current.paired_at)}</span>
                </div>
                <div className="flex justify-between gap-2">
                  <span className="text-muted-foreground">{t("remote.lastSeen")}</span>
                  <span>{fmtTime(current.last_seen_at)}</span>
                </div>
                <div className="flex justify-between gap-2">
                  <span className="text-muted-foreground">{t("remote.linkExpires")}</span>
                  <span>{fmtTime(current.expires_at)}</span>
                </div>
              </div>
            ) : (
              <>
                {link.qr_svg ? (
                  <div className="flex justify-center py-2">
                    <img
                      src={link.qr_svg}
                      alt={t("remote.qrAlt")}
                      className="h-52 w-52 rounded-lg border border-border bg-white p-2"
                    />
                  </div>
                ) : (
                  <p className="py-3 text-center text-[11.5px] text-muted-foreground">{t("remote.noQr")}</p>
                )}
                <p className="text-center text-[11.5px] text-muted-foreground">{t("remote.scanHint")}</p>
              </>
            )}

            <div className="mt-2 flex items-center gap-1 rounded-lg border border-border bg-background px-2 py-1.5">
              <span className="min-w-0 flex-1 truncate text-[10.5px] text-muted-foreground">{link.pair_url}</span>
              <button
                type="button"
                onClick={copy}
                className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                aria-label={t("remote.copy")}
              >
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              </button>
            </div>

            <div className="mt-2 grid grid-cols-2 gap-2">
              <Button variant="outline" className="h-8 text-[11.5px]" onClick={() => void makeLink(link.sid)} disabled={creating}>
                {creating ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1 h-3.5 w-3.5" />}
                {t("remote.refresh")}
              </Button>
              <Button variant="outline" className="h-8 text-[11.5px] text-destructive" onClick={() => void stop()}>
                <Square className="mr-1 h-3.5 w-3.5" />
                {t("remote.stop")}
              </Button>
            </div>
            <p className="mt-2 text-[10.5px] leading-relaxed text-muted-foreground">{t("remote.stopHint")}</p>
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-border bg-muted/20 p-5 text-center">
            <Smartphone className="mx-auto h-7 w-7 text-muted-foreground" />
            <p className="mt-2 text-[12px] font-medium">{t("remote.noSession")}</p>
            <p className="mt-1 text-[10.5px] text-muted-foreground">{t("remote.noSessionHint")}</p>
            <Button className="mt-3 h-9" onClick={() => void makeLink()} disabled={creating || !config?.enabled}>
              {creating ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Smartphone className="mr-1 h-4 w-4" />}
              {t("remote.generate")}
            </Button>
          </div>
        )}

        {activePaired.length > 0 && (
          <div className="rounded-xl border border-border bg-card p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[12px] font-medium">{t("remote.devices")}</span>
              <button
                type="button"
                onClick={() => void stopAll()}
                className="text-[10.5px] text-destructive hover:underline"
              >
                {t("remote.stopAll")}
              </button>
            </div>
            <div className="space-y-1.5">
              {activePaired.map((s) => (
                <div key={s.sid} className="flex items-center justify-between gap-2 rounded-lg bg-muted/30 px-2.5 py-2">
                  <div className="min-w-0">
                    <div className="truncate text-[11.5px] font-medium">{s.device_name || t("remote.phone")}</div>
                    <div className="truncate text-[10px] text-muted-foreground">
                      {t("remote.lastSeen")} {fmtTime(s.last_seen_at)}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => void stop(s.sid)}
                    className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-[10.5px] text-destructive hover:bg-destructive/10"
                  >
                    <WifiOff className="h-3.5 w-3.5" />
                    {t("remote.stop")}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        <p className="text-[10px] leading-relaxed text-muted-foreground">{t("remote.securityHint")}</p>
      </div>
    </SidePanel>
  );
}
