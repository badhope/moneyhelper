import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { MotionConfig } from "framer-motion";
import { PanelLeftOpen, X } from "lucide-react";
import { SessionSidebar } from "@/components/SessionSidebar";
import { Onboarding } from "@/components/Onboarding";
import { CommandPalette } from "@/components/CommandPalette";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ConfirmDialog } from "@/components/ui/confirm";
import { OfflineBanner } from "@/components/ui/offline-banner";
import { PasswordDialog } from "@/components/ui/password-dialog";
import { ErrorBoundary } from "@/lib/ErrorBoundary";
import { useBootstrap, useSessions, store } from "@/lib/store";
import { api, getToken } from "@/lib/api";
import { LoginView } from "@/components/LoginView";
import { useToast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { useIsDesktop } from "@/lib/use-media-query";
import { useResizableWidth } from "@/lib/use-resizable-width";
import { TopBar } from "@/components/TopBar";
import { MobileDrawer } from "@/components/MobileDrawer";
import { MobileTabBar } from "@/components/MobileTabBar";

// 首屏只需要 TopBar + 会话栏 + 对话区。以下面板都是"点开才用"，
// 静态引入会把它们的依赖（Dashboard 的图表、部门看板、设置表单）压进主包。
const ChatView = lazy(() => import("@/components/ChatView").then((m) => ({ default: m.ChatView })));
const SettingsView = lazy(() => import("@/components/SettingsView").then((m) => ({ default: m.SettingsView })));
const FinancePage = lazy(() => import("@/components/FinancePage").then((m) => ({ default: m.FinancePage })));
const ScheduledOutputsPanel = lazy(() =>
  import("@/components/ScheduledOutputsPanel").then((m) => ({ default: m.ScheduledOutputsPanel })),
);
const DepartmentPanel = lazy(() =>
  import("@/components/DepartmentPanel").then((m) => ({ default: m.DepartmentPanel })),
);

export type DataKind = "overview" | "holdings" | "market" | "ledger" | "health" | "strategy";

export default function App() {
  const { t } = useI18n();
  const { sessions, loading: sessionsLoading } = useSessions();
  const { bootstrap } = useBootstrap();
  const { toast } = useToast();

  // 主区视图：对话 or 财务工作区（整页切换，对标 opencode / codex 的 section 导航）
  const [view, setView] = useState<DataKind | "chat">("chat");
  const [settingsOpen, setSettingsOpen] = useState(false);
  // 设置页有未保存改动时，关闭前必须确认（原先点关闭直接丢弃修改，没有任何提示）
  const [settingsDirty, setSettingsDirty] = useState(false);
  const [settingsCloseConfirm, setSettingsCloseConfirm] = useState(false);

  const [activeThread, setActiveThread] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<{ id: number; threadId: string } | null>(null);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [cmdOpen, setCmdOpen] = useState(false);
  // 侧栏面板状态集中在此：桌面侧栏与移动抽屉都要能打开它们
  const [inboxOpen, setInboxOpen] = useState(false);
  const [deptOpen, setDeptOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  // 桌面侧栏按视口条件渲染（而非 CSS 隐藏）：避免同一入口在移动端出现两份
  // 可访问 DOM（屏幕阅读器与自动化工具都会读到）
  const isDesktop = useIsDesktop();
  // 桌面侧栏宽度可拖拽（持久化）；最小 200 保证会话标题可读，最大 420 不挤压对话
  const navWidth = useResizableWidth({
    storageKey: "wo.navWidth",
    defaultWidth: 240,
    min: 200,
    max: 420,
  });
  const [locateRunId, setLocateRunId] = useState<number | null>(null);

  const [userCount, setUserCount] = useState<number | null>(null);
  const [authed, setAuthed] = useState<boolean>(!!getToken());

  useEffect(() => {
    if (getToken()) return;
    api<{ count: number }>("/api/auth/user-count")
      .then((r) => setUserCount(r.count ?? 0))
      .catch(() => setUserCount(0));
  }, []);

  const [sidebarOpen, setSidebarOpen] = useState(() => {
    try {
      return localStorage.getItem("wo.sidebar") !== "0";
    } catch {
      return true;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem("wo.sidebar", sidebarOpen ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [sidebarOpen]);

  const colorScheme = bootstrap?.settings.color_scheme ?? "cn";
  useEffect(() => {
    document.documentElement.dataset.scheme = colorScheme === "us" ? "us" : "cn";
  }, [colorScheme]);

  // 适老化：字号档位与高对比度写进根元素，由 index.css 的 data-* 规则统一放大
  const textScale = bootstrap?.settings.text_scale ?? "normal";
  const highContrast = bootstrap?.settings.high_contrast ?? "off";
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.textScale = textScale;
    root.dataset.contrast = highContrast === "on" ? "high" : "normal";
  }, [textScale, highContrast]);

  useEffect(() => {
    if (bootstrap?.settings.data_note !== "empty") return;
    try {
      if (localStorage.getItem("wo.onboarded") === "1") return;
    } catch {
      return;
    }
    setShowOnboarding(true);
  }, [bootstrap]);

  /**
   * 新对话：只切到一个本地临时线程，不落库。
   * 对标 ChatGPT：点「新对话」不该在侧栏留下一条空会话；只有发出第一条消息后
   * 后端 upsert_session 才会真正建会话（标题也由首个问题决定）。
   */
  const newSession = useCallback(() => {
    setActiveThread(`__new_${Date.now()}`);
  }, []);

  const openChat = useCallback(
    (threadId: string | null) => {
      if (!threadId && sessions.length === 0) {
        void newSession();
        return;
      }
      setActiveThread(threadId ?? sessions[0]?.thread_id ?? null);
    },
    [sessions, newSession],
  );

  const deleteSession = useCallback(
    async (id: number, threadId: string) => {
      try {
        await api(`/api/sessions/${id}`, { method: "DELETE" });
        await store.refreshSessions();
        if (activeThread === threadId) {
          setActiveThread(null);
          if (sessions.length <= 1) void newSession();
          else {
            const next = sessions.find((s) => s.thread_id !== threadId);
            setActiveThread(next?.thread_id ?? null);
          }
        }
        toast(t("app.sessionDeleted"), "ok");
      } catch (e) {
        toast(e instanceof Error ? e.message : String(e), "error");
      }
    },
    [activeThread, sessions, newSession, toast, t],
  );

  const renameSession = useCallback(
    async (id: number, title: string) => {
      try {
        await api(`/api/sessions/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ title }),
        });
        await store.refreshSessions();
      } catch (e) {
        toast(e instanceof Error ? e.message : String(e), "error");
      }
    },
    [toast],
  );

  useEffect(() => {
    if (activeThread) return;
    // 会话列表加载完成前不下结论：否则会把「加载中」误判为「没有任何会话」，
    // 每次打开都新建垃圾会话，且首发消息可能滞留在 __tmp_ 线程。
    if (sessionsLoading) return;
    if (sessions.length > 0) setActiveThread(sessions[0].thread_id);
    else void newSession();
  }, [activeThread, sessions, sessionsLoading, newSession]);

  // 对话里的"跳转意图"：切到对应财务页
  const openData = useCallback((kind: string) => {
    if (kind === "settings") {
      setSettingsOpen(true);
      return;
    }
    const valid: DataKind[] = ["overview", "holdings", "market", "ledger", "health", "strategy"];
    const k = (valid as string[]).includes(kind) ? (kind as DataKind) : "overview";
    setView(k);
  }, []);

  // 需要登录但还没登录：渲染登录页。
  // 必须放在**所有 hooks 之后**——hooks 数量在多次渲染间必须一致，
  // 提前 return 会触发 "Rendered fewer hooks than expected" 白屏。
  if (userCount !== null && userCount > 0 && !authed) {
    return (
      <MotionConfig reducedMotion="user">
        <LoginView onAuthed={() => setAuthed(true)} />
      </MotionConfig>
    );
  }

  return (
    <MotionConfig reducedMotion="user">
      <TooltipProvider>
        <OfflineBanner />
        <ErrorBoundary>
          <div className="flex h-full">
            {/* 左侧会话栏：窄、常驻、可折叠（仅桌面渲染，移动端用抽屉） */}
            {isDesktop && (
            <aside
              className={cn(
                "relative flex shrink-0 flex-col transition-[width] duration-200",
                sidebarOpen ? "" : "w-12",
              )}
              style={sidebarOpen ? { width: navWidth.width } : undefined}
            >
              {sidebarOpen ? (
                <SessionSidebar
                  activeThread={activeThread}
                  onHome={() => setView("chat")}
                  onOpenOverview={() => setView("overview")}
                  activeView={view}
                  onSelect={(tid) => { setView("chat"); openChat(tid); }}
                  onNew={() => { setView("chat"); void newSession(); }}
                  onDelete={(id, threadId) => setPendingDelete({ id, threadId })}
                  onRename={renameSession}
                  onOpenSettings={() => setSettingsOpen(true)}
                  onCollapse={() => setSidebarOpen(false)}
                  onOpenDept={() => setDeptOpen(true)}
                  onOpenInbox={() => setInboxOpen(true)}
                />
              ) : (
                <div className="flex h-full w-12 flex-col items-center bg-sidebar pt-3">
                  <button
                    type="button"
                    aria-label={t("sidebar.expand")}
                    onClick={() => setSidebarOpen(true)}
                    className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground"
                  >
                    <PanelLeftOpen className="w-4 h-4" />
                  </button>
                </div>
              )}
              {sidebarOpen && (
                <div
                  role="separator"
                  aria-orientation="vertical"
                  aria-label={t("sidebar.resize")}
                  aria-valuenow={navWidth.width}
                  className={cn(
                    "absolute -right-1 top-0 z-10 h-full w-2 cursor-col-resize transition-colors hover:bg-primary/30",
                    navWidth.dragging && "bg-primary/40",
                  )}
                  {...navWidth.handleProps}
                />
              )}
            </aside>
            )}

            {/* 主区：对话与财务工作区整页切换（对标 opencode / codex 的 section 导航） */}
            <div className="flex min-w-0 flex-1 flex-col">
              <TopBar
                onOpenSettings={() => setSettingsOpen(true)}
                onOpenNav={() => setMobileNavOpen(true)}
                onBackToChat={view !== "chat" ? () => setView("chat") : undefined}
              />

              <main className="flex min-h-0 flex-1 pb-[calc(3.25rem+env(safe-area-inset-bottom))] md:pb-0">
                <div className="flex h-full w-full flex-col view-enter">
                  <Suspense
                    fallback={
                      <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
                        {t("app.preparing")}
                      </div>
                    }
                  >
                    {view !== "chat" ? (
                      <FinancePage kind={view} onKindChange={(k) => setView(k)} />
                    ) : activeThread ? (
                      <ChatView
                        key={activeThread}
                        threadId={activeThread}
                        locateRunId={locateRunId}
                        onLocateDone={() => setLocateRunId(null)}
                        onNewSession={() => { void newSession(); }}
                        onOpenSettings={() => setSettingsOpen(true)}
                        onNavigate={openData}
                      />
                    ) : (
                      <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
                        {t("app.preparing")}
                      </div>
                    )}
                  </Suspense>
                </div>
              </main>
            </div>
          </div>

          {/* 移动端导航抽屉：桌面侧栏在 <md 隐藏，此处提供等价入口（会话列表/新建/部门/收件箱） */}
          {!isDesktop && (
          <MobileDrawer open={mobileNavOpen} onClose={() => setMobileNavOpen(false)}>
            <SessionSidebar
              activeThread={activeThread}
              onHome={() => {
                setMobileNavOpen(false);
                setView("chat");
              }}
              onOpenOverview={() => {
                setMobileNavOpen(false);
                setView("overview");
              }}
              activeView={view}
              onSelect={(tid) => {
                setMobileNavOpen(false);
                setView("chat");
                openChat(tid);
              }}
              onNew={() => {
                setMobileNavOpen(false);
                setView("chat");
                void newSession();
              }}
              onDelete={(id, threadId) => setPendingDelete({ id, threadId })}
              onRename={renameSession}
              onOpenSettings={() => {
                setMobileNavOpen(false);
                setSettingsOpen(true);
              }}
              onCollapse={() => setMobileNavOpen(false)}
              onOpenDept={() => {
                setMobileNavOpen(false);
                setDeptOpen(true);
              }}
              onOpenInbox={() => {
                setMobileNavOpen(false);
                setInboxOpen(true);
              }}
            />
          </MobileDrawer>
          )}

          {/* 侧栏面板：桌面与移动端共用同一份状态（避免两端各挂一份导致重复请求） */}
          <Suspense fallback={null}>
            {inboxOpen && <ScheduledOutputsPanel open onClose={() => setInboxOpen(false)} />}
            {deptOpen && <DepartmentPanel open onClose={() => setDeptOpen(false)} />}
          </Suspense>

          {/* 手机端底部导航：高频入口常驻拇指区，其余功能走抽屉 */}
          {!isDesktop && (
            <MobileTabBar
              active={view}
              onChat={() => setView("chat")}
              onData={(k) => setView(k)}
              onInbox={() => setInboxOpen(true)}
              onSettings={() => setSettingsOpen(true)}
            />
          )}

          {/* 设置页：全屏 overlay（ChatGPT 式：左侧栏收起，顶栏只有标题与关闭） */}
          {settingsOpen && (
            <div className="fixed inset-0 z-40 flex flex-col bg-background">
              <div className="flex h-12 shrink-0 items-center justify-between border-b border-border/70 px-4">
                <span className="text-[15px] font-medium">{t("topbar.settings")}</span>
                <button
                  type="button"
                  onClick={() => {
                    if (settingsDirty) setSettingsCloseConfirm(true);
                    else setSettingsOpen(false);
                  }}
                  className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                >
                  <X className="w-4 h-4" /> {t("app.close")}
                </button>
              </div>
              <div className="flex min-h-0 flex-1 flex-col">
                <div className="mx-auto flex min-h-0 w-full max-w-6xl flex-1 flex-col px-4 py-4 sm:px-6">
                  <Suspense
                    fallback={
                      <div className="py-12 text-center text-sm text-muted-foreground">{t("app.preparing")}</div>
                    }
                  >
                    <SettingsView onDirtyChange={setSettingsDirty} />
                  </Suspense>
                </div>
              </div>
            </div>
          )}

          <ConfirmDialog
            open={settingsCloseConfirm}
            onOpenChange={setSettingsCloseConfirm}
            title={t("settings.unsavedTitle")}
            description={t("settings.unsavedDesc")}
            confirmText={t("settings.discardAndClose")}
            cancelText={t("settings.keepEditing")}
            danger
            onConfirm={() => {
              setSettingsCloseConfirm(false);
              setSettingsDirty(false);
              setSettingsOpen(false);
            }}
          />

          <ConfirmDialog
            open={pendingDelete !== null}
            onOpenChange={(o) => {
              if (!o) setPendingDelete(null);
            }}
            title={t("app.deleteTitle")}
            description={t("app.deleteDesc")}
            confirmText={t("app.delete")}
            danger
            onConfirm={() => {
              const td = pendingDelete;
              setPendingDelete(null);
              if (td) void deleteSession(td.id, td.threadId);
            }}
          />

          <PasswordDialog />

          <CommandPalette
            open={cmdOpen}
            onOpenChange={setCmdOpen}
            onNavigateChat={() => undefined}
            onNavigateFeature={openData}
            onOpenSettings={() => setSettingsOpen(true)}
            onNewSession={() => void newSession()}
            sessions={sessions}
            onSelectSession={openChat}
          />

          {showOnboarding && (
            <Onboarding
              onNavigate={(where) => {
                if (where === "settings") setSettingsOpen(true);
                else openData(where);
              }}
              onDone={() => {
                try {
                  localStorage.setItem("wo.onboarded", "1");
                } catch {
                  /* ignore */
                }
                setShowOnboarding(false);
              }}
            />
          )}
        </ErrorBoundary>
      </TooltipProvider>
    </MotionConfig>
  );
}
