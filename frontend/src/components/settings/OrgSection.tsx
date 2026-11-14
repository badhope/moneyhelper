import { useCallback, useEffect, useState } from "react";
import {
  Building2,
  Check,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
  UserPlus,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm";
import {
  addOrgMember,
  createOrgDepartment,
  createOrgPosition,
  deleteOrgDepartment,
  deleteOrgPosition,
  getOrgOverview,
  listOrgTenants,
  removeOrgMember,
  updateOrgDepartment,
  updateOrgMember,
  updateOrgPosition,
  type OrgOverview,
  type OrgTenant,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { Section, inputCls, labelCls } from "./shared";

const ROLE_KEYS: Record<string, string> = {
  owner: "org.roleOwner",
  admin: "org.roleAdmin",
  accountant: "org.roleAccountant",
  approver: "org.roleApprover",
  viewer: "org.roleViewer",
  member: "org.roleMember",
};

const KIND_KEYS: Record<string, string> = {
  local: "org.kindLocal",
  personal: "org.kindPersonal",
  enterprise: "org.kindEnterprise",
};

const miniInput =
  "rounded-lg border border-input bg-background px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-ring";

type ConfirmTarget =
  | { kind: "department"; id: number; label: string }
  | { kind: "position"; id: number; label: string }
  | { kind: "member"; id: number; label: string };

/**
 * 企业组织设置（切片 3）：租户视图切换 + 部门/岗位/成员管理。
 *
 * 切换只作用于组织 API，不改变现有账本归属；页面必须明确说出这一点，
 * 否则用户会以为账本也跟着切了。
 */
export function OrgSection() {
  const { t } = useI18n();
  const { toast } = useToast();
  const [tenants, setTenants] = useState<OrgTenant[]>([]);
  const [tenantId, setTenantId] = useState<number | null>(null);
  const [data, setData] = useState<OrgOverview | null>(null);
  const [loading, setLoading] = useState(true);

  const [deptForm, setDeptForm] = useState({ name: "", code: "", parent_id: "" });
  const [posForm, setPosForm] = useState({
    name: "",
    code: "",
    department_id: "",
    role_hint: "",
  });
  const [memberForm, setMemberForm] = useState({
    user_id: "",
    role: "member",
    department_id: "",
    position_id: "",
  });

  const [editDept, setEditDept] = useState<{
    id: number;
    name: string;
    code: string;
    parent_id: string;
  } | null>(null);
  const [editPos, setEditPos] = useState<{
    id: number;
    name: string;
    code: string;
    department_id: string;
    role_hint: string;
  } | null>(null);
  const [confirm, setConfirm] = useState<ConfirmTarget | null>(null);

  useEffect(() => {
    let alive = true;
    listOrgTenants()
      .then((ts) => {
        if (!alive) return;
        setTenants(ts);
        // 默认落在当前正在工作的租户（切片 7b 全局切换），
        // 否则组织页显示的租户会和顶栏当前租户对不上。
        setTenantId((prev) => {
          if (prev != null) return prev;
          const active = ts.find((x) => x.active);
          return active?.id ?? ts[0]?.id ?? null;
        });
      })
      .catch((e) => toast(e instanceof Error ? e.message : String(e), "error"));
    return () => {
      alive = false;
    };
  }, [toast]);

  const load = useCallback(async () => {
    if (tenantId == null) return;
    setLoading(true);
    try {
      setData(await getOrgOverview(tenantId));
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setLoading(false);
    }
  }, [tenantId, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const selected = tenants.find((x) => x.id === tenantId) ?? null;
  const canWrite = selected?.role === "owner" || selected?.role === "admin";
  const deptName = (id: number | null) =>
    data?.departments.find((d) => d.id === id)?.name ?? t("org.none");
  const posName = (id: number | null) =>
    data?.positions.find((p) => p.id === id)?.name ?? t("org.none");
  const roleLabel = (role: string) => t(ROLE_KEYS[role] ?? "org.roleMember");
  const statusLabel = (status: string) =>
    t(status === "archived" ? "org.statusArchived" : "org.statusActive");

  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
      throw e;
    }
  };

  const submitDept = async () => {
    if (!deptForm.name.trim()) return;
    try {
      await run(() =>
        createOrgDepartment(
          {
            name: deptForm.name,
            code: deptForm.code,
            parent_id: deptForm.parent_id ? Number(deptForm.parent_id) : null,
          },
          tenantId ?? undefined,
        ),
      );
      setDeptForm({ name: "", code: "", parent_id: "" });
      toast(t("org.added"), "ok");
    } catch {
      /* toast already shown */
    }
  };

  const saveDept = async () => {
    if (!editDept) return;
    try {
      await run(() =>
        updateOrgDepartment(
          editDept.id,
          {
            name: editDept.name,
            code: editDept.code,
            parent_id: editDept.parent_id ? Number(editDept.parent_id) : null,
          },
          tenantId ?? undefined,
        ),
      );
      setEditDept(null);
      toast(t("org.updated"), "ok");
    } catch {
      /* toast already shown */
    }
  };

  const submitPos = async () => {
    if (!posForm.name.trim()) return;
    try {
      await run(() =>
        createOrgPosition(
          {
            name: posForm.name,
            code: posForm.code,
            department_id: posForm.department_id
              ? Number(posForm.department_id)
              : null,
            role_hint: posForm.role_hint,
          },
          tenantId ?? undefined,
        ),
      );
      setPosForm({ name: "", code: "", department_id: "", role_hint: "" });
      toast(t("org.added"), "ok");
    } catch {
      /* toast already shown */
    }
  };

  const savePos = async () => {
    if (!editPos) return;
    try {
      await run(() =>
        updateOrgPosition(
          editPos.id,
          {
            name: editPos.name,
            code: editPos.code,
            department_id: editPos.department_id
              ? Number(editPos.department_id)
              : null,
            role_hint: editPos.role_hint,
          },
          tenantId ?? undefined,
        ),
      );
      setEditPos(null);
      toast(t("org.updated"), "ok");
    } catch {
      /* toast already shown */
    }
  };

  const submitMember = async () => {
    if (!memberForm.user_id.trim()) return;
    try {
      await run(() =>
        addOrgMember(
          {
            user_id: Number(memberForm.user_id),
            role: memberForm.role,
            department_id: memberForm.department_id
              ? Number(memberForm.department_id)
              : null,
            position_id: memberForm.position_id
              ? Number(memberForm.position_id)
              : null,
          },
          tenantId ?? undefined,
        ),
      );
      setMemberForm({
        user_id: "",
        role: "member",
        department_id: "",
        position_id: "",
      });
      toast(t("org.added"), "ok");
    } catch {
      /* toast already shown */
    }
  };

  const remove = async () => {
    const target = confirm;
    setConfirm(null);
    if (!target) return;
    try {
      await run(async () => {
        if (target.kind === "department") {
          await deleteOrgDepartment(target.id, tenantId ?? undefined);
        } else if (target.kind === "position") {
          await deleteOrgPosition(target.id, tenantId ?? undefined);
        } else {
          await removeOrgMember(target.id, tenantId ?? undefined);
        }
      });
      toast(t("org.deleted"), "ok");
    } catch {
      /* toast already shown */
    }
  };

  return (
    <div className="space-y-3">
      <Section
        title={t("settings.navOrg")}
        icon={<Building2 className="w-4 h-4 text-muted-foreground" />}
        desc={t("org.desc")}
      >
        <div className="flex flex-col gap-2 @sm:flex-row @sm:items-end @sm:justify-between">
          <div className="min-w-0 flex-1">
            <label className={labelCls} htmlFor="orgsection-1">{t("org.tenant")}</label>
            <select id="orgsection-1"
              className={inputCls}
              value={tenantId ?? ""}
              onChange={(e) => setTenantId(e.target.value ? Number(e.target.value) : null)}
              disabled={tenants.length <= 1}
            >
              {tenants.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                  {x.kind !== "local"
                    ? ` · ${t(KIND_KEYS[x.kind] ?? "org.kindPersonal")}`
                    : ""}
                  {" · "}
                  {roleLabel(x.role ?? "member")}
                </option>
              ))}
            </select>
          </div>
          <div className="text-xs text-muted-foreground @sm:text-right">
            <div>
              {t("org.counts")
                .replaceAll("{d}", String(data?.counts.departments ?? 0))
                .replaceAll("{p}", String(data?.counts.positions ?? 0))
                .replaceAll("{m}", String(data?.counts.members ?? 0))}
            </div>
            {loading ? <div>{t("settings.loading")}</div> : null}
          </div>
        </div>
        <div className="mt-2 flex items-start gap-2 text-[11.5px] text-muted-foreground">
          <span>{t("org.switchHint")}</span>
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto h-7 shrink-0 px-2"
            onClick={() => void load()}
            disabled={loading}
          >
            <RefreshCw className={cn("mr-1 h-3.5 w-3.5", loading && "animate-spin")} />
            {t("settings.refresh")}
          </Button>
        </div>
        {!canWrite && selected ? (
          <div className="mt-2 rounded-lg border border-border/70 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            {t("org.readonly")}
          </div>
        ) : null}
      </Section>

      <Section title={`${t("org.departments")} (${data?.counts.departments ?? 0})`}>
        {canWrite ? (
          <div className="mb-3 flex flex-wrap items-end gap-2">
            <div className="w-40">
              <label className={labelCls} htmlFor="orgsection-2">{t("org.name")}</label>
              <input id="orgsection-2"
                className={inputCls}
                value={deptForm.name}
                onChange={(e) => setDeptForm({ ...deptForm, name: e.target.value })}
                placeholder={t("org.name")}
              />
            </div>
            <div className="w-24">
              <label className={labelCls} htmlFor="orgsection-3">{t("org.code")}</label>
              <input id="orgsection-3"
                className={inputCls}
                value={deptForm.code}
                onChange={(e) => setDeptForm({ ...deptForm, code: e.target.value })}
                placeholder={t("org.code")}
              />
            </div>
            <div className="w-36">
              <label className={labelCls} htmlFor="orgsection-4">{t("org.parent")}</label>
              <select id="orgsection-4"
                className={inputCls}
                value={deptForm.parent_id}
                onChange={(e) => setDeptForm({ ...deptForm, parent_id: e.target.value })}
              >
                <option value="">{t("org.none")}</option>
                {data?.departments.map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </div>
            <Button size="sm" onClick={() => void submitDept()}>
              <Plus className="mr-1 h-3.5 w-3.5" />
              {t("org.addDepartment")}
            </Button>
          </div>
        ) : null}
        {data?.departments.length ? (
          <div className="space-y-2">
            {data.departments.map((d) => (
              <div key={d.id} className="rounded-lg border border-border/70 px-3 py-2">
                {editDept?.id === d.id ? (
                  <div className="flex flex-wrap items-end gap-2">
                    <input
                      className={miniInput}
                      value={editDept.name}
                      onChange={(e) => setEditDept({ ...editDept, name: e.target.value })}
                    />
                    <input
                      className={miniInput}
                      value={editDept.code}
                      onChange={(e) => setEditDept({ ...editDept, code: e.target.value })}
                      placeholder={t("org.code")}
                    />
                    <select
                      className={miniInput}
                      value={editDept.parent_id}
                      onChange={(e) => setEditDept({ ...editDept, parent_id: e.target.value })}
                    >
                      <option value="">{t("org.none")}</option>
                      {data.departments
                        .filter((x) => x.id !== d.id)
                        .map((x) => (
                          <option key={x.id} value={x.id}>{x.name}</option>
                        ))}
                    </select>
                    <Button size="sm" onClick={() => void saveDept()}>
                      <Check className="h-3.5 w-3.5" />
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setEditDept(null)}>
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ) : (
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-sm font-medium">{d.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {d.code || t("org.none")} · {deptName(d.parent_id)} · {statusLabel(d.status)}
                      </div>
                    </div>
                    {canWrite ? (
                      <div className="flex gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() =>
                            setEditDept({
                              id: d.id,
                              name: d.name,
                              code: d.code,
                              parent_id: d.parent_id ? String(d.parent_id) : "",
                            })
                          }
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() =>
                            setConfirm({ kind: "department", id: d.id, label: d.name })
                          }
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    ) : null}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="py-2 text-xs text-muted-foreground">{t("org.emptyDepartments")}</div>
        )}
      </Section>

      <Section title={`${t("org.positions")} (${data?.counts.positions ?? 0})`}>
        {canWrite ? (
          <div className="mb-3 flex flex-wrap items-end gap-2">
            <div className="w-40">
              <label className={labelCls} htmlFor="orgsection-5">{t("org.name")}</label>
              <input id="orgsection-5"
                className={inputCls}
                value={posForm.name}
                onChange={(e) => setPosForm({ ...posForm, name: e.target.value })}
                placeholder={t("org.name")}
              />
            </div>
            <div className="w-40">
              <label className={labelCls} htmlFor="orgsection-6">{t("org.department")}</label>
              <select id="orgsection-6"
                className={inputCls}
                value={posForm.department_id}
                onChange={(e) =>
                  setPosForm({ ...posForm, department_id: e.target.value })
                }
              >
                <option value="">{t("org.none")}</option>
                {data?.departments.map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </div>
            <div className="w-28">
              <label className={labelCls} htmlFor="orgsection-7">{t("org.roleHint")}</label>
              <input id="orgsection-7"
                className={inputCls}
                value={posForm.role_hint}
                onChange={(e) => setPosForm({ ...posForm, role_hint: e.target.value })}
                placeholder="accountant"
              />
            </div>
            <Button size="sm" onClick={() => void submitPos()}>
              <Plus className="mr-1 h-3.5 w-3.5" />
              {t("org.addPosition")}
            </Button>
          </div>
        ) : null}
        {data?.positions.length ? (
          <div className="space-y-2">
            {data.positions.map((p) => (
              <div key={p.id} className="rounded-lg border border-border/70 px-3 py-2">
                {editPos?.id === p.id ? (
                  <div className="flex flex-wrap items-end gap-2">
                    <input
                      className={miniInput}
                      value={editPos.name}
                      onChange={(e) => setEditPos({ ...editPos, name: e.target.value })}
                    />
                    <select
                      className={miniInput}
                      value={editPos.department_id}
                      onChange={(e) =>
                        setEditPos({ ...editPos, department_id: e.target.value })
                      }
                    >
                      <option value="">{t("org.none")}</option>
                      {data.departments.map((d) => (
                        <option key={d.id} value={d.id}>{d.name}</option>
                      ))}
                    </select>
                    <input
                      className={miniInput}
                      value={editPos.role_hint}
                      onChange={(e) =>
                        setEditPos({ ...editPos, role_hint: e.target.value })
                      }
                      placeholder={t("org.roleHint")}
                    />
                    <Button size="sm" onClick={() => void savePos()}>
                      <Check className="h-3.5 w-3.5" />
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setEditPos(null)}>
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ) : (
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-sm font-medium">{p.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {deptName(p.department_id)} · {p.role_hint || t("org.none")} · {statusLabel(p.status)}
                      </div>
                    </div>
                    {canWrite ? (
                      <div className="flex gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() =>
                            setEditPos({
                              id: p.id,
                              name: p.name,
                              code: p.code,
                              department_id: p.department_id
                                ? String(p.department_id)
                                : "",
                              role_hint: p.role_hint,
                            })
                          }
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() =>
                            setConfirm({ kind: "position", id: p.id, label: p.name })
                          }
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    ) : null}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="py-2 text-xs text-muted-foreground">{t("org.emptyPositions")}</div>
        )}
      </Section>

      <Section title={`${t("org.members")} (${data?.counts.members ?? 0})`}>
        {canWrite ? (
          <div className="mb-3 flex flex-wrap items-end gap-2">
            <div className="w-28">
              <label className={labelCls} htmlFor="orgsection-8">{t("org.userId")}</label>
              <input id="orgsection-8"
                className={inputCls}
                inputMode="numeric"
                value={memberForm.user_id}
                onChange={(e) =>
                  setMemberForm({ ...memberForm, user_id: e.target.value })
                }
                placeholder="1"
              />
            </div>
            <div className="w-32">
              <label className={labelCls} htmlFor="orgsection-9">{t("org.role")}</label>
              <select id="orgsection-9"
                className={inputCls}
                value={memberForm.role}
                onChange={(e) => setMemberForm({ ...memberForm, role: e.target.value })}
              >
                {Object.entries(ROLE_KEYS)
                  .filter(([value]) => value !== "owner")
                  .map(([value, key]) => (
                    <option key={value} value={value}>{t(key)}</option>
                  ))}
              </select>
            </div>
            <div className="w-36">
              <label className={labelCls} htmlFor="orgsection-10">{t("org.department")}</label>
              <select id="orgsection-10"
                className={inputCls}
                value={memberForm.department_id}
                onChange={(e) =>
                  setMemberForm({ ...memberForm, department_id: e.target.value })
                }
              >
                <option value="">{t("org.none")}</option>
                {data?.departments.map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </div>
            <div className="w-36">
              <label className={labelCls} htmlFor="orgsection-11">{t("org.position")}</label>
              <select id="orgsection-11"
                className={inputCls}
                value={memberForm.position_id}
                onChange={(e) =>
                  setMemberForm({ ...memberForm, position_id: e.target.value })
                }
              >
                <option value="">{t("org.none")}</option>
                {data?.positions.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
            <Button size="sm" onClick={() => void submitMember()}>
              <UserPlus className="mr-1 h-3.5 w-3.5" />
              {t("org.addMember")}
            </Button>
          </div>
        ) : null}
        {canWrite ? (
          <div className="mb-2 text-[11.5px] text-muted-foreground">{t("org.userIdHint")}</div>
        ) : null}
        {data?.members.length ? (
          <div className="space-y-2">
            {data.members.map((m) => (
              <div
                key={m.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/70 px-3 py-2"
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium">
                    {m.display_name || m.username || `#${m.user_id}`}
                    <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                      @{m.username || m.user_id} · #{m.user_id}
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {deptName(m.department_id)} · {posName(m.position_id)} · {statusLabel(m.status)}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {m.role === "owner" ? (
                    <span className="rounded-full border border-border px-2 py-0.5 text-xs">
                      {roleLabel(m.role)}
                    </span>
                  ) : (
                    <select
                      className={miniInput}
                      value={m.role}
                      disabled={!canWrite}
                      onChange={(e) => {
                        void updateOrgMember(
                          m.user_id,
                          { role: e.target.value },
                          tenantId ?? undefined,
                        )
                          .then(load)
                          .then(() => toast(t("org.updated"), "ok"))
                          .catch((e) =>
                            toast(e instanceof Error ? e.message : String(e), "error"),
                          );
                      }}
                    >
                      {Object.entries(ROLE_KEYS)
                        .filter(([value]) => value !== "owner")
                        .map(([value, key]) => (
                          <option key={value} value={value}>{t(key)}</option>
                        ))}
                    </select>
                  )}
                  {canWrite && m.role !== "owner" ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        setConfirm({
                          kind: "member",
                          id: m.user_id,
                          label: m.display_name || m.username || `#${m.user_id}`,
                        })
                      }
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="py-2 text-xs text-muted-foreground">{t("org.emptyMembers")}</div>
        )}
      </Section>

      <ConfirmDialog
        open={!!confirm}
        onOpenChange={(open) => {
          if (!open) setConfirm(null);
        }}
        title={t("org.confirmDelete")}
        description={confirm?.label}
        danger
        onConfirm={() => void remove()}
      />
    </div>
  );
}
