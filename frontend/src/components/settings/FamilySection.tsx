import { useCallback, useEffect, useState } from "react";
import { HandCoins, Plus, RefreshCw, Trash2, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  addMember,
  createMemberLoan,
  deleteMember,
  deleteMemberLoan,
  familySummary,
  listMemberLoans,
  listMembers,
  settleMemberLoan,
  type FamilyMember,
  type FamilySummary,
  type MemberLoan,
} from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { fmtMoney } from "@/lib/format";
import { Section, inputCls, labelCls } from "./shared";
import { MotionsPanel } from "./MotionsPanel";
import { cn } from "@/lib/utils";

const ROLES: { value: FamilyMember["role"]; key: string }[] = [
  { value: "owner", key: "family.roleOwner" },
  { value: "admin", key: "family.roleAdmin" },
  { value: "member", key: "family.roleMember" },
  { value: "viewer", key: "family.roleViewer" },
];

/**
 * 家庭账本：成员管理 + 成员间借贷 + 家庭汇总。
 *
 * 后端这套能力（成员 CRUD、借贷、汇总）一直完整存在，但界面上没有任何入口，
 * 用户只能通过 API 使用。这里按"一览 → 操作"的顺序组织：
 * 先看家庭合计与各成员占比，再管成员和借贷，避免一上来就是表单。
 */
export function FamilySection() {
  const { t } = useI18n();
  const { toast } = useToast();
  const [members, setMembers] = useState<FamilyMember[]>([]);
  const [loans, setLoans] = useState<MemberLoan[]>([]);
  const [summary, setSummary] = useState<FamilySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [role, setRole] = useState<FamilyMember["role"]>("member");
  const [loan, setLoan] = useState({ from: "", to: "", amount: "", note: "" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ms, ls, sm] = await Promise.all([
        listMembers(),
        listMemberLoans(),
        familySummary(),
      ]);
      setMembers(ms);
      setLoans(ls);
      setSummary(sm);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const doAdd = async () => {
    const display = name.trim();
    if (!display) return;
    try {
      await addMember({ display_name: display, role });
      setName("");
      toast(t("family.added"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doDelete = async (id: number) => {
    try {
      await deleteMember(id);
      toast(t("family.removed"), "ok");
      await load();
    } catch (e) {
      // 有流水的成员被删时会先置空归属再删，真失败通常是权限/外键
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doLoan = async () => {
    const from = Number(loan.from);
    const to = Number(loan.to);
    const amount = Number(loan.amount);
    if (!from || !to || from === to || !(amount > 0)) {
      toast(t("family.loanInvalid"), "error");
      return;
    }
    try {
      await createMemberLoan({ from_member_id: from, to_member_id: to, amount, note: loan.note });
      setLoan({ from: "", to: "", amount: "", note: "" });
      toast(t("family.loanAdded"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const pending = loans.filter((l) => !l.settled);

  return (
    <Section
      title={t("family.title")}
      icon={<Users className="w-4 h-4 text-muted-foreground" />}
      desc={t("family.desc")}
    >
      {/* 家庭汇总：先给结论，再给明细 */}
      {summary && members.length > 0 && (
        <div className="@container mb-3 grid gap-2 rounded-lg border border-border p-2.5 sm:grid-cols-3">
          <div>
            <div className="text-[11px] text-muted-foreground">{t("family.householdIncome")}</div>
            <div className="text-sm font-semibold tabular-nums">
              {fmtMoney(summary.household_income, false, true)}
            </div>
          </div>
          <div>
            <div className="text-[11px] text-muted-foreground">{t("family.householdExpense")}</div>
            <div className="text-sm font-semibold tabular-nums">
              {fmtMoney(summary.household_expense, false, true)}
            </div>
          </div>
          <div>
            <div className="text-[11px] text-muted-foreground">{t("family.householdNet")}</div>
            <div
              className={cn(
                "text-sm font-semibold tabular-nums",
                summary.household_net >= 0 ? "text-success" : "text-red-500",
              )}
            >
              {fmtMoney(summary.household_net, true, true)}
            </div>
          </div>
        </div>
      )}

      {/* 成员列表 */}
      {members.length === 0 ? (
        <p className="py-3 text-xs text-muted-foreground">{t("family.empty")}</p>
      ) : (
        <ul className="mb-3 divide-y divide-border rounded-lg border border-border">
          {members.map((m) => {
            const stat = summary?.members.find((x) => x.id === m.id);
            return (
              <li key={m.id} className="flex items-center gap-2 px-2.5 py-2">
                <span
                  className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-[11px] font-medium text-white"
                  style={{ backgroundColor: m.avatar_color || "#b8891f" }}
                  aria-hidden
                >
                  {m.display_name.slice(0, 1)}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm">{m.display_name}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {t(`family.role${m.role[0].toUpperCase()}${m.role.slice(1)}`)}
                    {stat ? ` · ${t("family.txCount", { n: stat.transaction_count })}` : ""}
                  </div>
                </div>
                {stat && (
                  <div className="shrink-0 text-right text-[11px] tabular-nums text-muted-foreground">
                    <div>{fmtMoney(stat.expense, false, true)} {t("family.expenseShort")}</div>
                    <div>{stat.pct}%</div>
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => void doDelete(m.id)}
                  aria-label={t("family.remove")}
                  className="shrink-0 rounded p-1.5 text-muted-foreground hover:bg-accent hover:text-red-500"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {/* 添加成员 */}
      <div className="@container flex flex-wrap items-end gap-2">
        <div className="min-w-[120px] flex-1">
          <label className={labelCls} htmlFor="familysect-1">{t("family.name")}</label>
          <input id="familysect-1"
            className={inputCls}
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void doAdd()}
            placeholder={t("family.namePh")}
          />
        </div>
        <div className="min-w-[100px]">
          <label className={labelCls} htmlFor="familysect-2">{t("family.role")}</label>
          <select id="familysect-2"
            className={inputCls}
            value={role}
            onChange={(e) => setRole(e.target.value as FamilyMember["role"])}
          >
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {t(r.key)}
              </option>
            ))}
          </select>
        </div>
        <Button size="sm" onClick={() => void doAdd()} disabled={!name.trim()}>
          <Plus className="mr-1 h-3.5 w-3.5" />
          {t("family.add")}
        </Button>
        <Button size="sm" variant="outline" onClick={() => void load()} disabled={loading}>
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
        </Button>
      </div>

      {/* 成员间借贷 */}
      {members.length >= 2 && (
        <div className="mt-4">
          <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-medium">
            <HandCoins className="h-3.5 w-3.5 text-muted-foreground" />
            {t("family.loans")}
            {pending.length > 0 && (
              <span className="rounded-full bg-amber-100 px-1.5 text-[10px] text-amber-700">
                {t("family.pendingCount", { n: pending.length })}
              </span>
            )}
          </h3>

          {loans.length === 0 ? (
            <p className="text-[11px] text-muted-foreground">{t("family.noLoans")}</p>
          ) : (
            <ul className="mb-2 divide-y divide-border rounded-lg border border-border">
              {loans.map((l) => (
                <li key={l.id} className="flex items-center gap-2 px-2.5 py-1.5 text-xs">
                  <span className="min-w-0 flex-1 truncate">
                    {l.from_name || `#${l.from_member_id}`} → {l.to_name || `#${l.to_member_id}`}
                    {l.note ? ` · ${l.note}` : ""}
                  </span>
                  <span className="shrink-0 tabular-nums">{fmtMoney(l.amount, false, true)}</span>
                  {l.settled ? (
                    <span className="shrink-0 text-[10px] text-muted-foreground">
                      {t("family.settled")}
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() =>
                        void settleMemberLoan(l.id).then(load).catch((e) => toast(String(e), "error"))
                      }
                      className="shrink-0 rounded border border-border px-1.5 py-0.5 text-[10px] hover:bg-accent"
                    >
                      {t("family.settle")}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() =>
                      void deleteMemberLoan(l.id).then(load).catch((e) => toast(String(e), "error"))
                    }
                    aria-label={t("family.deleteLoan")}
                    className="shrink-0 rounded p-1 text-muted-foreground hover:text-red-500"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="@container flex flex-wrap items-end gap-2">
            <div className="min-w-[90px]">
              <label className={labelCls} htmlFor="familysect-3">{t("family.from")}</label>
              <select id="familysect-3"
                className={inputCls}
                value={loan.from}
                onChange={(e) => setLoan((v) => ({ ...v, from: e.target.value }))}
              >
                <option value="">—</option>
                {members.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name}
                  </option>
                ))}
              </select>
            </div>
            <div className="min-w-[90px]">
              <label className={labelCls} htmlFor="familysect-4">{t("family.to")}</label>
              <select id="familysect-4"
                className={inputCls}
                value={loan.to}
                onChange={(e) => setLoan((v) => ({ ...v, to: e.target.value }))}
              >
                <option value="">—</option>
                {members.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name}
                  </option>
                ))}
              </select>
            </div>
            <div className="min-w-[90px]">
              <label className={labelCls} htmlFor="familysect-5">{t("family.amount")}</label>
              <input id="familysect-5"
                className={inputCls}
                type="number"
                min="0"
                value={loan.amount}
                onChange={(e) => setLoan((v) => ({ ...v, amount: e.target.value }))}
              />
            </div>
            <div className="min-w-[110px] flex-1">
              <label className={labelCls} htmlFor="familysect-6">{t("family.note")}</label>
              <input id="familysect-6"
                className={inputCls}
                value={loan.note}
                onChange={(e) => setLoan((v) => ({ ...v, note: e.target.value }))}
                placeholder={t("family.notePh")}
              />
            </div>
            <Button size="sm" variant="outline" onClick={() => void doLoan()}>
              <Plus className="mr-1 h-3.5 w-3.5" />
              {t("family.addLoan")}
            </Button>
          </div>
        </div>
      )}
          <MotionsPanel />
    </Section>
  );
}
