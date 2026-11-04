/** useMutate：基于 useMutation 的统一封装 —— 成功弹 ok toast + bump 刷新，失败弹错误 toast。
 *  替代散落在各处的「裸 api().then(bump)」调用（无 try/catch、DELETE 失败静默吞掉）。 */

import { useMutation } from "@tanstack/react-query";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { store } from "@/lib/store";

interface UseMutateOptions<TArgs, TResult> {
  /** 要执行的异步操作（内部会调 api 等） */
  fn: (args: TArgs) => Promise<TResult>;
  /** i18n 成功文案 key（可空：为空则成功不弹 toast，但仍 bump）；
   *  传函数时按本次 (args, 返回值) 动态选 key（用于按 res 二选一文案），返回 null 则不弹 */
  key?: string | ((args: TArgs, res: TResult) => string | null);
  /** 成功文案变量（{var} 占位替换）；传函数时按本次 (args, 返回值) 动态解析 */
  vars?: Record<string, string | number> | ((args: TArgs, res: TResult) => Record<string, string | number>);
  /** i18n 错误文案 key（可空：为空则直接弹错误 message） */
  errorKey?: string;
  /** 成功后是否刷新全局数据（默认 true）；传函数时按 (args, res) 动态决定 */
  bump?: boolean | ((args: TArgs, res: TResult) => boolean);
  /** 成功后额外回调（用于本地 state 清理等） */
  onSettled?: (res: TResult | undefined, err: unknown, args: TArgs) => void;
  /** true 时失败不弹 toast（由 onSettled 自行处理内联错误呈现） */
  silentError?: boolean;
}

export function useMutate<TArgs, TResult>(opts: UseMutateOptions<TArgs, TResult>) {
  const { toast } = useToast();
  const { t } = useI18n();

  const m = useMutation({
    mutationFn: opts.fn,
    onSuccess: (res, args) => {
      const doBump = typeof opts.bump === "function" ? opts.bump(args, res) : opts.bump !== false;
      if (doBump) store.bump();
      const key = typeof opts.key === "function" ? opts.key(args, res) : opts.key;
      if (key) {
        const vars = typeof opts.vars === "function" ? opts.vars(args, res) : opts.vars;
        toast(t(key, vars), "ok");
      }
      opts.onSettled?.(res, undefined, args);
    },
    onError: (e: unknown, args) => {
      const msg = e instanceof Error ? e.message : String(e);
      if (opts.silentError !== true) {
        if (opts.errorKey) {
          // vars 的签名是 (args, result)，成功路径依赖 result 拼文案。
          // 失败时 result 不存在，直接调用会让 vars 内部 res.xxx 抛 TypeError，
          // toast 永远执行不到——用户点了按钮毫无反馈（"以为已保存"）。
          // 这里包一层：vars 抛错就退回空对象，保证错误提示一定能显示。
          let base: Record<string, unknown> = {};
          if (typeof opts.vars === "function") {
            try {
              base = (opts.vars(args, undefined as unknown as TResult) ?? {}) as Record<string, unknown>;
            } catch {
              base = {};
            }
          } else if (opts.vars) {
            base = opts.vars as Record<string, unknown>;
          }
          toast(t(opts.errorKey, { ...base, e: msg }), "error");
        } else toast(msg, "error");
      }
      opts.onSettled?.(undefined, e, args);
    },
  });

  return {
    isPending: m.isPending,
    mutate: m.mutate,
    mutateAsync: m.mutateAsync,
  };
}
