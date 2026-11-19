import type { GlAccount } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

/**
 * 科目下拉：全站唯一实现。
 *
 * 原先 6 处（总账分录、报销借/贷方、采购应付、银行三处账户选择）各自手写
 * `<option value="">选择科目</option> + accounts.map(...)`，文案与展示格式
 * （`code + 空格 + name`）靠人工保持一致。改一处漏五处是迟早的事，所以收成一个组件。
 *
 * 只负责"呈现 + 回传字符串值"：不取数据、不管校验，避免把各页的加载状态耦合进来
 * （各页的 accounts 来源不同：有的是 GL 全量，有的按类型过滤）。
 */
export function AccountSelect({
  accounts,
  value,
  onChange,
  className,
  disabled,
  filter,
  blankLabel,
  id,
}: {
  accounts: GlAccount[];
  value: string;
  onChange: (value: string) => void;
  className?: string;
  disabled?: boolean;
  /** 只列出满足条件的科目，例如 `(a) => a.type === "asset"` */
  filter?: (a: GlAccount) => boolean;
  blankLabel?: string;
  /** 供 label 的 htmlFor 关联，调用方本来就有这个 id（迁移时保留，不要新造） */
  id?: string;
}) {
  const { t } = useI18n();
  const shown = filter ? accounts.filter(filter) : accounts;
  return (
    <select
      id={id}
      className={className}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
    >
      <option value="">{blankLabel ?? t("gl.selectAccount")}</option>
      {shown.map((a) => (
        <option key={a.id} value={a.id}>
          {a.code} {a.name}
        </option>
      ))}
    </select>
  );
}
