import { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";
import { api } from "@/lib/api";
import { useMutate } from "@/lib/use-mutate";
import { FieldError } from "@/components/ui/field-error";
import type { Position } from "@/lib/types";

const inputCls =
  "w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring";
const labelCls = "block text-xs text-muted-foreground mb-1";

/** 编辑持仓弹窗：可改 名称 / 类型 / 行业 / 股数 / 成本 / 现价 / 费用，提交 PUT /api/positions/:symbol。 */
export function PositionEditDialog({
  position,
  open,
  onOpenChange,
  onDone,
}: {
  position: Position | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDone: () => void;
}) {
  const { t } = useI18n();
  const [f, setF] = useState({
    name: "",
    kind: "股票",
    industry: "其他",
    shares: "",
    cost: "",
    last: "",
  });
  const [err, setErr] = useState("");

  const save = useMutate<{ payload: Record<string, unknown>; name: string; symbol: string }, void>({
    fn: (a) =>
      api(`/api/positions/${encodeURIComponent(a.symbol)}`, {
        method: "PUT",
        body: JSON.stringify(a.payload),
      }).then(() => undefined),
    key: "pos.editSaved",
    vars: (a) => ({ name: a.name }),
    silentError: true,
    onSettled: (_res, e) => {
      if (e) setErr(e instanceof Error ? e.message : String(e));
      else onDone();
    },
  });

  useEffect(() => {
    if (open && position) {
      // cost 是总成本（每股 × 股数），这个输入框要的是**每股**成本。
      // 直接回填 position.cost 会把 168000 当成单价存回去，保存一次成本放大 100 倍。
      const perShare =
        position.cost_per_share ??
        (position.shares > 0 ? position.cost / position.shares : 0);
      setF({
        name: position.name,
        kind: position.kind,
        industry: position.industry,
        shares: String(position.shares),
        cost: String(Number(perShare.toFixed(6))),
        last: String(position.last),
      });
      setErr("");
    }
  }, [open, position]);

  if (!position) return null;

  const submit = () => {
    setErr("");
    const shares = Number(f.shares);
    const cost = Number(f.cost);
    const last = Number(f.last);
    if (!f.name.trim()) return setErr(t("pos.nameReq"));
    if (!(shares > 0)) return setErr(t("pos.sharesReq"));
    if (cost < 0) return setErr(t("pos.costReq"));
    if (last < 0) return setErr(t("pos.lastReq"));
    void save.mutate({
      symbol: position.symbol,
      payload: {
        name: f.name.trim(),
        kind: f.kind,
        industry: f.industry.trim() || "其他",
        shares,
        cost,
        last,
      },
      name: f.name,
    });
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/45 backdrop-blur-sm data-[state=open]:animate-fade-in" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(94vw,30rem)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-card p-4 shadow-lift data-[state=open]:animate-fade-in max-h-[90vh] overflow-y-auto scroll-thin">
          <div className="flex items-center justify-between mb-3">
            <Dialog.Title className="text-sm font-semibold flex items-center gap-1.5">
              <Pencil className="w-3.5 h-3.5 text-primary" />
              {t("pos.edit", { name: position.name })}
              <span className="text-xs text-muted-foreground tabular-nums">{position.symbol}</span>
            </Dialog.Title>
            <Dialog.Close asChild>
              <button
                type="button"
                className="rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-accent"
                aria-label={t("pos.close")}
              >
                ✕
              </button>
            </Dialog.Close>
          </div>

          <div className="grid grid-cols-2 gap-2.5">
            <div>
              <label className={labelCls}>{t("pos.name")}</label>
              <input className={inputCls} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
            </div>
            <div>
              <label className={labelCls}>{t("pos.kind")}</label>
              <select className={inputCls} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
                {["股票", "ETF", "基金", "现金", "其他"].map((k) => (
                  <option key={k}>{k}</option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls}>{t("pos.industry")}</label>
              <input className={inputCls} value={f.industry} onChange={(e) => setF({ ...f, industry: e.target.value })} />
            </div>
            <div>
              <label className={labelCls}>{t("pos.shares")}</label>
              <input className={inputCls} type="number" min="0" step="any" value={f.shares} onChange={(e) => setF({ ...f, shares: e.target.value })} />
            </div>
            <div>
              <label className={labelCls}>{t("pos.cost")}</label>
              <input className={inputCls} type="number" min="0" step="any" value={f.cost} onChange={(e) => setF({ ...f, cost: e.target.value })} />
            </div>
            <div>
              <label className={labelCls}>{t("pos.last")}</label>
              <input className={inputCls} type="number" min="0" step="any" value={f.last} onChange={(e) => setF({ ...f, last: e.target.value })} />
            </div>
          </div>

          {err ? <FieldError className="mt-2">{err}</FieldError> : null}

          <div className="mt-4 flex justify-end gap-2">
            <Dialog.Close asChild>
              <Button variant="outline" size="sm">
                {t("confirm.cancel")}
              </Button>
            </Dialog.Close>
            <Button size="sm" onClick={submit} disabled={!f.name || !f.shares || save.isPending}>
              {t("entry.save")}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
