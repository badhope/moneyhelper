/** 远程控制 API：配对链接、二维码、设备会话与撤销。 */

import { api } from "./client";

export interface RemoteSession {
  sid: string;
  label: string;
  device_name: string;
  device_ua: string;
  device_ip: string;
  created_at: string;
  pair_expires_at: string;
  paired_at: string;
  last_seen_at: string;
  expires_at: string;
  revoked_at: string;
  paired: boolean;
  revoked: boolean;
  expired: boolean;
  active: boolean;
}

export interface RemoteConfig {
  enabled: boolean;
  public_url: string;
  session_hours: number;
  base_url: string;
  warning: string;
  qr_available: boolean;
  sessions: RemoteSession[];
  active_count: number;
}

export interface RemoteLink extends RemoteSession {
  pair_url: string;
  qr_svg: string;
  base_url: string;
  warning: string;
}

export interface RemoteMe {
  remote: boolean;
  sid?: string;
  user_id?: number;
  label?: string;
  device_name?: string;
  paired_at?: string;
  expires_at?: string;
}

export const getRemoteConfig = () => api<RemoteConfig>("/api/remote/config");

export const updateRemoteConfig = (patch: {
  public_url?: string;
  session_hours?: number;
  enabled?: boolean;
}) =>
  api<RemoteConfig>("/api/remote/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });

export const createRemoteSession = (body: { label?: string; hours?: number } = {}) =>
  api<RemoteLink>("/api/remote/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const refreshRemoteSession = (sid: string) =>
  api<RemoteLink>(`/api/remote/sessions/${encodeURIComponent(sid)}/refresh`, {
    method: "POST",
  });

export const stopRemoteSession = (sid: string) =>
  api<{ ok: boolean }>(`/api/remote/sessions/${encodeURIComponent(sid)}/stop`, {
    method: "POST",
  });

export const stopAllRemoteSessions = () =>
  api<{ ok: boolean; revoked: number }>("/api/remote/stop-all", { method: "POST" });

export const getRemoteMe = () => api<RemoteMe>("/api/remote/me");

export const disconnectRemote = () =>
  api<{ ok: boolean }>("/api/remote/disconnect", { method: "POST" });

/** 配对入口不走 api()：手机上还没有任何本地令牌，也不需要 401 口令框。 */
export async function pairRemote(sid: string, token: string): Promise<{ redirect: string; device_name: string }> {
  const resp = await fetch("/api/remote/pair", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sid, token }),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(body?.error || `配对失败（HTTP ${resp.status}）`);
  }
  return body;
}
