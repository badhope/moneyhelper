/** 外部投递通道（4.22.0）：邮箱真发信 / 签名 HTTPS 网关，附投递留痕。
 *
 * 这是“真实出本机”的一层：SMTP 走 smtplib，网关走 httpx；没有密钥时只显示
 * 待配置，不伪造“已发送”。税局/银行/审计是否真正入账，以持牌通道回执为准。
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  FileCheck2,
  Landmark,
  LockKeyhole,
  Mail,
  PlugZap,
  RefreshCw,
  Send,
  Settings2,
  ShieldCheck,
  Trash2,
  Wallet,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { SidePanel } from "@/components/ui/side-panel";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/lib/i18n";
import {
  useDeleteExternalChannel,
  useDeliverPacket,
  useExternalChannels,
  useSaveExternalChannel,
  useTestExternalChannel,
  type ExternalChannel,
  type ExternalDelivery,
  type HandoffRecord,
} from "@/lib/use-external-packets";

const inputClass =
  "h-10 w-full rounded-xl border border-border/70 bg-background px-3 text-[13px] text-foreground outline-none " +
  "transition-colors placeholder:text-muted-foreground/70 focus:border-primary";

interface PacketOption {
  kind: HandoffRecord["kind"];
  packetId: string;
  status: string;
}

interface Draft {
  label: string;
  enabled: boolean;
  host: string;
  port: string;
  security: string;
  username: string;
  from_addr: string;
  to_addrs: string;
  subject_prefix: string;
  endpoint: string;
  provider_name: string;
  timeout_sec: string;
  password: string;
  signing_secret: string;
}

function channelId(channel: ExternalChannel): string {
  return channel.channel_id ?? channel.id ?? "";
}

function kindLabel(kind: string, t: (key: string) => string): string {
  if (kind === "tax") return t("external.handoffKindTax");
  if (kind === "payment") return t("external.handoffKindPayment");
  return t("external.handoffKindConsolidation");
}

function channelName(channel: ExternalChannel, t: (key: string) => string): string {
  return t(`external.channel.${channelId(channel)}.name`);
}

function channelHint(channel: ExternalChannel, t: (key: string) => string): string {
  return t(`external.channel.${channelId(channel)}.hint`);
}

function channelIcon(channel: ExternalChannel): ReactNode {
  const cid = channelId(channel);
  if (cid === "smtp") return <Mail className="h-5 w-5" />;
  if (cid === "tax_gateway") return <Landmark className="h-5 w-5" />;
  if (cid === "bank_gateway") return <Wallet className="h-5 w-5" />;
  return <FileCheck2 className="h-5 w-5" />;
}

function channelTone(channel: ExternalChannel): string {
  if (channel.ready) return "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300";
  if (channel.configured) return "bg-amber-500/12 text-amber-700 dark:text-amber-300";
  return "bg-muted/60 text-muted-foreground";
}

function channelSummary(channel: ExternalChannel): string {
  const cfg = channel.config;
  if (channelId(channel) === "smtp") {
    const to = cfg.to_addrs;
    return Array.isArray(to) ? to.join(", ") : String(cfg.from_addr ?? "");
  }
  const provider = String(cfg.provider_name ?? "").trim();
  const endpoint = String(cfg.endpoint ?? "");
  const host = endpoint.replace(/^https?:\/\//, "").split("/")[0];
  return [provider, host].filter(Boolean).join(" · ");
}

function missingLabel(code: string, t: (key: string) => string): string {
  return t(`external.channelMissing.${code}`);
}

function formatTs(value: string): string {
  return value ? value.replace("T", " ").slice(0, 16) : "";
}

function fromChannel(channel: ExternalChannel): Draft {
  const cfg = channel.config;
  return {
    label: channel.label,
    enabled: channel.enabled,
    host: String(cfg.host ?? ""),
    port: String(cfg.port ?? "587"),
    security: String(cfg.security ?? "starttls"),
    username: String(cfg.username ?? ""),
    from_addr: String(cfg.from_addr ?? ""),
    to_addrs: Array.isArray(cfg.to_addrs) ? cfg.to_addrs.join(", ") : String(cfg.to_addrs ?? ""),
    subject_prefix: String(cfg.subject_prefix ?? "[Moneyhelper]"),
    endpoint: String(cfg.endpoint ?? ""),
    provider_name: String(cfg.provider_name ?? ""),
    timeout_sec: String(cfg.timeout_sec ?? "15"),
    password: "",
    signing_secret: "",
  };
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-[12px] font-medium text-foreground">{label}</span>
      {hint ? <span className="mt-0.5 block text-[11px] leading-relaxed text-muted-foreground">{hint}</span> : null}
      <div className="mt-1.5">{children}</div>
    </label>
  );
}

function StatusPill({ channel, t }: { channel: ExternalChannel; t: (key: string) => string }) {
  if (channel.ready) {
    return (
      <Badge variant="ok" className="gap-1 px-2 py-0.5 text-[10.5px]">
        <CheckCircle2 className="h-3 w-3" />
        {t("external.channelReady")}
      </Badge>
    );
  }
  if (!channel.configured) {
    return (
      <Badge variant="muted" className="gap-1 px-2 py-0.5 text-[10.5px]">
        <LockKeyhole className="h-3 w-3" />
        {t("external.channelUnconfigured")}
      </Badge>
    );
  }
  return (
    <Badge variant="warn" className="gap-1 px-2 py-0.5 text-[10.5px]">
      <AlertTriangle className="h-3 w-3" />
      {channel.enabled ? t("external.channelIncomplete") : t("external.channelDisabled")}
    </Badge>
  );
}

function ChannelCard({
  channel,
  onConfig,
  onTest,
  testing,
}: {
  channel: ExternalChannel;
  onConfig: () => void;
  onTest: () => void;
  testing: boolean;
}) {
  const { t } = useI18n();
  const summary = channelSummary(channel);
  return (
    <article className="rounded-2xl border border-border/55 bg-background/45 p-3.5 sm:p-4">
      <div className="flex items-start justify-between gap-3">
        <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${channelTone(channel)}`}>
          {channelIcon(channel)}
        </div>
        <StatusPill channel={channel} t={t} />
      </div>
      <div className="mt-3">
        <div className="text-[14px] font-semibold">{channelName(channel, t)}</div>
        <p className="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">{channelHint(channel, t)}</p>
      </div>
      <div className="mt-2 min-h-[18px] truncate text-[11.5px] text-muted-foreground" title={summary}>
        {summary || t("external.channelNoAddress")}
      </div>
      {channel.last_test_at ? (
        <div
          className={
            "mt-2 flex items-center gap-1.5 text-[11px] " +
            (channel.last_test_ok ? "text-emerald-700 dark:text-emerald-300" : "text-red-700 dark:text-red-300")
          }
        >
          {channel.last_test_ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
          <span className="truncate">
            {t("external.channelLastTest")} {formatTs(channel.last_test_at)} · {channel.last_test_detail}
          </span>
        </div>
      ) : (
        <div className="mt-2 flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <Clock3 className="h-3.5 w-3.5" />
          {t("external.channelNeverTested")}
        </div>
      )}
      {channel.missing.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1">
          {channel.missing.map((code) => (
            <span key={code} className="rounded-md bg-amber-500/10 px-1.5 py-0.5 text-[10.5px] text-amber-800 dark:text-amber-300">
              {missingLabel(code, t)}
            </span>
          ))}
        </div>
      ) : null}
      <div className="mt-3 flex gap-2">
        <Button size="sm" variant="outline" onClick={onConfig} className="h-8 flex-1 rounded-lg px-2.5 text-[12px]">
          <Settings2 className="h-3.5 w-3.5" />
          {t("external.channelConfigure")}
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={onTest}
          disabled={testing || !channel.ready}
          className="h-8 flex-1 rounded-lg px-2.5 text-[12px]"
        >
          <PlugZap className={`h-3.5 w-3.5 ${testing ? "animate-pulse" : ""}`} />
          {testing ? t("external.channelTesting") : t("external.channelTest")}
        </Button>
      </div>
    </article>
  );
}

function DeliveryStatus({ status, t }: { status: string; t: (key: string) => string }) {
   if (status === "accepted") {
    return (
      <Badge variant="ok" className="gap-1 px-2 py-0.5 text-[10.5px]">
        <CheckCircle2 className="h-3 w-3" />
        {t("external.deliveryAccepted")}
      </Badge>
    );
  }
  if (status === "failed") {
    return (
      <Badge variant="danger" className="gap-1 px-2 py-0.5 text-[10.5px]">
        <XCircle className="h-3 w-3" />
        {t("external.deliveryFailed")}
      </Badge>
    );
  }
  return (
    <Badge variant="warn" className="gap-1 px-2 py-0.5 text-[10.5px]">
      <Clock3 className="h-3 w-3" />
      {t("external.deliveryPending")}
    </Badge>
  );
}

function DeliveryRow({
  delivery,
  channel,
  t,
}: {
  delivery: ExternalDelivery;
  channel?: ExternalChannel;
  t: (key: string) => string;
}) {
  const receipt =
    String(delivery.receipt.receipt_id ?? "") ||
    String(delivery.receipt.status_code ?? "") ||
    String(delivery.receipt.message_id ?? "");
  return (
    <div className="flex flex-wrap items-start justify-between gap-2 rounded-xl border border-border/45 bg-background/45 px-3 py-2.5">
      <div className="flex min-w-0 items-start gap-2.5">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          {channel ? channelIcon(channel) : <Send className="h-4 w-4" />}
        </div>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[12.5px] font-semibold">{kindLabel(delivery.kind, t)}</span>
            <span className="text-[11px] text-muted-foreground">
              {channel ? channelName(channel, t) : delivery.channel_id}
            </span>
            <DeliveryStatus status={delivery.status} t={t} />
          </div>
          <div className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">{delivery.packet_id}</div>
          {delivery.error ? (
            <div className="mt-1 text-[11px] leading-relaxed text-red-700 dark:text-red-300">{delivery.error}</div>
          ) : receipt ? (
            <div className="mt-1 text-[11px] text-muted-foreground">
              {t("external.deliveryReceipt")} · <span className="font-mono">{receipt}</span>
            </div>
          ) : null}
        </div>
      </div>
      <span className="text-[11px] tabular-nums text-muted-foreground">{formatTs(delivery.updated_at)}</span>
    </div>
  );
}

export function ExternalDeliveryCenter({
  period,
  groupId,
  packets,
}: {
  period: string;
  groupId: string;
  packets: PacketOption[];
}) {
  const { t } = useI18n();
  const query = useExternalChannels();
  const save = useSaveExternalChannel();
  const test = useTestExternalChannel();
  const remove = useDeleteExternalChannel();
  const deliver = useDeliverPacket();

  const [configId, setConfigId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [kind, setKind] = useState<HandoffRecord["kind"]>("tax");
  const [channel, setChannel] = useState("");
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [flash, setFlash] = useState<{ tone: "ok" | "danger"; text: string } | null>(null);

  const channels = query.data?.channels ?? [];
  const selectedPacket = packets.find((item) => item.kind === kind);
  const matching = useMemo(
    () => channels.filter((item) => item.kinds.includes(kind)),
    [channels, kind],
  );
  const selectedChannel = matching.find((item) => channelId(item) === channel);

  useEffect(() => {
    if (!selectedPacket) {
      const first = packets.find((item) => item.status !== "missing");
      if (first) setKind(first.kind);
      return;
    }
    if (!matching.some((item) => item.ready && channelId(item) === channel)) {
      const ready = matching.find((item) => item.ready);
      setChannel(ready ? channelId(ready) : "");
    }
  }, [packets, selectedPacket, matching, channel]);

  useEffect(() => setConfirming(false), [kind, channel]);

  function openConfig(item: ExternalChannel) {
    setConfigId(channelId(item));
    setDraft(fromChannel(item));
    setFlash(null);
  }

  function closeConfig() {
    setConfigId(null);
    setDraft(null);
  }

  function submitConfig() {
    if (!configId || !draft) return;
    const isSmtp = configId === "smtp";
    const config: Record<string, unknown> = isSmtp
      ? {
          host: draft.host.trim(),
          port: Number(draft.port || 587),
          security: draft.security,
          username: draft.username.trim(),
          from_addr: draft.from_addr.trim(),
          to_addrs: draft.to_addrs
            .split(/[,;，；\n]/)
            .map((item) => item.trim())
            .filter(Boolean),
          subject_prefix: draft.subject_prefix.trim(),
        }
      : {
          endpoint: draft.endpoint.trim(),
          provider_name: draft.provider_name.trim(),
          timeout_sec: Number(draft.timeout_sec || 15),
        };
    let secret: Record<string, string> | undefined;
    if (isSmtp) {
      secret = draft.password ? { password: draft.password } : undefined;
    } else {
      secret = draft.signing_secret ? { signing_secret: draft.signing_secret } : undefined;
    }
    setFlash(null);
    save.mutate(
      { channel_id: configId, label: draft.label.trim(), config, secret, enabled: draft.enabled },
      {
        onSuccess: () => {
          setFlash({ tone: "ok", text: t("external.channelSaved") });
          closeConfig();
        },
        onError: (error: Error) => setFlash({ tone: "danger", text: error.message }),
      },
    );
  }

  function runTest(item: ExternalChannel) {
    const cid = channelId(item);
    setTestingId(cid);
    setFlash(null);
    test.mutate(
      { channel_id: cid },
      {
        onSuccess: (result) => {
          setTestingId(null);
          setFlash({
            tone: result.ok ? "ok" : "danger",
            text: `${result.ok ? t("external.channelTestOk") : t("external.channelTestFail")}：${result.detail}`,
          });
        },
        onError: (error: Error) => {
          setTestingId(null);
          setFlash({ tone: "danger", text: error.message });
        },
      },
    );
  }

  function doSend() {
    if (!selectedChannel || !selectedPacket || !selectedPacket.packetId) return;
    if (!confirming) {
      setConfirming(true);
      return;
    }
    setFlash(null);
    deliver.mutate(
      {
        channel_id: channelId(selectedChannel),
        kind,
        period,
        group_id: kind === "consolidation" ? groupId : undefined,
        note,
      },
      {
        onSuccess: (result) => {
          setConfirming(false);
          setFlash({
            tone: result.duplicate ? "ok" : "ok",
            text: result.duplicate ? t("external.deliverDuplicate") : t("external.deliverDone"),
          });
        },
        onError: (error: Error) => {
          setConfirming(false);
          setFlash({ tone: "danger", text: error.message });
        },
      },
    );
  }

  return (
    <Card className="relative overflow-hidden rounded-[24px] border-border/60 p-4 shadow-[var(--shadow-soft)] sm:p-6">
      <div
        className="pointer-events-none absolute inset-x-0 top-0 h-32 opacity-70"
        style={{
          backgroundImage:
            "radial-gradient(90% 140% at 15% 0%, hsl(var(--primary) / 0.12), transparent 60%), radial-gradient(70% 100% at 100% 0%, hsl(var(--brand-gold) / 0.10), transparent 55%)",
        }}
      />
      <div className="relative flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-primary/12 text-primary">
            <Send className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[18px] font-bold tracking-tight sm:text-[19px]">{t("external.deliveryTitle")}</h2>
              {query.data ? (
                <>
                  <Badge variant="ok" className="px-2.5 py-1 text-[11.5px]">
                    {t("external.deliveryAcceptedShort")} {query.data.stats.accepted}
                  </Badge>
                  {query.data.stats.failed > 0 ? (
                    <Badge variant="danger" className="px-2.5 py-1 text-[11.5px]">
                      {t("external.deliveryFailedShort")} {query.data.stats.failed}
                    </Badge>
                  ) : null}
                </>
              ) : null}
            </div>
            <p className="mt-1 max-w-3xl text-[12.5px] leading-relaxed text-muted-foreground">
              {t("external.deliveryHint")}
            </p>
          </div>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => query.refetch()}
          disabled={query.isFetching}
          className="h-9 rounded-xl px-3 text-[12.5px]"
        >
          <RefreshCw className={`h-4 w-4 ${query.isFetching ? "animate-spin" : ""}`} />
          {t("external.channelRefresh")}
        </Button>
      </div>

      {flash ? (
        <div
          className={
            "relative mt-4 flex items-start gap-2 rounded-xl px-3 py-2.5 text-[12px] " +
            (flash.tone === "ok"
              ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
              : "bg-red-500/10 text-red-700 dark:text-red-300")
          }
        >
          {flash.tone === "ok" ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0" />}
          <span>{flash.text}</span>
        </div>
      ) : null}

      <div className="relative mt-4 grid gap-3 sm:grid-cols-2 2xl:grid-cols-4">
        {query.isLoading
          ? [0, 1, 2, 3].map((key) => <div key={key} className="h-52 animate-pulse rounded-2xl bg-muted/25" />)
          : channels.map((item) => (
              <ChannelCard
                key={channelId(item)}
                channel={item}
                onConfig={() => openConfig(item)}
                onTest={() => runTest(item)}
                testing={testingId === channelId(item)}
              />
            ))}
      </div>

      <div className="relative mt-4 rounded-2xl border border-border/50 bg-gradient-to-br from-primary/6 via-background/50 to-transparent p-3.5 sm:p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-[14px] font-semibold">{t("external.deliverComposerTitle")}</div>
            <div className="mt-0.5 text-[11.5px] text-muted-foreground">{t("external.deliverComposerHint")}</div>
          </div>
          <Badge variant="muted" className="px-2.5 py-1 text-[11px]">
            <ShieldCheck className="h-3.5 w-3.5" />
            {t("external.deliverReceiptOnly")}
          </Badge>
        </div>

        <div className="mt-3 grid gap-2.5 lg:grid-cols-[240px_minmax(0,1fr)_220px]">
          <Field label={t("external.deliverPacket")}>
            <select
              className={inputClass}
              value={kind}
              onChange={(event) => setKind(event.target.value as HandoffRecord["kind"])}
            >
              {packets.map((item) => (
                <option key={item.kind} value={item.kind}>
                  {kindLabel(item.kind, t)} · {item.status}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("external.deliverChannel")}>
            <select className={inputClass} value={channel} onChange={(event) => setChannel(event.target.value)}>
              <option value="">{t("external.deliverPickChannel")}</option>
              {matching.map((item) => (
                <option key={channelId(item)} value={channelId(item)} disabled={!item.ready}>
                  {channelName(item, t)} {item.ready ? "" : `· ${t("external.channelNotReady")}`}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("external.deliverNote")}>
            <input
              className={inputClass}
              value={note}
              maxLength={120}
              placeholder={t("external.deliverNotePlaceholder")}
              onChange={(event) => setNote(event.target.value)}
            />
          </Field>
        </div>

        {selectedPacket && selectedPacket.status === "missing" ? (
          <div className="mt-2.5 flex items-center gap-2 rounded-lg bg-amber-500/10 px-2.5 py-2 text-[11.5px] text-amber-800 dark:text-amber-300">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            {t("external.deliverMissingPacket")}
          </div>
        ) : null}

        {confirming && selectedChannel ? (
          <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-primary/25 bg-primary/8 px-3 py-2.5 text-[12px]">
            <span className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-primary" />
              {t("external.deliverConfirm", {
                channel: channelName(selectedChannel, t),
                packet: selectedPacket ? kindLabel(selectedPacket.kind, t) : "",
              })}
            </span>
            <div className="flex gap-2">
              <Button size="sm" variant="ghost" onClick={() => setConfirming(false)} className="h-8 rounded-lg px-2.5 text-[12px]">
                {t("external.cancel")}
              </Button>
              <Button size="sm" onClick={doSend} disabled={deliver.isPending} className="h-8 rounded-lg px-3 text-[12px]">
                {deliver.isPending ? t("external.delivering") : t("external.deliverConfirmButton")}
              </Button>
            </div>
          </div>
        ) : null}

        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <div className="text-[11px] leading-relaxed text-muted-foreground">{query.data?.boundary}</div>
          <Button
            onClick={doSend}
            disabled={
              !selectedChannel ||
              !selectedChannel.ready ||
              !selectedPacket ||
              !selectedPacket.packetId ||
              selectedPacket.status === "missing" ||
              deliver.isPending
            }
            className="h-10 rounded-xl px-4 text-[13px]"
          >
            {deliver.isPending ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            {deliver.isPending
              ? t("external.delivering")
              : confirming
                ? t("external.deliverConfirmButton")
                : t("external.deliverAction")}
          </Button>
        </div>
      </div>

      <div className="relative mt-4">
        <div className="flex items-center justify-between gap-2">
          <div className="text-[13px] font-semibold">{t("external.deliveryRecent")}</div>
          <span className="text-[11px] text-muted-foreground">
            {t("external.deliveryCount", { n: query.data?.deliveries.length ?? 0 })}
          </span>
        </div>
        {(query.data?.deliveries.length ?? 0) === 0 ? (
          <div className="mt-2">
            <EmptyState mode="compact" text={t("external.deliveryEmpty")} />
          </div>
        ) : (
          <div className="mt-2 grid gap-2 2xl:grid-cols-2">
            {(query.data?.deliveries ?? []).slice(0, 6).map((item) => (
              <DeliveryRow
                key={item.id}
                delivery={item}
                channel={channels.find((entry) => channelId(entry) === item.channel_id)}
                t={t}
              />
            ))}
          </div>
        )}
      </div>

      <SidePanel
        open={Boolean(configId && draft)}
        onClose={closeConfig}
        title={configId ? t(`external.channel.${configId}.name`) : t("external.channelConfigure")}
        icon={<Settings2 className="h-4 w-4" />}
        widthKey="external.channelPanelWidth"
        defaultWidth={460}
      >
        {configId && draft ? (
          <div className="space-y-4">
            <div className="rounded-xl border border-border/50 bg-muted/20 px-3 py-2.5 text-[11.5px] leading-relaxed text-muted-foreground">
              {configId === "smtp" ? t("external.channelSmtpHint") : t("external.channelGatewayHint")}
            </div>
            <Field label={t("external.channelLabel")}>
              <input
                className={inputClass}
                value={draft.label}
                maxLength={60}
                onChange={(event) => setDraft({ ...draft, label: event.target.value })}
              />
            </Field>
            {configId === "smtp" ? (
              <>
                <div className="grid grid-cols-[minmax(0,1fr)_110px] gap-2">
                  <Field label={t("external.channelSmtpHost")}>
                    <input
                      className={inputClass}
                      value={draft.host}
                      placeholder="smtp.example.com"
                      onChange={(event) => setDraft({ ...draft, host: event.target.value })}
                    />
                  </Field>
                  <Field label={t("external.channelSmtpPort")}>
                    <input
                      className={inputClass}
                      value={draft.port}
                      inputMode="numeric"
                      onChange={(event) => setDraft({ ...draft, port: event.target.value })}
                    />
                  </Field>
                </div>
                <Field label={t("external.channelSmtpSecurity")}>
                  <select
                    className={inputClass}
                    value={draft.security}
                    onChange={(event) => setDraft({ ...draft, security: event.target.value })}
                  >
                    <option value="starttls">STARTTLS · 587</option>
                    <option value="ssl">SSL/TLS · 465</option>
                    <option value="none">{t("external.channelSmtpPlain")}</option>
                  </select>
                </Field>
                <div className="grid grid-cols-2 gap-2">
                  <Field label={t("external.channelSmtpUser")}>
                    <input
                      className={inputClass}
                      value={draft.username}
                      autoComplete="username"
                      onChange={(event) => setDraft({ ...draft, username: event.target.value })}
                    />
                  </Field>
                  <Field label={t("external.channelSmtpPassword")} hint={t("external.channelSecretKeep")}>
                    <input
                      className={inputClass}
                      type="password"
                      value={draft.password}
                      autoComplete="new-password"
                      placeholder={t("external.channelSecretPlaceholder")}
                      onChange={(event) => setDraft({ ...draft, password: event.target.value })}
                    />
                  </Field>
                </div>
                <Field label={t("external.channelSmtpFrom")}>
                  <input
                    className={inputClass}
                    value={draft.from_addr}
                    placeholder="finance@example.com"
                    onChange={(event) => setDraft({ ...draft, from_addr: event.target.value })}
                  />
                </Field>
                <Field label={t("external.channelSmtpTo")} hint={t("external.channelSmtpToHint")}>
                  <input
                    className={inputClass}
                    value={draft.to_addrs}
                    placeholder="accountant@example.com"
                    onChange={(event) => setDraft({ ...draft, to_addrs: event.target.value })}
                  />
                </Field>
                <Field label={t("external.channelSmtpSubject")}>
                  <input
                    className={inputClass}
                    value={draft.subject_prefix}
                    maxLength={40}
                    onChange={(event) => setDraft({ ...draft, subject_prefix: event.target.value })}
                  />
                </Field>
              </>
            ) : (
              <>
                <Field label={t("external.channelEndpoint")} hint={t("external.channelEndpointHint")}>
                  <input
                    className={inputClass}
                    value={draft.endpoint}
                    placeholder="https://gateway.example.com/moneyhelper"
                    onChange={(event) => setDraft({ ...draft, endpoint: event.target.value })}
                  />
                </Field>
                <Field label={t("external.channelProvider")}>
                  <input
                    className={inputClass}
                    value={draft.provider_name}
                    placeholder="乐企服务商 / 银行开放平台"
                    onChange={(event) => setDraft({ ...draft, provider_name: event.target.value })}
                  />
                </Field>
                <div className="grid grid-cols-[minmax(0,1fr)_120px] gap-2">
                  <Field label={t("external.channelSigningSecret")} hint={t("external.channelSecretKeep")}>
                    <input
                      className={inputClass}
                      type="password"
                      value={draft.signing_secret}
                      autoComplete="new-password"
                      placeholder={t("external.channelSecretPlaceholder")}
                      onChange={(event) => setDraft({ ...draft, signing_secret: event.target.value })}
                    />
                  </Field>
                  <Field label={t("external.channelTimeout")}>
                    <input
                      className={inputClass}
                      value={draft.timeout_sec}
                      inputMode="numeric"
                      onChange={(event) => setDraft({ ...draft, timeout_sec: event.target.value })}
                    />
                  </Field>
                </div>
                <div className="rounded-xl border border-border/45 bg-muted/15 px-3 py-2.5 text-[11px] leading-relaxed text-muted-foreground">
                  {t("external.channelSignatureHint")}
                </div>
              </>
            )}
            <div className="flex items-center justify-between gap-3 rounded-xl border border-border/50 px-3 py-2.5">
              <div>
                <div className="text-[12.5px] font-medium">{t("external.channelEnable")}</div>
                <div className="text-[11px] text-muted-foreground">{t("external.channelEnableHint")}</div>
              </div>
              <Switch checked={draft.enabled} onChange={(value) => setDraft({ ...draft, enabled: value })} />
            </div>
            <div className="flex gap-2 pt-1">
              <Button variant="outline" onClick={closeConfig} className="h-10 flex-1 rounded-xl">
                {t("external.cancel")}
              </Button>
              <Button onClick={submitConfig} disabled={save.isPending} className="h-10 flex-[1.4] rounded-xl">
                {save.isPending ? <RefreshCw className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                {t("external.channelSave")}
              </Button>
            </div>
            {channels.find((item) => channelId(item) === configId)?.configured ? (
              <Button
                variant="ghost"
                onClick={() => {
                  if (configId) {
                    remove.mutate(configId, {
                      onSuccess: () => {
                        closeConfig();
                        setFlash({ tone: "ok", text: t("external.channelDeleted") });
                      },
                      onError: (error: Error) => setFlash({ tone: "danger", text: error.message }),
                    });
                  }
                }}
                disabled={remove.isPending}
                className="h-9 w-full rounded-xl text-[12px] text-muted-foreground hover:text-red-600"
              >
                <Trash2 className="h-3.5 w-3.5" />
                {t("external.channelDelete")}
              </Button>
            ) : null}
          </div>
        ) : null}
      </SidePanel>
    </Card>
  );
}
