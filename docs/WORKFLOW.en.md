# Conversation Workflow Guide (conversation is the hub)

Ask AI is the center of Moneyhelper: bookkeeping, quotes, holdings, reports, backups and settings all happen with one sentence in the chat; the other 4 tabs are views of the conversation results. On a fresh install the first screen directly lists the capability cards — just say what's on them.

## 1. One-sentence bookkeeping

| You say | Result |
|---|---|
| "coffee 28" | Expense recorded (rule-fast, no model call) |
| "salary 1w credited" | Income 10000 recorded (supports 万/w/k and Chinese numerals) |
| "coffee 28, taxi 32" | Multi-entry bookkeeping in one sentence, each entry recorded |
| "taxi 32 yesterday" | Recorded with yesterday's date |

> If rules can't parse it, the model fallback kicks in; the reply shows "Recorded …" with delete guidance. Questions ("I want to start investing") never get mis-booked.

## 2. Market & watchlist

| You say | Result |
|---|---|
| "check CATL" | Live quote / change (`get_quote`) |
| "add CATL to my watchlist" | Added (`add_to_watchlist`), instantly visible on Market |
| "how's my watchlist?" | Watchlist summary |
| "analyze 600519" | K-line + market snapshot + risk analysis |

## 3. Holdings

| You say | Result |
|---|---|
| "buy 100 shares of 600519" | Position opened at current price (asks for cost when quotes unavailable) |
| "sell half of 600519" | Half-position sell (recognizes 一半/半仓/减半) |
| "how are my holdings?" | Market value / P&L / concentration analysis + jump to Holdings |

## 4. Report / backup / checkup

| You say | Result |
|---|---|
| "generate today's morning report" / "morning report" | L1 insight / L2 advice report, archived |
| "back up now" | Local encrypted backup (one-time passphrase shown) |
| "run a full health check" | 5-dimension check (emergency fund / debt / concentration / savings rate / budget) |

## 5. Memory & settings

| You say | Result |
|---|---|
| "remember I pay rent 5000 next month" | Stored to long-term memory (takes priority over bookkeeping) |
| "set default home to Holdings" | Setting changed + jump to Settings |
| "switch colors to green-up/red-down" | `color_scheme=us` applied |
| "switch the UI to English" | `lang=en` applied |

## 6. Follow-up continuity

After a finance-related round, omitted follow-ups are auto-continued (e.g. "what about last month?" → last month's ledger analysis). The model only gets read-only tools here — it can never write to your data.

## 7. A complete end-to-end workflow

> "Check Kweichow Moutai and add it to my watchlist if it looks good" → "I bought 100 shares at 1500"

The model orchestrates `search_symbol → get_quote → get_kline → add_to_watchlist`, then the "buy" action opens the position at cost 1500 via `record_position` — finding the symbol, viewing quotes, adding the watchlist, and storing the position, all in the conversation. The Market watchlist, Overview and Holdings update instantly; every number comes from the deterministic engine or a real quote source — never fabricated.

## Security boundary

- The agent tool loop only exposes **read + watchlist maintenance** tools; bookkeeping / memory / buy-sell / settings / backup / report are all intercepted by deterministic front-end branches — the model can never silently change your data.
- Every answer carries a source badge (rule / deterministic / model); when AI is unconfigured or fails, it degrades automatically and the service never breaks.
