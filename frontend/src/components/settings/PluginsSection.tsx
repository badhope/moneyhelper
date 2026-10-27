import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, Plug, Plus, RefreshCw, Trash2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { Section, inputCls, labelCls } from "./shared";

interface McpServer {
  name: string;
  url: string;
  transport?: "http" | "stdio";
  command?: string;
  args?: string[];
  enabled?: boolean;
  tools: string[];
}

/**
 * MCP 插件：外部工具服务器（Claude Code / Cursor 用的同一套协议）。
 *
 * 支持两种传输：StreamableHTTP（url）与 stdio（command + args，本地进程）。
 * 支持逐台启用/停用（停用只保留配置不参与发现，避免离线环境反复超时）。
 * 凭据（URL 里的 user:token）由后端打码后回显。
 */
export function PluginsSection() {
  const { t } = useI18n();
  const { toast } = useToast();
  const qc = useQueryClient();
  const [transport, setTransport] = useState<"http" | "stdio">("http");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  const list = useQuery({
    queryKey: ["/api/mcp/servers"],
    queryFn: () => api<{ servers: McpServer[] }>("/api/mcp/servers").then((r) => r.servers ?? []),
  });
  const servers = list.data ?? [];

  const save = async (next: McpServer[]) => {
    setSaving(true);
    try {
      await api("/api/mcp/servers", {
        method: "PUT",
        body: JSON.stringify({
          servers: next.map((s) => ({
            name: s.name,
            url: s.url,
            command: s.command,
            args: s.args,
            enabled: s.enabled !== false,
          })),
        }),
      });
      await qc.invalidateQueries({ queryKey: ["/api/mcp/servers"] });
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setSaving(false);
    }
  };

  const add = async () => {
    const n = name.trim();
    if (!n) return;
    if (servers.some((s) => s.name === n)) {
      toast(t("plugins.nameTaken"), "error");
      return;
    }
    if (transport === "http" && !url.trim()) return;
    if (transport === "stdio" && !command.trim()) return;
    const entry: McpServer =
      transport === "http"
        ? { name: n, url: url.trim(), enabled: true, tools: [] }
        : {
            name: n,
            url: "",
            command: command.trim(),
            args: args
              .split(/\s+/)
              .map((x) => x.trim())
              .filter(Boolean),
            enabled: true,
            tools: [],
          };
    await save([...servers, entry]);
    setName("");
    setUrl("");
    setCommand("");
    setArgs("");
    toast(t("plugins.saved"), "ok");
  };

  const test = async () => {
    if (transport === "http" && !url.trim()) return;
    if (transport === "stdio" && !command.trim()) return;
    setTesting(true);
    try {
      const r = await api<{ tools: string[] }>("/api/mcp/test", {
        method: "POST",
        body: JSON.stringify({
          url: transport === "http" ? url.trim() : "",
          command: transport === "stdio" ? command.trim() : "",
          args: transport === "stdio" ? args.split(/\s+/).filter(Boolean) : [],
        }),
      });
      toast(t("plugins.testOk", { n: (r.tools ?? []).length }), "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setTesting(false);
    }
  };

  const toggle = async (s: McpServer) => {
    await save(servers.map((x) => (x.name === s.name ? { ...x, enabled: !s.enabled } : x)));
  };

  return (
    <Section
      title={t("settings.navPlugins")}
      icon={<Plug className="w-4 h-4 text-muted-foreground" />}
      desc={t("plugins.desc")}
    >
      <div className="space-y-3">
        <div className="flex items-center gap-1.5">
          {(["http", "stdio"] as const).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={transport === v}
              onClick={() => setTransport(v)}
              className={
                transport === v
                  ? "rounded-md bg-primary px-2.5 py-1 text-[11px] text-primary-foreground"
                  : "rounded-md bg-muted px-2.5 py-1 text-[11px] text-muted-foreground hover:text-foreground"
              }
            >
              {v === "http" ? t("plugins.http") : t("plugins.stdio")}
            </button>
          ))}
        </div>

        <div className="grid gap-2 sm:grid-cols-[10rem_minmax(0,1fr)]">
          <div>
            <label className={labelCls}>{t("plugins.name")}</label>
            <input
              className={inputCls}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="my-server"
              maxLength={40}
            />
          </div>
          {transport === "http" ? (
            <div>
              <label className={labelCls}>{t("plugins.url")}</label>
              <input
                className={inputCls}
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://example.com/mcp"
                spellCheck={false}
              />
            </div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              <div>
                <label className={labelCls}>{t("plugins.command")}</label>
                <input
                  className={inputCls}
                  value={command}
                  onChange={(e) => setCommand(e.target.value)}
                  placeholder="npx / uvx / python"
                  spellCheck={false}
                />
              </div>
              <div>
                <label className={labelCls}>{t("plugins.args")}</label>
                <input
                  className={inputCls}
                  value={args}
                  onChange={(e) => setArgs(e.target.value)}
                  placeholder="-y @modelcontextprotocol/server-memory"
                  spellCheck={false}
                />
              </div>
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => void add()} disabled={saving || !name.trim()}>
            <Plus className="h-3.5 w-3.5" /> {t("plugins.add")}
          </Button>
          <Button size="sm" variant="outline" onClick={() => void test()} disabled={testing}>
            {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            {t("plugins.test")}
          </Button>
          <span className="text-[11px] text-muted-foreground">{t("plugins.hint")}</span>
        </div>

        {list.isPending ? (
          <p className="py-4 text-center text-xs text-muted-foreground">{t("plugins.loading")}</p>
        ) : servers.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-xs text-muted-foreground">
            {t("plugins.empty")}
          </div>
        ) : (
          <ul className="space-y-2">
            {servers.map((s) => (
              <li key={s.name} className="rounded-lg border border-border px-3 py-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5 text-sm font-medium">
                      {s.tools.length > 0 ? (
                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                      ) : (
                        <XCircle className="h-3.5 w-3.5 text-muted-foreground" />
                      )}
                      {s.name}
                      <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                        {s.transport ?? "http"}
                      </span>
                      {s.enabled === false && (
                        <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-600">
                          {t("plugins.disabled")}
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">
                      {s.transport === "stdio" ? `${s.command} ${(s.args ?? []).join(" ")}` : s.url}
                    </div>
                    {s.tools.length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {s.tools.slice(0, 8).map((tool) => (
                          <span
                            key={tool}
                            className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
                          >
                            {tool}
                          </span>
                        ))}
                        {s.tools.length > 8 && (
                          <span className="text-[10px] text-muted-foreground">+{s.tools.length - 8}</span>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      type="button"
                      aria-label={t("plugins.remove", { name: s.name })}
                      className="rounded p-1.5 text-muted-foreground hover:bg-red-500/10 hover:text-red-600"
                      onClick={() => void save(servers.filter((x) => x.name !== s.name))}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                    <Switch
                      checked={s.enabled !== false}
                      onChange={() => void toggle(s)}
                      label={`${t("plugins.toggle")} ${s.name}`}
                    />
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}

        <p className="text-[11px] leading-relaxed text-muted-foreground">{t("plugins.writeGuard")}</p>
      </div>
    </Section>
  );
}
