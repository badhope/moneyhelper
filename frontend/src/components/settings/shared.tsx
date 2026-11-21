import { Card } from "@/components/ui/card";

// 表单样式统一在 ui/field，这里再导出一次，避免 20 多处旧引用一起改
export { inputCls, labelCls } from "@/components/ui/field";

/** 供应商预设（与后端 app/llm.py PROVIDERS 一致）：快捷选择自动填入 base/model，可手动改 */
export const PRESET_PROVIDERS = {
  // 内置聚合端点：一个 key 拉全部模型，国内直连
  qs: { base: "https://api.qs.al/v1", model: "glm-5.3-flash" },
  deepseek: { base: "https://api.deepseek.com/v1", model: "deepseek-chat" },
  doubao: { base: "https://ark.cn-beijing.volces.com/api/v3", model: "" },
  qwen: { base: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus" },
} as const;
export type ProviderKey = keyof typeof PRESET_PROVIDERS | "custom";

/** 设置页通用卡片容器：标题 + 图标 + 描述 + 内容 */
export function Section({
  title,
  icon,
  desc,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  desc?: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="p-[var(--card-pad)]">
      <div className="flex items-center gap-1.5 text-sm font-medium mb-1">
        {icon}
        {title}
      </div>
      {desc ? <div className="text-xs text-muted-foreground mb-2">{desc}</div> : null}
      {children}
    </Card>
  );
}

/** 设置页「标签 + 控件」横排容器 */
export function Row({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    // 窄屏改为上下堆叠：设置项右侧常是长下拉（供应商/模型），
    // 强制 shrink-0 横排会在 390px 下把文字压成逐字竖排。
    <div className="flex flex-col gap-1.5 py-1.5 @sm:flex-row @sm:items-center @sm:justify-between @sm:gap-3">
      <div className="min-w-0">
        <div className="text-sm">{label}</div>
        {hint ? <div className="text-xs text-muted-foreground mt-0.5">{hint}</div> : null}
      </div>
      <div className="min-w-0 @sm:shrink-0">{children}</div>
    </div>
  );
}
