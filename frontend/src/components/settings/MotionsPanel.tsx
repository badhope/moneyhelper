/** 家庭议会卡（M6.4）：提案 → 成员投票 → 法定人数/多数决。
 *
 * 只负责表决；通过后不改账本，资金动作仍走既有审批与交易链。
 */

import { useCallback, useEffect, useState } from "react";
import { Gavel, Plus, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { fmtMoney } from "@/lib/format";
import { api } from "@/lib/api";
import { inputCls, labelCls } from "./shared";
import { cn } from "@/lib/utils";

interface MotionTally {
  yes: number;
  no: number;
  abstain: number;
  voted: number;
  members: number;
  quorum_needed: number;
  quorum_met: boolean;
  would_pass: boolean;
}

interface Motion {
  id: string;
  title: string;
  amount: number;
  category: string;
  note: string;
  proposer_id: number | null;
  status: "voting" | "approved" | "rejected" | "withdrawn";
  created_at: string;
  tally: MotionTally;
}

const STATUS_VARIANT: Record<Motion["status"], "outline" | "ok" | "danger" | "muted"> = {
  voting: "outline",
  approved: "ok",
  rejected: "danger",
  withdrawn: "muted",
};

export function MotionsPanel() {
  const { t } = useI18n();
  const { toast } = useToast();
  const [items, setItems] = useState<Motion[]>([]);
  const [loading, setLoading] = useState(true);
  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [members, setMembers] = useState<{ id: number; display_name: string }[]>([]);
  const [activeId, setActiveId] = useState<number>(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [res, ms, me] = await Promise.all([
        api<{ items: Motion[] }>("/api/family/motions"),
        api<{ members: { id: number; display_name: string }[] }>("/api/members"),
        api<{ member: { id: number } | null }>("/api/members/me"),
      ]);
      setItems(res.items ?? []);
      setMembers(ms.members ?? []);
      setActiveId(me.member?.id ?? ms.members?.[0]?.id ?? 0);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async () => {
    if (!title.trim()) {
      toast(t("family.motionTitlePh"), "error");
      return;
    }
    setBusy(true);
    try {
      await api("/api/family/motions", {
        method: "POST",
        body: JSON.stringify({ title: title.trim(), amount: Number(amount) || 0 }),
      });
      setTitle("");
      setAmount("");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const vote = async (motionId: string, memberId: number, v: "yes" | "no" | "abstain") => {
    setBusy(true);
    try {
      await api(`/api/family/motions/${motionId}/votes`, {
        method: "POST",
        body: JSON.stringify({ member_id: memberId, vote: v }),
      });
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-4 rounded-lg border border-border p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-sm font-medium">
          <Gavel className="h-4 w-4 text-muted-foreground" />
          {t("family.motionsTitle")}
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7" aria-label={t("connect.refresh")} onClick={() => void load()}>
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
        </Button>
      </div>
      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{t("family.motionsHint")}</p>

      <div className="mt-2 flex flex-wrap items-end gap-2">
        <label className="min-w-40 flex-1">
          <span className={labelCls}>{t("family.motionTitlePh")}</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} className={inputCls} />
        </label>
        <label className="w-28">
          <span className={labelCls}>{t("family.motionAmountPh")}</span>
          <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" className={inputCls} />
        </label>
        <Button size="sm" disabled={busy} onClick={() => void create()}>
          <Plus className="mr-1 h-3.5 w-3.5" />
          {t("family.createMotion")}
        </Button>
      </div>

      <div className="mt-2 space-y-1.5">
        {items.length === 0 ? (
          <div className="py-2 text-center text-[11px] text-muted-foreground">{t("family.noMotions")}</div>
        ) : (
          items.map((m) => (
            <div key={m.id} className="rounded-md border border-border/70 px-2.5 py-2">
              <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
                <Badge variant={STATUS_VARIANT[m.status]} className="px-1.5 py-0 text-[10px]">
                  {t(`family.motionStatus.${m.status}`)}
                </Badge>
                <span className="font-medium">{m.title}</span>
                {m.amount > 0 ? <span className="tabular-nums text-muted-foreground">{fmtMoney(m.amount)}</span> : null}
              </div>
              <div className="mt-1 text-[10.5px] text-muted-foreground">
                {t("family.tally", {
                  yes: m.tally.yes,
                  no: m.tally.no,
                  abstain: m.tally.abstain,
                  quorum: m.tally.quorum_needed,
                  voted: m.tally.voted,
                })}
              </div>
              {m.status === "voting" ? (
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  <select
                    value={activeId}
                    onChange={(e) => setActiveId(Number(e.target.value))}
                    className="rounded-md border border-border bg-background px-1.5 py-1 text-[11px]"
                    aria-label={t("family.voter")}
                  >
                    {members.map((mm) => (
                      <option key={mm.id} value={mm.id}>
                        {mm.display_name}
                      </option>
                    ))}
                  </select>
                  {(["yes", "no", "abstain"] as const).map((v) => (
                    <Button
                      key={v}
                      size="sm"
                      variant={v === "yes" ? "default" : "outline"}
                      disabled={busy}
                      onClick={() => void vote(m.id, activeId, v)}
                    >
                      {t(v === "yes" ? "family.voteYes" : v === "no" ? "family.voteNo" : "family.voteAbstain")}
                    </Button>
                  ))}
                </div>
              ) : null}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
