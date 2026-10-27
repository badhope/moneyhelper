# Configuration Reference (env vars + app settings)

Moneyhelper has two layers of configuration: **environment variables** (before startup, `backend/.env`, copied from `.env.example`) and **app settings** (at runtime, Settings page, persisted to the SQLite `settings` table, applied immediately).

## 1. Environment variables (backend/.env)

All optional; the app runs fully without them (deterministic templates back everything — bookkeeping, analysis and reports all work without AI).

| Variable | Default | Description |
|---|---|---|
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible endpoint. CN presets: DeepSeek / Doubao (Volcano Ark) / Qwen / Unisound (see cheat-sheet below) |
| `LLM_API_KEY` | empty | Model key; or leave empty and fill it in the Settings page after startup |
| `LLM_MODEL` | `deepseek-chat` | Model name |
| `API_TOKEN` | empty | Access token. Empty = no auth (localhost/LAN only); set → every `/api/*` requires Bearer/`?token=`, frontend shows a passcode dialog |
| `ALLOWED_HOSTS` | empty | Extra hosts allowed when no token is set (comma-separated). Localhost only by default |
| `CORS_ALLOW_ALL` | empty | Debug: allow the frontend dev origin (`1`). Not needed for same-origin production |
| `MONEYHELPER_TRUST_PROXY` | empty | `1` = behind a trusted reverse proxy; login throttling reads the real client IP from `X-Forwarded-For`. Leave unset when the port is directly exposed (the header is spoofable) |

> Compatibility: the legacy `XIAOMAN_*` prefix is still read (`MONEYHELPER_*` wins) so existing deployments upgrade without switching to an empty ledger; new deployments should use the new prefix.

> Note: AI settings in the app (Settings page → `ai_base_url` / `ai_api_key` / `ai_model` / `ai_enabled`) take priority over env vars once saved; they survive restarts.

## 2. App settings (Settings page, persisted)

| Setting | Key | Values | Description |
|---|---|---|---|
| Default home | `default_tab` | `chat` (default) / `overview` / `holdings` / `market` / `ledger` | Landing tab on startup/refresh |
| Color scheme | `color_scheme` | `cn` (red-up/green-down, default) / `us` (green-up/red-down) | Global up/down colors, instant switch |
| Language | `lang` | `zh` / `en` | Full UI bilingual (empty states, capability list, settings included) |
| Number format | `compact_numbers` | `on` / `off` | Large amounts shown as 1.3万 / 1.3M |
| Quick suggestions | `show_suggestions` | `on` / `off` | Quick chips under the chat input |
| Auto refresh | `auto_refresh` / `auto_refresh_seconds` | `on`/`off` / seconds (default 300) | Overview quote polling |
| Show export | `show_export` | `on` / `off` | Show the export entry |
| Expand process | `expand_process` | `on` / `off` | Auto-expand/collapse the agent tool steps in chat |
| Voice input | `voice_input` | `on` / `off` | Voice input toggle |
| Monthly income | `monthly_income` | number | Basis for budget / savings rate / emergency fund |
| Emergency target | `emergency_target_months` | number (default 6) | Target months of coverage |
| Essential categories | `essential_categories` | comma-separated (default 居住,餐饮,交通) | Budget/over-spend analysis scope |
| Monthly budget | `budgets` (API) | array `[{category,amount}]`; `__total` for the total | Settings → Budget; live progress on Overview |
| Financial goals | `goals` (API) | `{name, target, note}` | Settings → Ledger Rules → Goals |
| Report time | `report_time` | `HH:MM` (default 08:00) | Daily morning report time |
| Quote source | `quote_source_mode` | `auto` (default) / `eastmoney` / `sina` / `snapshot` | 3-level fallback; `snapshot` uses only the local snapshot price |
| Access token | — | see `API_TOKEN` | Settings → Access Passcode (Bearer auth + 401 dialog) |
| Long-term memory | `memory` (API) | text entries | Settings → Long-term Memory; referenced first in Q&A |

## 3. AI endpoint cheat-sheet (China-first)

| Provider | Base URL | Example model | Notes |
|---|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` | Default preset |
| Doubao (Volcano Ark) | `https://ark.cn-beijing.volces.com/api/v3` | inference endpoint ID | Requires enabling an endpoint first |
| Qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | |
| Unisound | `https://maas-api.unisound.com/v1` | `u2-flash` | Streaming + tool loop verified |

Model requirements: OpenAI-compatible `/chat/completions`, supporting **streaming (SSE)** and **function calling** (required for the tool loop). If unsupported, the app degrades to the deterministic path — the service never breaks.

## 4. Change validation

- Settings writes go through `PUT /api/settings` validation: numeric ranges, on/off enums, `HH:MM` format, quote-source enum, URL prefixes, etc. Invalid items are reported one by one; valid items apply one by one.
- Backup passphrases are never persisted and never appear in plaintext exports; plaintext export shows a strong warning.
