import { useCallback, useEffect, useState } from "react";
import { Building2, Check, ChevronDown, Loader2 } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import {
  getActiveTenant,
  listOrgTenants,
  switchActiveTenant,
  type OrgTenant,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * 全局租户切换（切片 7b）。
 *
 * 解决的老问题：个人租户优先的兼容映射让"既是员工又是企业成员"的人
 * 永远落不进企业租户，组织/总账/报销/付款/对账全部只能看到个人那一份。
 *
 * 边界（必须在 UI 上说清楚，不能让用户误判数据范围）：
 * - 切换只作用于**企业域**：组织、总账、报销、付款、银行对账；
 * - 个人流水（记账、总览、持仓、负债）仍按登录用户归属，不随切换改变；
 * - 切不动的时候（只有一个租户）直接不渲染，不占顶栏空间。
 */
export function TenantSwitcher({ onChanged }: { onChanged?: () => void }) {
  const { t } = useI18n();
  const { toast } = useToast();
  const [tenants, setTenants] = useState<OrgTenant[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const list = await listOrgTenants();
      setTenants(list);
      const info = await getActiveTenant();
      setActiveId(info.active_tenant_id ?? null);
    } catch {
      // 未登录 / 无账号体系 / 后端不可用：静默隐藏切换器，不打断主流程
      setTenants([]);
      setActiveId(null);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const onSelect = useCallback(
    async (tenantId: number) => {
      if (tenantId === activeId) return;
      setBusy(true);
      try {
        const res = await switchActiveTenant(tenantId);
        setActiveId(res.active_tenant_id ?? tenantId);
        if (res.tenants) setTenants(res.tenants);
        toast(t("tenant.switched"), "ok");
        onChanged?.();
      } catch (e) {
        toast(e instanceof Error ? e.message : t("tenant.switchFailed"), "error");
      } finally {
        setBusy(false);
      }
    },
    [activeId, onChanged, t, toast],
  );

  // 只有一个租户就没有"切换"这回事，不渲染
  if (!loaded || tenants.length <= 1) return null;

  const active = tenants.find((x) => x.id === activeId) ?? tenants[0];

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <label className="relative hidden min-w-0 items-center gap-1 rounded-lg px-2 py-1.5 text-sm text-foreground/80 transition-colors hover:bg-accent md:inline-flex">
          <Building2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="max-w-[11rem] truncate">{active?.name ?? t("tenant.label")}</span>
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          )}
          <select
            value={activeId ?? ""}
            onChange={(e) => void onSelect(Number(e.target.value))}
            disabled={busy}
            aria-label={t("tenant.label")}
            data-testid="tenant-switcher"
            title={t("tenant.scopeHint")}
            className="absolute inset-0 cursor-pointer opacity-0"
          >
            {tenants.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name}
              </option>
            ))}
          </select>
        </label>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">
        <div className="space-y-1">
          <div className="font-medium">{t("tenant.label")}</div>
          <div className="text-muted-foreground">{t("tenant.scopeHint")}</div>
          <ul className="space-y-0.5">
            {tenants.map((x) => (
              <li key={x.id} className="flex items-center gap-1.5">
                {x.id === activeId ? (
                  <Check className="h-3 w-3 shrink-0" />
                ) : (
                  <span className="w-3 shrink-0" />
                )}
                <span className={cn(x.id === activeId && "font-medium")}>{x.name}</span>
              </li>
            ))}
          </ul>
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
