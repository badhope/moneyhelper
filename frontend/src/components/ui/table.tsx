import type { CSSProperties, ReactNode } from "react";

/**
 * 表格骨架：全站唯一的 `<table>` 容器。
 *
 * 原先 16 处各自写 `className="w-full text-[11px]/text-[12px]/text-xs/text-sm
 * + min-w-[420~560px] + table-fixed + border-collapse"`，字号与最小宽度靠人工对齐，
 * 同一份"表格该长什么样"的知识被复制了 16 份。
 *
 * 这里只统一**容器层**（字号 / 是否固定列宽 / 最小宽度 / 对齐 / 边框合并），
 * 不碰 `<thead>/<th>/<td>` 的结构——各表的内边距与语义列（金额右对齐、状态徽章等）
 * 差异是真实存在的，强行抽象成 columns 配置会把简单表格写复杂，反而更难维护。
 *
 * 字号档位对应既有用法（1rem=16px）：
 *   2xs=11px   xs=12px   sm=13px   md=14px(text-sm)
 */
type Size = "2xs" | "xs" | "sm" | "md";

const SIZE_CLASS: Record<Size, string> = {
  "2xs": "text-[11px]",
  xs: "text-[12px]",
  sm: "text-[13px]",
  md: "text-sm",
};

export function Table({
  size = "xs",
  fixed = false,
  collapse = false,
  minWidth,
  align,
  className,
  style,
  children,
  ...rest
}: {
  size?: Size;
  /** 固定列宽（原 `table-fixed`） */
  fixed?: boolean;
  /** 边框合并（原 `border-collapse`）。原生默认是 separate，别默认打开以免改变既有视觉 */
  collapse?: boolean;
  /** 最小宽度（px），窄屏下允许横向滚动而不是挤压列 */
  minWidth?: number;
  align?: "left" | "center" | "right";
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
} & Record<string, unknown>) {
  const cls = [
    "w-full",
    SIZE_CLASS[size],
    fixed ? "table-fixed" : "",
    collapse ? "border-collapse" : "",
    align ? `text-${align}` : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");
  const mergedStyle = minWidth ? { minWidth, ...style } : style;
  return (
    <table className={cls} style={mergedStyle} {...rest}>
      {children}
    </table>
  );
}
