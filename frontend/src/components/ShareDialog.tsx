import { useEffect, useState } from "react";
import { Check, Copy, ExternalLink, Link2, Loader2, ShieldOff, X } from "lucide-react";
import { createShare, revokeShare, type ShareResult } from "@/lib/api";
import { copyText } from "@/lib/clipboard";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { errMsg } from "@/lib/utils";

/** 会话只读分享：生成不可变快照链接，可复制、打开、撤销；不暴露账本与模型配置。 */
export function ShareDialog({
  threadId,
  open,
  onClose,
}: {
  threadId: string;
  open: boolean;
  onClose: () => void;
}) {
  const { t: tr } = useI18n();
  const { toast } = useToast();
  const [days, setDays] = useState(7);
  const [result, setResult] = useState<ShareResult | null>(null);
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!open) return;
    setResult(null);
    setCopied(false);
  }, [open]);

  const url = result?.path ? new URL(result.path, window.location.origin).toString() : "";

  const create = async () => {
    setCreating(true);
    try {
      const r = await createShare(threadId, days);
      setResult(r);
      setCopied(false);
    } catch (e) {
      toast(errMsg(e), "error");
    } finally {
      setCreating(false);
    }
  };

  const copy = () => {
    if (!url) return;
    if (copyText(url)) {
      setCopied(true);
      toast(tr("share.copied"), "ok");
      window.setTimeout(() => setCopied(false), 1800);
    } else {
      toast(tr("share.copyFail"), "error");
    }
  };

  const revoke = async () => {
    if (!result) return;
    setRevoking(true);
    try {
      await revokeShare(result.token);
      setResult(null);
      toast(tr("share.revoked"), "ok");
    } catch (e) {
      toast(errMsg(e), "error");
    } finally {
      setRevoking(false);
    }
  };

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-3 backdrop-blur-[2px]" role="dialog" aria-modal="true">
      <div className="w-full max-w-[520px] overflow-hidden rounded-2xl border border-border bg-card shadow-2xl">
        <div className="flex items-start justify-between border-b border-border px-5 py-3.5">
          <div>
            <h2 className="flex items-center gap-2 text-[15px] font-semibold">
              <Link2 className="h-4 w-4 text-primary" /> {tr("share.title")}
            </h2>
            <p className="mt-0.5 text-[11.5px] text-muted-foreground">{tr("share.desc")}</p>
          </div>
          <button type="button" onClick={onClose} aria-label={tr("share.close")} className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3 px-5 py-4">
          {!result ? (
            <>
              <div className="flex items-center gap-2">
                <span className="text-[12.5px] text-muted-foreground">{tr("share.expire")}</span>
                <select
                  value={days}
                  onChange={(e) => setDays(Number(e.target.value))}
                  className="h-8 rounded-lg border border-border bg-background px-2 text-[12.5px] outline-none"
                >
                  <option value={1}>{tr("share.day", { n: 1 })}</option>
                  <option value={7}>{tr("share.day", { n: 7 })}</option>
                  <option value={30}>{tr("share.day", { n: 30 })}</option>
                </select>
              </div>
              <ul className="space-y-1 rounded-xl bg-muted/40 px-3 py-2.5 text-[11.5px] leading-relaxed text-muted-foreground">
                <li>• {tr("share.note1")}</li>
                <li>• {tr("share.note2")}</li>
                <li>• {tr("share.note3")}</li>
              </ul>
              <button
                type="button"
                onClick={create}
                disabled={creating || !threadId}
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-primary px-3.5 py-2 text-[13px] font-medium text-primary-foreground disabled:opacity-50"
              >
                {creating && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {tr("share.create")}
              </button>
            </>
          ) : (
            <>
              <div className="flex items-center gap-1.5">
                <input
                  readOnly
                  value={url}
                  onFocus={(e) => e.target.select()}
                  className="h-9 min-w-0 flex-1 rounded-lg border border-border bg-background px-2.5 text-[12px] text-foreground/85"
                />
                <button type="button" onClick={copy} className="inline-flex h-9 shrink-0 items-center gap-1 rounded-lg border border-border px-2.5 text-[12px] hover:bg-accent">
                  {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
                  {tr("share.copy")}
                </button>
              </div>
              <p className="text-[11.5px] text-muted-foreground">
                {tr("share.expiresAt", { t: new Date(result.expires_at).toLocaleString() })}
              </p>
              <div className="flex items-center gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => window.open(url, "_blank", "noopener,noreferrer")}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[12.5px] hover:bg-accent"
                >
                  <ExternalLink className="h-3.5 w-3.5" /> {tr("share.open")}
                </button>
                <button
                  type="button"
                  onClick={revoke}
                  disabled={revoking}
                  className="ml-auto inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12.5px] text-red-600 hover:bg-red-50 disabled:opacity-50 dark:hover:bg-red-950/40"
                >
                  {revoking ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldOff className="h-3.5 w-3.5" />}
                  {tr("share.revoke")}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
