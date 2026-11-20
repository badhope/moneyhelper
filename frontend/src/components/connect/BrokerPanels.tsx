/** 连接中心深化面板 · 券商：执行状态、重新分类、券商配置。 */

/** 连接中心深化面板（v4.5）：市场温度 / 个股档案 / 预交易检查 / 风控参数 / 条件单 / 发票 / 券商对账。
 *
 * 拆成独立文件：ConnectPage 已 900+ 行，继续内联会让单文件失控；这些面板都只依赖
 * use-connect 的 hooks，彼此独立，按需渲染。
 */

import { useState } from "react";

import { Loader2, ShieldCheck } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";

import { useI18n } from "@/lib/i18n";

import { useToast } from "@/lib/toast";
import { cn, errMsg } from "@/lib/utils";
import { useApplyCategorize, useExecuteStatus, useConfigureBroker } from "@/lib/use-connect";


/** 券商执行状态（v4.6）：护栏与适配器可用性，不提供下单按钮 */
export function ExecuteStatusCard() {
  const { t } = useI18n();
  const q = useExecuteStatus();
  const d = q.data;
  if (q.isPending) {
    return (
      <Card className="p-[var(--card-pad)]">
        <Skeleton className="h-24 w-full" />
      </Card>
    );
  }
  if (!d) {
    return (
      <Card className="p-[var(--card-pad)]">
        <EmptyState mode="compact" text={t("connect.noData")} />
      </Card>
    );
  }
  return (
    <Card className="min-w-0 p-[var(--card-pad)]">
      <div className="flex items-center gap-1.5 text-[13px] font-semibold">
        <ShieldCheck className="h-4 w-4 text-primary" />
        {t("connect.execTitle")}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        <Badge variant={d.guardrails.trading_enabled ? "warn" : "ok"} className="px-1.5 py-0 text-[10px]">
          {d.guardrails.trading_enabled ? t("connect.execOn") : t("connect.execOff")}
        </Badge>
        <Badge variant={d.guardrails.dry_run ? "ok" : "danger"} className="px-1.5 py-0 text-[10px]">
          {d.guardrails.dry_run ? "dry-run" : t("connect.execLive")}
        </Badge>
        <span className="text-[10.5px] text-muted-foreground">
          {t("connect.execBroker")}: {d.guardrails.broker}
        </span>
      </div>
      <div className="mt-2 space-y-1">
        {d.adapters.map((a) => (
          <div key={a.id} className="flex items-start gap-1.5 text-[11px]">
            <span
              className={cn(
                "mt-1 h-1.5 w-1.5 shrink-0 rounded-full",
                a.available ? "bg-emerald-500" : "bg-muted-foreground/40",
              )}
            />
            <span className="min-w-0">
              <span className="font-medium">{a.id}</span>
              {a.supports_trading ? (
                <span className="ml-1 text-amber-600 dark:text-amber-400">{t("connect.execReal")}</span>
              ) : null}
              <span className="block text-[10px] leading-snug text-muted-foreground">{a.note}</span>
            </span>
          </div>
        ))}
      </div>
      <p className="mt-1.5 border-t border-border/60 pt-1.5 text-[10px] leading-relaxed text-muted-foreground">
        {d.note}
      </p>
    </Card>
  );
}

/** 一键重新归类（v4.6） */
export function RecategorizeCard() {
  const { t } = useI18n();
  const { toast } = useToast();
  const apply = useApplyCategorize();
  return (
    <Card className="p-[var(--card-pad)]">
      <div className="text-[13px] font-semibold">{t("connect.recatTitle")}</div>
      <p className="mt-1 text-[10.5px] leading-relaxed text-muted-foreground">{t("connect.recatHint")}</p>
      <Button
        size="sm"
        className="mt-2 w-full"
        disabled={apply.isPending}
        onClick={() =>
          void apply
            .mutateAsync()
            .then((r) => toast(t("connect.recatDone", { n: r.changed, t: r.total }), r.changed ? "ok" : "info"))
            .catch((e) => toast(String(e), "error"))
        }
      >
        {apply.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
        {t("connect.recatRun")}
      </Button>
    </Card>
  );
}


/** 真券商配置卡（v4.7）：填 API 凭据 → vault 加密保存 → probe/connect。
 *
 * 不把秘密写入 localStorage、React Query 缓存或日志；表单只在内存里存在，
 * 保存后后端只返回 configured=true，不回显值。
 */
export function BrokerConfigCard() {
  const { t } = useI18n();
  const { toast } = useToast();
  const status = useExecuteStatus();
  const configure = useConfigureBroker();
  const [broker, setBroker] = useState("futu");
  const [form, setForm] = useState<Record<string, string>>({});
  const [label, setLabel] = useState("");

  const fields: Record<string, { key: string; label: string; secret?: boolean; placeholder: string }[]> = {
    futu: [
      { key: "host", label: "OpenD Host", placeholder: "127.0.0.1" },
      { key: "port", label: "OpenD Port", placeholder: "11111" },
      { key: "account_id", label: "Account ID", placeholder: "数字账户 ID" },
      { key: "market", label: "Trade Market", placeholder: "HK / US / CN" },
      { key: "security_firm", label: "Security Firm", placeholder: "FUTUSECURITIES（可选）" },
    ],
    longport: [
      { key: "app_key", label: "App Key", secret: true, placeholder: "从长桥 OpenAPI 控制台复制" },
      { key: "app_secret", label: "App Secret", secret: true, placeholder: "不会回显" },
      { key: "access_token", label: "Access Token", secret: true, placeholder: "不会回显" },
    ],
    tiger: [
      { key: "tiger_id", label: "Tiger ID", secret: true, placeholder: "开发者 ID" },
      { key: "private_key", label: "Private Key", secret: true, placeholder: "PEM 私钥内容/路径" },
      { key: "account", label: "Account", placeholder: "交易账户" },
      { key: "license", label: "License", secret: true, placeholder: "可选" },
    ],
    ibkr: [
      { key: "host", label: "TWS Host", placeholder: "127.0.0.1" },
      { key: "port", label: "TWS Port", placeholder: "7497" },
      { key: "client_id", label: "Client ID", placeholder: "31" },
    ],
    xtquant: [
      { key: "path", label: "QMT userdata_mini", placeholder: "D:\\QMT\\userdata_mini" },
      { key: "account_id", label: "Account ID", secret: true, placeholder: "资金账号" },
    ],
    easytrader: [
      { key: "exe_path", label: "Client exe", placeholder: "C:\\...\\xiadan.exe" },
      { key: "account", label: "Account", secret: true, placeholder: "资金账号" },
      { key: "password", label: "Password", secret: true, placeholder: "只写入 vault" },
    ],
  };
  const current = status.data?.adapters.find((a) => a.id === broker);
  const configured = current?.configured;

  const save = async () => {
    const secret: Record<string, string> = {};
    for (const field of fields[broker] ?? []) {
      if (form[field.key]?.trim()) secret[field.key] = form[field.key].trim();
    }
    if (!Object.keys(secret).length) {
      toast(t("connect.brokerFill"), "error");
      return;
    }
    try {
      await configure.mutateAsync({ name: broker, secret, label: label || broker, enabled: false });
      setForm({});
      toast(t("connect.brokerSaved"), "ok");
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  return (
    <Card className="min-w-0 p-[var(--card-pad)]">
      <div className="flex items-center gap-1.5 text-[13px] font-semibold">
        <ShieldCheck className="h-4 w-4 text-primary" />
        {t("connect.brokerConfigTitle")}
      </div>
      <p className="mt-1 text-[10.5px] leading-relaxed text-muted-foreground">{t("connect.brokerConfigHint")}</p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {(["futu", "longport", "tiger", "ibkr", "xtquant", "easytrader"] as const).map((name) => {
          const a = status.data?.adapters.find((x) => x.id === name);
          return (
            <button
              key={name}
              type="button"
              onClick={() => { setBroker(name); setForm({}); }}
              className={cn(
                "rounded-md border px-2 py-1 text-[11px] transition-colors",
                broker === name ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {name}
              {a?.configured ? <span className="ml-1 text-emerald-600">●</span> : null}
            </button>
          );
        })}
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={t("connect.brokerLabelPh")} className="rounded-md border border-border bg-background px-2 py-1.5 text-[12px] sm:col-span-2" />
        {(fields[broker] ?? []).map((field) => (
          <input
            key={field.key}
            type={field.secret ? "password" : "text"}
            value={form[field.key] ?? ""}
            onChange={(e) => setForm({ ...form, [field.key]: e.target.value })}
            placeholder={`${field.label} · ${field.placeholder}`}
            className="rounded-md border border-border bg-background px-2 py-1.5 text-[12px]"
          />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button size="sm" disabled={configure.isPending} onClick={() => void save()}>
          {configure.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
          {t("connect.brokerSave")}
        </Button>
        <Badge variant={configured ? "ok" : "muted"} className="px-1.5 py-0 text-[10px]">
          {configured ? t("connect.brokerConfigured") : t("connect.brokerNotConfigured")}
        </Badge>
        {current?.note ? <span className="text-[10.5px] text-muted-foreground">{current.note}</span> : null}
      </div>
      <p className="mt-2 border-t border-border/60 pt-2 text-[10px] leading-relaxed text-muted-foreground">{t("connect.brokerSafety")}</p>
    </Card>
  );
}
