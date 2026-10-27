import { motion } from "framer-motion";
import { Inbox, LayoutGrid, MessageSquare, Settings2, Wallet } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { DataKind } from "@/App";

/**
 * 手机端底部导航（<768px）。
 *
 * 为什么不复用顶栏：手机上拇指可及区在屏幕底部，把主入口放顶部会让每次
 * 切换都变成"伸手 + 精确点击"。底部条只放高频五项，其余功能仍从抽屉进入，
 * 保持界面简单（用户不必一次看到所有能力）。
 *
 * 安全区：底部补 env(safe-area-inset-bottom)，避免被 iOS/Android 手势条遮挡。
 */
export function MobileTabBar({
  active,
  onChat,
  onData,
  onInbox,
  onSettings,
  unread = 0,
}: {
  /** 当前高亮项：chat 或某个数据面板 kind */
  active: DataKind | "chat" | null;
  onChat: () => void;
  onData: (kind: DataKind) => void;
  onInbox: () => void;
  onSettings: () => void;
  unread?: number;
}) {
  const { t } = useI18n();

  const items: {
    key: string;
    label: string;
    icon: typeof MessageSquare;
    onPress: () => void;
    isActive: boolean;
    badge?: number;
  }[] = [
    {
      key: "chat",
      label: t("nav.chat"),
      icon: MessageSquare,
      onPress: onChat,
      isActive: active === "chat",
    },
    {
      key: "overview",
      label: t("nav.finance"),
      icon: LayoutGrid,
      onPress: () => onData("overview"),
      // 财务工作区的所有子页（总览/行情/记账/体检）都归在「总览」这一入口下
      // 财务工作区的所有子页（总览/行情/记账/体检/投研/财报）都归在「总览」这一入口下
      isActive:
        active === "overview" ||
        active === "market" ||
        active === "ledger" ||
        active === "health" ||
        active === "strategy" ||
        active === "research" ||
        active === "statements" ||
        active === "paper",
    },
    {
      key: "holdings",
      label: t("nav.holdings"),
      icon: Wallet,
      onPress: () => onData("holdings"),
      isActive: active === "holdings",
    },
    {
      key: "inbox",
      label: t("inbox.title"),
      icon: Inbox,
      onPress: onInbox,
      isActive: false,
      badge: unread,
    },
    {
      key: "settings",
      label: t("sidebar.settings"),
      icon: Settings2,
      onPress: onSettings,
      isActive: false,
    },
  ];

  return (
    <nav
      aria-label={t("nav.main")}
      className="fixed inset-x-0 bottom-0 z-30 border-t border-border/70 bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
    >
      <ul className="flex items-stretch">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <li key={item.key} className="flex-1">
              <button
                type="button"
                onClick={item.onPress}
                aria-current={item.isActive ? "page" : undefined}
                className={cn(
                  "relative flex w-full flex-col items-center justify-center gap-0.5 py-2 text-[11px] leading-none transition-colors",
                  item.isActive ? "text-primary" : "text-muted-foreground active:text-foreground",
                )}
              >
                <Icon className="h-[18px] w-[18px]" aria-hidden="true" />
                <span>{item.label}</span>
                {item.badge ? (
                  <span className="absolute right-[22%] top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[9px] font-semibold text-primary-foreground">
                    {item.badge > 99 ? "99+" : item.badge}
                  </span>
                ) : null}
                {item.isActive && (
                  <motion.span
                    layoutId="xm-tab-indicator"
                    className="absolute inset-x-3 top-0 h-0.5 rounded-full bg-primary"
                    transition={{ type: "spring", stiffness: 500, damping: 40 }}
                  />
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
