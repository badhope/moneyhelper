import { useState } from "react";
import { motion } from "framer-motion";
import { UserPlus, LogIn, Eye, EyeOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { FieldError } from "@/components/ui/field-error";
import { api, setToken } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { BrandLogo, BRAND } from "@/lib/brand";

type Mode = "login" | "register";

export function LoginView({ onAuthed }: { onAuthed: () => void }) {
  const { t } = useI18n();
  const { toast } = useToast();
  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      if (mode === "login") {
        const r = await api<{ access_token: string; user: { username: string; display_name: string } }>(
          "/api/auth/login",
          { method: "POST", body: JSON.stringify({ username, password }) },
        );
        setToken(r.access_token);
        toast(`欢迎回来，${r.user.display_name || r.user.username}！`, "ok");
      } else {
        const r = await api<{ access_token: string }>(
          "/api/auth/register",
          { method: "POST", body: JSON.stringify({ username, password, display_name: displayName }) },
        );
        setToken(r.access_token);
        toast(t("auth.registerOk"), "ok");
      }
      onAuthed();
    } catch (ex) {
      const msg = ex instanceof Error ? ex.message : String(ex);
      setErr(msg.includes("401") ? "用户名或密码错误"
        : msg.includes("409") ? "该用户名已被注册"
        : msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4 relative overflow-hidden">
      {/* 品牌光晕背景 */}
      <div className="pointer-events-none absolute inset-0" aria-hidden="true">
        <div className="absolute -top-20 left-1/2 -translate-x-1/2 h-72 w-[36rem] rounded-full bg-primary/[0.07] blur-3xl" />
        <div className="absolute -bottom-32 -right-20 h-80 w-80 rounded-full bg-brand-gold/[0.06] blur-3xl" />
      </div>
      <motion.div
        initial={{ opacity: 0, y: 20, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.3, ease: "easeOut" }}
        className="w-full max-w-sm"
      >
        {/* Logo + 标题 */}
        <motion.div
          className="mb-6 text-center"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05, duration: 0.3 }}
        >
          <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/8 shadow-soft ring-1 ring-primary/15">
            <BrandLogo size={42} />
          </div>
          <h1 className="text-xl font-semibold text-foreground">{BRAND.name}</h1>
          <p className="mt-1.5 text-sm text-muted-foreground text-balance">
            {mode === "login" ? t("auth.loginSubtitle") : t("auth.registerSubtitle")}
          </p>
        </motion.div>

        {/* Tab 切换 */}
        <div className="mb-4 flex rounded-lg bg-muted p-1">
          <button
            type="button"
            onClick={() => { setMode("login"); setErr(""); }}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-md py-2 text-sm font-medium transition-all ${
              mode === "login" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <LogIn className="h-3.5 w-3.5" />
            {t("auth.login")}
          </button>
          <button
            type="button"
            onClick={() => { setMode("register"); setErr(""); }}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-md py-2 text-sm font-medium transition-all ${
              mode === "register" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <UserPlus className="h-3.5 w-3.5" />
            {t("auth.register")}
          </button>
        </div>

        {/* 表单 */}
        <form onSubmit={submit} className="space-y-3 rounded-xl border border-border bg-card p-5 shadow-sm">
          {mode === "register" && (
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                {t("auth.displayName")}
              </label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder={t("auth.displayNamePh")}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
              />
            </div>
          )}

          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t("auth.username")}
            </label>
            <input
              type="text"
              required
              minLength={3}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder={t("auth.usernamePh")}
              autoComplete="username"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t("auth.password")}
            </label>
            <div className="relative">
              <input
                type={showPwd ? "text" : "password"}
                required
                minLength={6}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={mode === "register" ? t("auth.passwordPh") : "••••••"}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                className="w-full rounded-md border border-input bg-background px-3 py-2 pr-9 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
              />
              <button
                type="button"
                tabIndex={-1}
                onClick={() => setShowPwd(!showPwd)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                {showPwd ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          {err && <FieldError>{err}</FieldError>}

          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "…" : mode === "login" ? t("auth.login") : t("auth.register")}
          </Button>
        </form>

        <p className="mt-4 text-center text-xs text-muted-foreground">
          {t("auth.localOnly")}
        </p>
        <p className="mt-1 text-center text-[11px] text-muted-foreground/60">
          {mode === "login" ? "" : "注册即代表同意 MIT 开源协议与本地存储条款"}
        </p>
      </motion.div>
    </div>
  );
}
