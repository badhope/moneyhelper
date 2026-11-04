import { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";
import { api } from "@/lib/api";
import { useMutate } from "@/lib/use-mutate";
import { FieldError } from "@/components/ui/field-error";
import { fmtMoney } from "@/lib/format";
import type { Position } from "@/lib/types";

const inputCls =
  "w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring";
const labelCls = "block text-xs text-muted-foreground mb-1";

/**
 * 追加持仓弹窗：填「本次买入股数 + 成交价」，后端按加权平均合并成本。
 *
 * 为什么必须有这个弹窗：原实现点「追加」直接把当前全部持仓股数当新增股数提交，
 * 点一次仓位就翻倍、成本价被重算，且没有确认。这属于误触即篡改核心资产数据。
 * 现在点击只打开本弹窗，股数默认空、必须用户输入，并实时显示合并后的结果让他核对。
 */
export function PositionAppendDialog({
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
  const [shares, setShares] = useState("");
  const [price, setPrice] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open || !position) return;
    setShares("");
    // 默认填当前每股成本作为参考价，但用户可以改（实际成交价常不同）
    setPrice(String(position.cost_per_share ?? (position.shares > 0 ? position.cost / position.shares : 0)));
    setErr("");
  }, [open, position]);

  const addMut = useMutate<{ symbol: string; shares: number; cost: number }, void>({
    fn: (a) =>
      api(`/api/positions/${encodeURIComponent(a.symbol)}/append`, {
        method: "POST",
        body: JSON.stringify({ shares: a.shares, cost: a.cost }),
      }),
    key: "pos.appended",
    vars: (a) => ({ name: position?.name ?? a.symbol, n: a.shares }),
    errorKey: "pos.appendFail",
    onSettled: (_r, e) => {
      if (e) return;
      onOpenChange(false);
      onDone();
    },
  });

  if (!position) return null;

  const addShares = Number(shares);
  const priceNum = Number(price);
  const valid = Number.isFinite(addShares) && addShares > 0 && Number.isFinite(priceNum) && priceNum > 0;

  // 事前预览：用户提交前就能看到合并后的股数与成本，避免「点完才发现不对」
  const oldShares = position.shares ?? 0;
  const oldPerShare = position.cost_per_share ?? (oldShares > 0 ? position.cost / oldShares : 0);
  const newShares = oldShares + (valid ? addShares : 0);
  const newPerShare =
    newShares > 0 ? (oldShares * oldPerShare + (valid ? addShares * priceNum : 0)) / newShares : oldPerShare;

  const submit = () => {
    if (!valid) {
      setErr(t("pos.appendInvalid"));
      return;
    }
    setErr("");
    addMut.mutate({ symbol: position.symbol, shares: addShares, cost: priceNum });
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-[2px]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(92vw,26rem)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-card p-4 shadow-lift focus:outline-none">
          <Dialog.Title className="text-sm font-semibold">
            {t("pos.appendTitle", { name: position.name })}
          </Dialog.Title>
          <Dialog.Description className="mt-1 text-[12px] text-muted-foreground">
            {t("pos.appendDesc")}
          </Dialog.Description>

          <div className="mt-3 space-y-2.5">
            <div>
              <label className={labelCls} htmlFor="append-shares">
                {t("pos.appendShares")}
              </label>
              <input
                id="append-shares"
                type="number"
                min="0"
                step="1"
                inputMode="decimal"
                className={inputCls}
                value={shares}
                onChange={(e) => setShares(e.target.value)}
                placeholder="100"
                autoFocus
              />
            </div>
            <div>
              <label className={labelCls} htmlFor="append-price">
                {t("pos.appendPrice")}
              </label>
              <input
                id="append-price"
                type="number"
                min="0"
                step="0.0001"
                inputMode="decimal"
                className={inputCls}
                value={price}
                onChange={(e) => setPrice(e.target.value)}
              />
            </div>
          </div>

          {/* 结果预览：这是用户核对「会不会算错」的唯一机会 */}
          <div className="mt-3 rounded-lg bg-muted/60 px-3 py-2 text-[12px] leading-relaxed">
            <div className="flex justify-between">
              <span className="text-muted-foreground">{t("pos.appendBefore")}</span>
              <span className="tabular-nums">
                {oldShares.toLocaleString()} × {fmtMoney(oldPerShare)}
              </span>
            </div>
            <div className="flex justify-between font-medium">
              <span className="text-muted-foreground">{t("pos.appendAfter")}</span>
              <span className="tabular-nums">
                {newShares.toLocaleString()} × {fmtMoney(newPerShare)}
              </span>
            </div>
          </div>

          <FieldError>{err}</FieldError>

          <div className="mt-4 flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
              {t("confirm.cancel")}
            </Button>
            <Button size="sm" disabled={!valid || addMut.isPending} onClick={submit}>
              {t("pos.appendConfirm")}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
