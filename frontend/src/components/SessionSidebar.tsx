/** 桌面侧边栏（ChatGPT 式）：品牌行 → 新对话 → 搜索 → 时间分组会话 → 底部功能与设置。 */

import { useEffect, useRef, useState } from "react";
import {
  Building2,
  Check,
  Inbox,
  LayoutGrid,
  MessageCircle,
  PanelLeftClose,
  Pencil,
  Plus,
  Search,
  Settings,
  Sunrise,
  Trash2,
  X,
} from "lucide-react";
import { BrandLogo, BRAND } from "@/lib/brand";
import { useSessions } from "@/lib/store";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { useScheduledOutputs } from "@/lib/inbox";
import { MorningReportDialog } from "@/components/MorningReportDialog";
import type { SessionItem } from "@/lib/types";

type Bucket = "today" | "week" | "older";

function timeBucket(iso: string): Bucket {
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return "older";
  const days = (Date.now() - ts) / 86400000;
  if (days < 1) return "today";
  if (days < 7) return "week";
  return "older";
}

export function SessionSidebar({
  activeThread,
  onHome,
  onOpenOverview,
  activeView,
  onSelect,
  onNew,
  onDelete,
  onRename,
  onOpenSettings,
  onCollapse,
  onOpenDept,
  onOpenInbox,
}: {
  activeThread: string | null;
  /** 品牌点击：回到问答 */
  onHome: () => void;
  /** 底部「总览」入口 */
  onOpenOverview: () => void;
  /** 当前主区视图：chat 或某个财务页 */
  activeView: string;
  onSelect: (threadId: string | null) => void;
  onNew: () => void;
  onDelete: (id: number, threadId: string) => void;
  onRename: (id: number, title: string) => void;
  onOpenSettings: () => void;
  onCollapse: () => void;
  onOpenDept: () => void;
  onOpenInbox: () => void;
}) {
  const { t } = useI18n();
  const { sessions } = useSessions();
  const { unread } = useScheduledOutputs();
  const [editing, setEditing] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [q, setQ] = useState("");
  const [reportOpen, setReportOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (searchOpen) searchRef.current?.focus();
  }, [searchOpen]);

  const kw = q.trim().toLowerCase();
  const filtered = kw ? sessions.filter((s) => s.title.toLowerCase().includes(kw)) : sessions;

  const groups: { key: Bucket; label: string }[] = [
    { key: "today", label: t("sidebar.today") },
    { key: "week", label: t("sidebar.week") },
    { key: "older", label: t("sidebar.older") },
  ];

  const commitRename = (s: SessionItem) => {
    const next = editTitle.trim();
    if (next && next !== s.title) onRename(s.id, next);
    setEditing(null);
  };

  const renderSession = (s: SessionItem) => {
    const active = s.thread_id === activeThread;
    if (editing === s.id) {
      return (
        <div key={s.id} className="flex items-center gap-1 rounded-lg bg-accent px-2 py-1">
          <input
            autoFocus
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitRename(s);
              if (e.key === "Escape") setEditing(null);
            }}
            onBlur={() => commitRename(s)}
            className="min-w-0 flex-1 bg-transparent text-[13px] outline-none"
            aria-label={t("sidebar.rename")}
          />
          <button
            type="button"
            aria-label={t("sidebar.rename")}
            className="p-1 text-muted-foreground hover:text-foreground"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => commitRename(s)}
          >
            <Check className="h-3.5 w-3.5" />
          </button>
        </div>
      );
    }
    return (
      <div
        key={s.id}
        role="button"
        tabIndex={0}
        onClick={() => onSelect(s.thread_id)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSelect(s.thread_id);
          }
        }}
        className={cn(
          "group relative flex h-9 items-center gap-2 rounded-lg px-2 text-[13.5px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          active
            ? "bg-foreground/[0.07] font-medium text-foreground"
            : "text-foreground/80 hover:bg-foreground/[0.05]",
        )}
      >
        <span className="min-w-0 flex-1 truncate">
          {/* 后端把默认标题存成中文「新会话」（数据层不感知语言）。
              英文界面直接显示它就是中英混排，因此按当前语言替换占位标题。 */}
          {s.title === "新会话" ? t("sidebar.newSession") : s.title}
        </span>
        <span className="absolute right-1 flex items-center gap-0.5 rounded-md bg-inherit pl-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          <button
            type="button"
            aria-label={t("sidebar.rename")}
            className="rounded p-1 text-muted-foreground hover:text-foreground"
            onClick={(e) => {
              e.stopPropagation();
              setEditTitle(s.title);
              setEditing(s.id);
            }}
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            aria-label={t("sidebar.deleteSession")}
            className="rounded p-1 text-muted-foreground hover:text-red-600"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(s.id, s.thread_id);
            }}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </span>
      </div>
    );
  };

  const navRow =
    "flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] text-foreground/80 transition-colors hover:bg-foreground/[0.05] hover:text-foreground";

  return (
    <div className="flex h-full flex-col bg-sidebar">
      <div className="flex items-center gap-1 px-2 pt-2.5 pb-1">
        <button
          type="button"
          onClick={onHome}
          className="flex min-w-0 items-center gap-2 rounded-lg px-1.5 py-1.5 text-left transition-colors hover:bg-foreground/[0.05]"
        >
          <BrandLogo size={26} />
          <span className="min-w-0">
            <span className="block truncate text-[15px] font-semibold leading-tight tracking-tight">
              {BRAND.name}
            </span>
            <span className="block truncate text-[10.5px] leading-tight text-muted-foreground">
              {t("brand.tagline")}
            </span>
          </span>
        </button>
        <button
          type="button"
          aria-label={t("sidebar.collapse")}
          onClick={onCollapse}
          className="ml-auto rounded-lg p-2 text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground"
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>

      <div className="px-2 pt-1">
        <div className="flex items-center gap-1">
          <button type="button" onClick={onNew} className={cn(navRow, "flex-1 font-medium")}>
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-foreground/15">
              <Plus className="h-3.5 w-3.5" />
            </span>
            {t("sidebar.newChat")}
          </button>
          <button
            type="button"
            aria-label={t("sidebar.searchSession")}
            aria-expanded={searchOpen}
            onClick={() => {
              setSearchOpen((v) => !v);
              if (searchOpen) setQ("");
            }}
            className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground"
          >
            <Search className="h-4 w-4" />
          </button>
        </div>

        {searchOpen && (
          <div className="relative mt-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              ref={searchRef}
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  setSearchOpen(false);
                  setQ("");
                }
              }}
              placeholder={t("sidebar.searchSession")}
              aria-label={t("sidebar.searchSession")}
              className="h-9 w-full rounded-lg bg-foreground/[0.05] pl-8 pr-8 text-[13px] outline-none placeholder:text-muted-foreground focus:bg-background focus:ring-1 focus:ring-border"
            />
            {q && (
              <button
                type="button"
                aria-label={t("sidebar.clearSearch")}
                onClick={() => setQ("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        )}
      </div>

      <div className="mt-2 min-h-0 flex-1 overflow-y-auto scroll-thin px-2 pb-2">
        {filtered.length === 0 ? (
          <div className="px-2 py-10 text-center text-xs leading-relaxed text-muted-foreground">
            <MessageCircle className="mx-auto mb-2 h-4 w-4 opacity-50" />
            {kw ? t("sidebar.noMatch") : t("sidebar.noSessions")}
          </div>
        ) : (
          groups.map((g) => {
            const items = filtered.filter((s) => timeBucket(s.updated_at || s.created_at) === g.key);
            if (items.length === 0) return null;
            return (
              <section key={g.key} className="mb-1">
                <h2 className="px-2 pb-1 pt-3 text-[11.5px] font-medium text-muted-foreground">
                  {g.label}
                </h2>
                <div className="space-y-px">{items.map(renderSession)}</div>
              </section>
            );
          })
        )}
      </div>

      <div className="border-t border-border/70 p-2">
        <button
          type="button"
          onClick={onOpenOverview}
          aria-current={activeView === "overview" ? "page" : undefined}
          className={cn(navRow, activeView === "overview" && "bg-foreground/[0.06] font-medium text-foreground")}
        >
          <LayoutGrid className="h-4 w-4 shrink-0" />
          {t("nav.dashboard")}
        </button>
        <button
          type="button"
          onClick={onOpenInbox}
          aria-label={t("inbox.title")}
          className={cn(navRow, "relative")}
        >
          <Inbox className="h-4 w-4 shrink-0" />
          <span className="min-w-0 flex-1 truncate text-left">{t("inbox.title")}</span>
          {unread > 0 && (
            <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold text-primary-foreground">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </button>
        <button type="button" onClick={onOpenDept} aria-label={t("dept.title")} className={navRow}>
          <Building2 className="h-4 w-4 shrink-0" />
          {t("dept.title")}
        </button>
        <button
          type="button"
          onClick={() => setReportOpen(true)}
          aria-label={t("report.generate")}
          className={navRow}
        >
          <Sunrise className="h-4 w-4 shrink-0" />
          {t("report.generate")}
        </button>
        <button type="button" onClick={onOpenSettings} className={navRow}>
          <Settings className="h-4 w-4 shrink-0" />
          {t("sidebar.settings")}
        </button>

        <div className="mt-1 flex items-center justify-between gap-2 border-t border-border/70 px-2.5 pt-2 text-[11px] text-muted-foreground">
          <span className="truncate">
            {sessions.length} {t("sidebar.sessionCount")}
          </span>
          <span className="truncate">{t("sidebar.localData")}</span>
        </div>
      </div>

      <MorningReportDialog open={reportOpen} onOpenChange={setReportOpen} />
    </div>
  );
}
