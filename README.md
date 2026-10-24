# Xiaoman

> A conversation-first personal finance assistant. One sentence to record an expense, check quotes, manage positions, run a health check, or get your morning report.

![License](https://img.shields.io/badge/License-MIT-green.svg)
![Release](https://img.shields.io/github/v/release/badhope/xiaoman)
![CI](https://github.com/badhope/xiaoman/actions/workflows/ci.yml/badge.svg)
![Docker](https://img.shields.io/badge/docker-compose-blue)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)
![React](https://img.shields.io/badge/React-19-61DAFB.svg)
![LangGraph](https://img.shields.io/badge/LangGraph-1.x-1A2B4A.svg)

| 简体中文 | English |
|---|---|
| [README.zh.md](README.zh.md) | **README.md (current)** |

## 30-second start

```bash
docker compose up -d --build     # http://localhost:8787
```

```bash
# Or run locally (Python 3.10+ / Node 18+): one command — venv + pip install + SPA build + serve on 8788
scripts/dev.sh --prod
```

## Why Xiaoman

- **Every number comes from a deterministic engine** — the model only classifies intent and writes prose, so it cannot invent an amount.
- **Built for Chinese bills** — WeChat Pay, Alipay and bank CSV imports are native, not an afterthought.
- **Conversation is the operation** — one sentence records an expense, opens a position, or gets a rebalancing plan.
- **Your data stays on your machine** — local SQLite, with optional passphrase-protected encrypted backups.

## What it is

Xiaoman is one of the 24 solar terms — the moment when grain is nearly, but not yet, full. Personal finance works the same way: save a little every day and let life fill up at its own pace.

A finance assistant that runs on your own machine, with conversation as the core interaction:

| You say | Xiaoman does |
|---|---|
| "coffee 28, taxi 32" | Records two entries in one sentence |
| "salary 1w credited" | Records income 10000 (supports 万/w/k and Chinese numerals) |
| "check CATL, add to watchlist if good" | Quote → add to watchlist → visible on Market |
| "buy 100 shares of 600519" | Opens a position at the current price (asks for cost when quotes are unavailable) |
| "sell half of 600519" | Half-position sell, never an accidental full liquidation |
| "remember I pay rent 5000 next month" | Stored in long-term memory, auto-referenced in answers |
| "generate today's morning report" | Generated and archived |

The other tabs (Overview / Holdings / Strategy / Market / Ledger) are views of the conversation results, not duplicate form entries.

## Core features

- **100% local data**: everything lives in a local SQLite database. Optional passphrase-protected encrypted backups (PBKDF2 + Fernet); the passphrase is never stored.
- **Never fabricates numbers**: amounts, P&L and risk metrics are computed by a deterministic engine; the model only classifies and writes prose. At runtime the model only sees read-only tools.
- **Model-agnostic**: unified access via LiteLLM — DeepSeek / Doubao / Qwen / Claude / OpenAI / Gemini, with automatic failover. Fully usable without any model configured.
- **Multi-agent orchestration**: a LangGraph graph (supervisor pipeline), plus a "finance department mode" that splits one request into tickets, runs departments in parallel, and summarizes for approval.
- **MCP protocol**: all finance tools are exposed as a standard MCP Server via fastmcp — Claude Code / Cursor can query your local data directly.
- **Investment strategy engine**: portfolio risk metrics (volatility / Sharpe / Sortino / max drawdown / Beta / VaR) against a benchmark, target-allocation rebalancing, valuation percentile, DCA plans and FIRE progress.
- **Long-term memory**: preferences live in a local table and are recalled with BM25; memory never leaves the machine.
- **3-level quote fallback**: Eastmoney → Sina → local snapshot, clearly labeled when offline.
- **PWA**: installable on desktop and mobile.

## Interface

Two surfaces, each with a clear job:

- **Chat** is the entry point — record an expense, ask a question.
- **Finance workspace** follows stock-broker conventions: a list on the left, detail for the selected
  symbol on the right.

Navigation: a persistent session sidebar (chat) plus six top tabs
(Overview / Holdings / Strategy / Market / Ledger / Health). The main area switches pages; "Back to chat"
returns to the conversation.

| Width | Layout |
|---|---|
| ≥1280 | Session sidebar (drag to resize) + main area (chat centred at 48rem, finance pages at 1200px) |
| 768–1279 | Sidebar kept; finance two-column layouts collapse to one |
| <768 | Compact top bar + five bottom tabs (Chat / Finance / Holdings / Scheduled / Settings), rest in a drawer |

Highlights:
- Holdings: summary strip → concentration warnings → table + P&L contribution chart, with
  concentration / sector / risk columns on the right.
- Strategy: portfolio risk metrics and equity curve vs benchmark, rebalance checklist, valuation
  percentile, DCA plans and FIRE progress.
- Market: watchlist and holdings with 60-day sparklines, plus a detail panel (trend, period change,
  60-day high/low, full K-line).
- Ledger: one-sentence entry plus a standard transaction table.
- Health: score, five-dimension bars, a "fix first" list, and per-dimension advice.
- Settings uses a left nav with three groups on desktop and a horizontal segmented bar on mobile
  (Basics / AI & automation / Data & security).
- Sidebar width is remembered (localStorage), double-click the divider to reset; panels trap and
  restore focus, Esc closes.
- Only chat code loads on first paint; charts / department board / inbox are lazy-loaded.

Screenshots: `cd frontend && node scripts/ui-audit.mjs` (every page, into `out/ui-audit/`);
README images: `node scripts/readme-shots.mjs` (writes `docs/screenshots/`).

## Screenshots

| Chat | Answer: plan + snapshot + actions |
|---|---|
| ![Chat](docs/screenshots/01-chat-home.png) | ![Answer](docs/screenshots/02-chat-answer.png) |

| Overview | Holdings |
|---|---|
| ![Overview](docs/screenshots/03-overview.png) | ![Holdings](docs/screenshots/04-holdings.png) |

| Market: list + detail | Ledger |
|---|---|
| ![Market](docs/screenshots/05-market.png) | ![Ledger](docs/screenshots/06-ledger.png) |

| Health check | Settings |
|---|---|
| ![Health](docs/screenshots/07-health.png) | ![Settings](docs/screenshots/08-settings.png) |

| Command palette (Ctrl+K) | Dark mode |
|---|---|
| ![Command palette](docs/screenshots/10-command-palette.png) | ![Dark](docs/screenshots/11-dark-mode.png) |

| Mobile: chat | Mobile: finance |
|---|---|
| ![Mobile chat](docs/screenshots/12-mobile-chat.png) | ![Mobile finance](docs/screenshots/13-mobile-finance.png) |

| Investment strategy: risk / rebalance / valuation / DCA / FIRE |
|---|
| ![Strategy](docs/screenshots/14-strategy.png) |

More in [docs/screenshots/](docs/screenshots/).

## Quick start

Requirements: Python 3.10+, Node.js 18+.

**Fastest path (Docker)**

```bash
docker compose up -d --build   # single container, port 8787, volume xiaoman-data
```

**One-click (recommended for development)**

```bash
scripts/dev.sh        # Windows (Git Bash) / macOS / Linux — backend 8788 + frontend 5198
scripts/dev.sh --prod # production mode: build once, serve on a single port
start.bat             # Windows: creates the venv, installs deps, opens two windows
start.bat --prod      # Windows production mode: one window, one port
```

The scripts create the virtualenv, install dependencies and check port conflicts; they pick
`Scripts/` or `bin/` automatically per platform.

**Manual**

```bash
# Backend (run inside backend/)
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # optional: fill LLM_* to enable a model
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8788

# Frontend dev mode (/api proxied to 8788)
cd frontend
npm install && npm run dev    # http://127.0.0.1:5198

# Or production mode: build once, served by the backend on one port
cd frontend && npm run build  # then open http://127.0.0.1:8788
```

The database lives at `backend/data/wealth.db` by default (`XIAOMAN_DATA_DIR` / `XIAOMAN_DB_PATH` override it; empty values fall back to the default).

A fresh database starts empty with chat-style onboarding; everything works without an AI key.

## Tech stack

| Layer | Tech |
|---|---|
| Frontend | React 19 + Vite + Tailwind 4 · ECharts · TanStack Table · PWA |
| Backend | FastAPI + LangGraph multi-agent orchestration + deterministic engine |
| Data | SQLite (aiosqlite + WAL) · encrypted backups (PBKDF2 + Fernet) |
| AI | LiteLLM unified access · local BM25 long-term memory · fastmcp |
| Quotes | Eastmoney → Sina → local snapshot, 3-level fallback |

## Architecture

```mermaid
flowchart LR
    FE[React SPA] --> API[FastAPI REST + SSE + static hosting]
    API --> G[LangGraph orchestration, supervisor pipeline]
    API --> D[Finance department mode, parallel tickets]
    G --> T[Tool layer, 27 deterministic tools]
    D --> T
    T --> K[Deterministic engine, single source of truth]
    T --> DB[(Local SQLite)]
    T --> Q[3-level quote fallback]
    G --> L[LiteLLM model access]
    G --> M[local BM25 memory]
    API --> MCP[MCP Server /mcp · 36 tools]
```

Principle: **the framework orchestrates; the engine computes**. The model only appears at classification and finalization; any failure degrades to the deterministic path. Full architecture with diagrams: [docs/architecture.md](docs/architecture.md).

Key invariants:
- Write tools are invisible to the model (removed at both schema and implementation layers); the model cannot edit the ledger.
- Amounts, P&L and risk metrics are computed only by `analysis` / `calculations`.
- Long-term memory is fully local (BM25); memory content never leaves the machine.
- Confirmable write actions use atomic claiming (`claim_pending_action`), so a token executes exactly once.

## Repository layout

```
backend/app/
  main.py            FastAPI entry: REST + SSE + auth + static hosting
  db/                Data layer (domain modules): ledger / portfolio / budgets /
                     debts / goals / memory / history / audit / backup / users ...
  routes/            Routes: budgets / settings / goals / market / import ...
  agents/            Multi-agent config: supervisor / bookkeeping / portfolio
  agent_graph.py     LangGraph graph: supervisor + specialized nodes + routes
  department.py      Finance department mode: tickets → parallel → summary
  analysis.py        Deterministic engine: positions / cashflow / debt / risk
  calculations/      Portfolio risk / rebalance / valuation / DCA / FIRE models
  tools.py           Agent tool layer: 27 function-calling tools
  quotes.py          Quotes: Eastmoney → Sina → snapshot fallback + cache
  nlparse.py         One-sentence bookkeeping: rule engine + AI fallback
  llm.py             LiteLLM unified model access
  mem.py             long-term memory (local BM25, no network)
  mcp_server.py      MCP Server exposing finance tools
  backup.py          Local encrypted backup, passphrase never stored
frontend/src/
  App.tsx            Adaptive layout: resizable sidebar on desktop / bottom nav on mobile
  components/        ChatView / Dashboard / HoldingsView / MarketView ...
  lib/               api / store / i18n (zh+en) / charts / format
docs/                Deploy / config / workflow / architecture / planning
```

## Docs

| Doc | Contents |
|---|---|
| [Quick start](docs/quickstart.md) | Up and running in 5 minutes |
| [Deployment](docs/DEPLOY.en.md) | Local / Docker / external access / backup migration ([中文](docs/DEPLOY.md)) |
| [Configuration](docs/CONFIG.en.md) | Env vars + settings + AI endpoint cheat-sheet ([中文](docs/CONFIG.md)) |
| [Workflows](docs/WORKFLOW.en.md) | Every conversation pattern ([中文](docs/WORKFLOW.md)) |
| [Architecture](docs/architecture.md) | Mermaid diagrams + department mode + data reliability |
| [CLI](docs/cli.md) | `xiaoman add / ls / report / balance / ask` — offline-first, same commands in local or remote mode |
| [Module map](docs/module-map.md) | Every backend module: size, structure, responsibility |
| [Development guide](docs/DEVELOPMENT.en.md) | Code map + add-tool/setting tutorials + release flow ([中文](docs/DEVELOPMENT.md)) |
| [Progress](docs/PROGRESS.md) | What is done, what is left, in one page |
| [Roadmap](docs/ROADMAP-v3.md) | v3 direction → [detailed plan](docs/PLAN-DETAILED.md) |
| [Planning archive](docs/planning/) | Reviews / differentiation / research docs |
| [Changelog](CHANGELOG.md) | Full version history |

## Tests

```bash
# Backend: 906 tests (engine / strategy / quote fallback / agent loop / LangGraph / API / backup / MCP ...)
cd backend && .venv/bin/python -m pytest tests -q
cd backend && .venv/bin/python -m ruff check app tests

# Frontend: tsc + build + 111 unit tests + 21 Playwright e2e specs
cd frontend && npm run build
cd frontend && npm run test:e2e
```

CI covers backend ruff (app + xiaoman package) + pytest, frontend tsc + vitest + build,
plus a hygiene job: no files over 1MB, and `mkdocs build --strict` must pass.

## Data & privacy

- All personal data lives in local SQLite; quotes use public Eastmoney/Sina endpoints; model calls go only to the endpoint you configured.
- Encrypted backups recommended; plaintext export shows a strong warning. No telemetry, no tracking, no third-party analytics.
- Auth: when `API_TOKEN` is set, all `/api/*` require `Bearer` or `?token=`; without a token, only localhost and the `ALLOWED_HOSTS` allowlist are accepted.

## Disclaimer

Everything this software outputs (health checks, reports, AI answers, suggestions) is for reference only and does not constitute investment advice. Markets carry risk.

## Contributing

- License: [MIT](LICENSE) · [CONTRIBUTING.md](CONTRIBUTING.md) · [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) · [SECURITY.md](SECURITY.md)
- Issues and PRs welcome; please pair new features with tests and pass the test commands above before submitting.

**Topics**: `personal-finance` `finance-assistant` `ai-agent` `langgraph` `fastapi` `react` `sqlite` `local-first` `mcp` `pwa`
