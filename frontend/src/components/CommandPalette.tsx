import { useEffect, useState } from "react";
import { Command } from "cmdk";
import {
  BarChart3, CandlestickChart, CreditCard, FileText, Languages, LayoutDashboard, MessageCircle, MessageSquare, Moon, Users,
  Settings, SunMoon, Target, Undo2, Wallet,
} from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { useTheme } from "@/lib/theme";
import { useToast } from "@/lib/toast";
import { store } from "@/lib/store";
import { listUndoables, undoById, type UndoableItem } from "@/lib/api";
import type { SessionItem } from "@/lib/types";

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onNavigateChat: () => void;
  onNavigateFeature: (feat: string) => void;
  onOpenSettings: () => void;
  onNewSession: () => void;
  /** 最近会话（跳转用） */
  sessions?: SessionItem[];
  onSelectSession?: (threadId: string) => void;
}

/** 全局命令面板（Cmd/Ctrl+K）：页面跳转 / 记账 / 撤销最近操作 / 外观 / 语言 / 新建会话。
 *  对标 WorkBuddy / ChatGPT 的 Command Palette 交互。 */
export function CommandPalette({
  open,
  onOpenChange,
  onNavigateChat,
  onNavigateFeature,
  onOpenSettings,
  onNewSession,
  sessions,
  onSelectSession,
}: CommandPaletteProps) {
  const { t, setLang } = useI18n();
  const { setTheme } = useTheme();
  const { toast } = useToast();
  const [q, setQ] = useState("");
  const [undos, setUndos] = useState<UndoableItem[]>([]);

  // 关闭时清空搜索词
  useEffect(() => {
    if (!open) setQ("");
  }, [open]);

  // 每次打开时拉取最近可撤销操作
  useEffect(() => {
    if (!open) return;
    let alive = true;
    listUndoables(8)
      .then((items) => {
        if (alive) setUndos(items);
      })
      .catch(() => {
        /* 撤销列表读取失败不影响命令面板其他功能 */
      });
    return () => {
      alive = false;
    };
  }, [open]);

  // 全局快捷键：Cmd/Ctrl+K 开关，Esc 关闭（此前只有开关没有 Esc，面板会卡住不关）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onOpenChange(!open);
        return;
      }
      if (open && e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onOpenChange(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  const run = (fn: () => void) => {
    onOpenChange(false);
    fn();
  };

  const runUndo = async (item: UndoableItem) => {
    onOpenChange(false);
    try {
      await undoById(item.id);
      toast(t("cmd.undoOk", { label: item.label }), "ok");
      store.bump();
    } catch (e) {
      toast(t("cmd.undoFail", { e: e instanceof Error ? e.message : String(e) }), "error");
    }
  };

  return (
    <div className={`fixed inset-0 z-[60] ${open ? "" : "pointer-events-none"}`}>
      {/* 遮罩 */}
      <div
        className={`absolute inset-0 bg-black/40 backdrop-blur-sm transition-opacity duration-150 ${open ? "opacity-100" : "opacity-0"}`}
        onClick={() => onOpenChange(false)}
      />
      {/* 面板 */}
      <div
        className={`absolute left-1/2 top-[7vh] w-[min(92vw,38rem)] -translate-x-1/2 transition-all duration-150 ${
          open ? "opacity-100 scale-100 translate-y-0" : "opacity-0 scale-95 pointer-events-none"
        }`}
      >
        <Command
          className="flex max-h-[calc(100dvh-16vh)] flex-col overflow-hidden rounded-xl border border-border bg-popover shadow-xl"
          label="Command"
        >
          <Command.Input
            value={q}
            onValueChange={setQ}
            placeholder={t("cmd.placeholder")}
            className="w-full shrink-0 border-b border-border bg-transparent px-4 py-3 text-sm outline-none placeholder:text-muted-foreground"
          />
          <Command.List className="min-h-0 flex-1 overflow-y-auto scroll-thin p-1.5 pb-3">
            <Command.Empty className="px-3 py-6 text-center text-sm text-muted-foreground">
              {t("cmd.empty")}
            </Command.Empty>

            <Command.Group heading={t("cmd.nav")} className="text-[11px] text-muted-foreground">
              <Command.Item onSelect={() => run(onNavigateChat)} className="cmd-item">
                <MessageSquare className="w-4 h-4" />
                <span>{t("cmd.goChat")}</span>
              </Command.Item>
              <Command.Item onSelect={() => run(() => onNavigateFeature("overview"))} className="cmd-item">
                <LayoutDashboard className="w-4 h-4" />
                <span>{t("cmd.goOverview")}</span>
              </Command.Item>
              <Command.Item onSelect={() => run(() => onNavigateFeature("holdings"))} className="cmd-item">
                <Wallet className="w-4 h-4" />
                <span>{t("cmd.goHoldings")}</span>
              </Command.Item>
              <Command.Item onSelect={() => run(() => onNavigateFeature("research"))} className="cmd-item">
                <CandlestickChart className="w-4 h-4" />
                <span>{t("cmd.goResearch")}</span>
              </Command.Item>
              <Command.Item onSelect={() => run(() => onNavigateFeature("statements"))} className="cmd-item">
                <FileText className="w-4 h-4" />
                <span>{t("cmd.goStatements")}</span>
              </Command.Item>
              <Command.Item onSelect={() => run(() => onNavigateFeature("paper"))} className="cmd-item">
                <Users className="w-4 h-4" />
                <span>{t("cmd.goPaper")}</span>
              </Command.Item>
              <Command.Item onSelect={() => run(() => onNavigateFeature("market"))} className="cmd-item">
                <BarChart3 className="w-4 h-4" />
                <span>{t("cmd.goMarket")}</span>
              </Command.Item>
              <Command.Item onSelect={() => run(() => onNavigateFeature("strategy"))} className="cmd-item">
                <Target className="w-4 h-4" />
                <span>{t("cmd.goStrategy")}</span>
              </Command.Item>
              <Command.Item onSelect={() => run(() => onNavigateFeature("ledger"))} className="cmd-item">
                <CreditCard className="w-4 h-4" />
                <span>{t("cmd.goLedger")}</span>
              </Command.Item>
              <Command.Item onSelect={() => run(onOpenSettings)} className="cmd-item">
                <Settings className="w-4 h-4" />
                <span>{t("cmd.goSettings")}</span>
              </Command.Item>
            </Command.Group>

            <Command.Group heading={t("cmd.actions")} className="flex-[2] text-[11px] text-muted-foreground">
              <Command.Item onSelect={() => run(onNewSession)} className="cmd-item">
                <PlusIcon />
                <span>{t("cmd.newSession")}</span>
              </Command.Item>
              <Command.Item onSelect={() => run(() => onNavigateFeature("strategy"))} className="cmd-item">
                <Target className="w-4 h-4" />
                <span>{t("cmd.goStrategy")}</span>
              </Command.Item>
              <Command.Item onSelect={() => run(() => onNavigateFeature("ledger"))} className="cmd-item">
                <PencilIcon />
                <span>{t("cmd.quickBook")}</span>
              </Command.Item>
            </Command.Group>

            {undos.length > 0 && (
              <Command.Group heading={t("cmd.undo")} className="text-[11px] text-muted-foreground">
                {undos.slice(0, 6).map((u) => (
                  <Command.Item
                    key={u.id}
                    onSelect={() => void runUndo(u)}
                    className="cmd-item"
                    value={`${u.label} undo ${u.entity} ${u.entity_id}`}
                  >
                    <Undo2 className="w-4 h-4" />
                    <span className="truncate">{u.label}</span>
                    <span className="ml-auto text-[11px] text-muted-foreground">{u.created_at.slice(5, 16)}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}

            {sessions && sessions.length > 0 && onSelectSession && (
              <Command.Group heading={t("cmd.recent")} className="text-[11px] text-muted-foreground">
                {sessions.slice(0, 5).map((s) => (
                  <Command.Item
                    key={s.thread_id}
                    onSelect={() => run(() => onSelectSession(s.thread_id))}
                    className="cmd-item"
                  >
                    <MessageCircle className="w-4 h-4" />
                    <span className="truncate">{s.title}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}

            <Command.Group heading={t("cmd.appearance")} className="text-[11px] text-muted-foreground">
              <Command.Item
                onSelect={() => run(() => setTheme("light"))}
                className="cmd-item"
                keywords={["light", "浅色", "主题"]}
              >
                <SunIcon />
                <span>{t("settings.light")}</span>
              </Command.Item>
              <Command.Item
                onSelect={() => run(() => setTheme("dark"))}
                className="cmd-item"
                keywords={["dark", "深色", "主题"]}
              >
                <Moon className="w-4 h-4" />
                <span>{t("settings.dark")}</span>
              </Command.Item>
              <Command.Item
                onSelect={() => run(() => setTheme("system"))}
                className="cmd-item"
                keywords={["system", "跟随系统", "主题"]}
              >
                <SunMoon className="w-4 h-4" />
                <span>{t("settings.system")}</span>
              </Command.Item>
            </Command.Group>

            <Command.Group heading={t("cmd.language")} className="text-[11px] text-muted-foreground">
              <Command.Item onSelect={() => run(() => setLang("zh"))} className="cmd-item" value="中文">
                <Languages className="w-4 h-4" />
                <span>中文</span>
              </Command.Item>
              <Command.Item onSelect={() => run(() => setLang("en"))} className="cmd-item" value="English">
                <Languages className="w-4 h-4" />
                <span>English</span>
              </Command.Item>
            </Command.Group>
          </Command.List>
        </Command>
      </div>
    </div>
  );
}

// 占位图标（避免顶部引入过多）：用小图标即可
function PlusIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 5v14M5 12h14" strokeLinecap="round" />
    </svg>
  );
}
function PencilIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3Z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
function SunIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" strokeLinecap="round" />
    </svg>
  );
}
