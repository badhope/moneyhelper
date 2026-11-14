import { useCallback, useEffect, useState } from "react";
import { BrainCog, Check, Plus, Sparkles, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm";
import { FieldError } from "@/components/ui/field-error";
import { addMemory, clearMemory, deleteMemory, listMemory, forgetMemory, listReflections, resolveReflection, clearReflections, suggestMemories, type ReflectionItem } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { fmtDate } from "@/lib/format";
import type { MemoryItem } from "@/lib/types";
import { Section, inputCls, labelCls } from "./shared";

/** 长期记忆 + AI 归纳偏好 + 主动遗忘 + 经验库（P1 反思/踩坑复盘） */
export function MemorySection() {
  const { t } = useI18n();
  const [items, setItems] = useState<MemoryItem[] | null>(null);
  const [text, setText] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const [forgetOpen, setForgetOpen] = useState(false);
  const [reflections, setReflections] = useState<ReflectionItem[] | null>(null);
  // AI 归纳偏好：多条目建议，逐条「记住」才落库（不搞一键全收，避免噪音）
  const [aiBusy, setAiBusy] = useState(false);
  const [aiSuggestions, setAiSuggestions] = useState<string[] | null>(null);
  const { toast } = useToast();

  const reload = useCallback(async () => {
    try {
      setItems(await listMemory());
    } catch {
      setItems([]);
    }
    try {
      setReflections(await listReflections());
    } catch {
      setReflections([]);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const aiSuggest = async () => {
    setAiBusy(true);
    setAiSuggestions(null);
    try {
      const r = await suggestMemories();
      if (r.ok && r.suggestions?.length) setAiSuggestions(r.suggestions);
      else toast(String(r.error || t("settings.memAiFail")), "error");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setAiBusy(false);
    }
  };

  const adoptOne = async (content: string) => {
    try {
      const r = await addMemory(content);
      toast(r.deduped ? t("settings.memDup") : t("settings.memSaved"), "ok");
      setAiSuggestions((prev) => (prev ? prev.filter((s) => s !== content) : prev));
      void reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const submit = async () => {
    setErr("");
    if (!text.trim()) return;
    setBusy(true);
    try {
      const r = await addMemory(text.trim());
      setText("");
      toast(r.deduped ? t("settings.memDup") : t("settings.memSaved"), "ok");
      void reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const doForget = async () => {
    try {
      const r = await forgetMemory(180);
      toast(r.deleted ? t("settings.memForgot", { n: r.deleted }) : t("settings.memForgetNone"), "ok");
      setForgetOpen(false);
      void reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  return (
    <Section title={t("settings.navMemory")} icon={<BrainCog className="w-4 h-4 text-muted-foreground" />} desc={t("settings.memDesc")}>
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <label className={labelCls} htmlFor="memorysect-1">{t("settings.memNew")}</label>
          <input id="memorysect-1"
            className={inputCls}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void submit();
            }}
            placeholder={t("settings.memPh")}
            maxLength={500}
          />
        </div>
        <Button size="sm" onClick={() => void submit()} disabled={busy || !text.trim()}>
          <Plus className="w-3.5 h-3.5" /> {t("settings.memSave")}
        </Button>
      </div>
      {err ? <FieldError className="mt-1">{err}</FieldError> : null}

      {/* AI 归纳偏好：看最近提问给出建议，逐条「记住」才落库 */}
      <div className="mt-3 rounded-lg border border-dashed border-primary/30 bg-primary/5 p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="text-sm">{t("settings.memAi")}</div>
            <div className="mt-0.5 text-xs text-muted-foreground">{t("settings.memAiHint")}</div>
          </div>
          <Button variant="outline" size="sm" className="shrink-0" onClick={() => void aiSuggest()} disabled={aiBusy}>
            <Sparkles className="w-3.5 h-3.5" /> {aiBusy ? t("settings.aiBusy") : t("settings.aiGen")}
          </Button>
        </div>
        {aiSuggestions && aiSuggestions.length > 0 && (
          <ul className="mt-2 space-y-1.5">
            {aiSuggestions.map((s) => (
              <li key={s} className="flex items-center justify-between gap-2 rounded-md border border-border bg-card px-2.5 py-1.5 text-sm">
                <span className="min-w-0 flex-1 break-words">{s}</span>
                <span className="flex shrink-0 items-center gap-1">
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-primary hover:bg-primary/10"
                    onClick={() => void adoptOne(s)}
                  >
                    <Check className="w-3 h-3" /> {t("settings.memAiAdopt")}
                  </button>
                  <button
                    type="button"
                    aria-label={t("settings.memAiSkip", { c: s })}
                    className="rounded p-0.5 text-muted-foreground hover:text-foreground"
                    onClick={() => setAiSuggestions((prev) => (prev ? prev.filter((x) => x !== s) : prev))}
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="mt-3 flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {items == null ? t("settings.loading") : items.length === 0 ? t("settings.memEmpty") : t("settings.memCount", { n: items.length })}
        </span>
        <span className="flex items-center gap-2">
          {items && items.length > 0 && (
            <Button variant="outline" size="sm" className="h-6 px-2 text-xs" onClick={() => setForgetOpen(true)} title={t("settings.memForgetHint")}>
              {t("settings.memForget")}
            </Button>
          )}
          {items && items.length > 0 && (
            <Button variant="outline" size="sm" className="h-6 px-2 text-xs" onClick={() => setClearOpen(true)}>
              {t("settings.memClear")}
            </Button>
          )}
        </span>
      </div>

      {items && items.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {items.map((m) => (
            <li key={m.id} className="flex items-start justify-between gap-2 rounded-lg border border-border px-2.5 py-1.5 text-sm">
              <span className="min-w-0 flex-1">
                <span className="block break-words">{m.content}</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {m.kind !== "fact" ? `${m.kind} · ` : ""}{t("settings.memUpdated")} {fmtDate(m.updated_at)}
                </span>
              </span>
              <button
                className="shrink-0 text-muted-foreground hover:text-red-600"
                onClick={() => {
                void deleteMemory(m.id)
                  .then(reload)
                  .catch((e) => toast(e instanceof Error ? e.message : String(e), "error"));
              }}
                aria-label={t("settings.memDelete", { c: m.content })}
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* 主动遗忘：清理 180 天未使用的记忆 */}
      <ConfirmDialog
        open={forgetOpen}
        title={t("settings.memForgetTitle")}
        description={t("settings.memForgetDesc")}
        confirmText={t("settings.memForget")}
        danger
        onOpenChange={setForgetOpen}
        onConfirm={() => void doForget()}
      />

      <ConfirmDialog
        open={clearOpen}
        title={t("settings.memClearTitle")}
        description={t("settings.memClearDesc")}
        confirmText={t("settings.memClear")}
        danger
        onOpenChange={setClearOpen}
        onConfirm={() => {
          void clearMemory()
            .then(() => {
              setClearOpen(false);
              toast(t("settings.memCleared"), "ok");
              void reload();
            })
            .catch((e) => toast(e instanceof Error ? e.message : String(e), "error"));
        }}
      />

      {/* 经验库（P1 反思 / 踩坑复盘）：工具失败的记录，供模型反思避免重复犯错 */}
      <div className="mt-4 pt-3 border-t border-border/60">
        <div className="flex items-center justify-between">
          <div className="text-sm font-medium">{t("settings.reflectionsTitle")}</div>
          {reflections && reflections.length > 0 && (
            <Button variant="outline" size="sm" className="h-6 px-2 text-xs" onClick={() => {
              void clearReflections()
                .then(() => {
                  toast(t("settings.reflectionsCleared"), "ok");
                  void reload();
                })
                .catch((e) => toast(e instanceof Error ? e.message : String(e), "error"));
            }}>
              {t("settings.reflectionsClear")}
            </Button>
          )}
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground/70">{t("settings.reflectionsDesc")}</p>
        {reflections == null ? (
          <div className="mt-2 text-xs text-muted-foreground">{t("settings.loading")}</div>
        ) : reflections.length === 0 ? (
          <div className="mt-2 text-xs text-muted-foreground/70">{t("settings.reflectionsEmpty")}</div>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {reflections.map((r) => (
              <li key={r.id} className="flex items-start justify-between gap-2 rounded-lg border border-amber-400/30 bg-amber-50/40 px-2.5 py-1.5 text-sm">
                <span className="min-w-0 flex-1">
                  <span className="block break-words"><span className="font-mono text-xs text-amber-700">{r.tool}</span> · {r.lesson}</span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">{fmtDate(r.created_at)}</span>
                </span>
                <button
                  className="shrink-0 text-muted-foreground hover:text-green-600"
                  onClick={() => {
                    void resolveReflection(r.id)
                      .then(reload)
                      .catch((e) => toast(e instanceof Error ? e.message : String(e), "error"));
                  }}
                  aria-label={t("settings.reflectionsResolve")}
                  title={t("settings.reflectionsResolve")}
                >
                  <Check className="w-3.5 h-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Section>
  );
}
