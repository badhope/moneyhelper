# Development Guide (training)

> For developers touching the Moneyhelper repo for the first time. After this guide you should be able to: **run it → understand the architecture → change code (add a tool / setting / route) → write tests → ship a release**.

## 0. Run it in 10 minutes

```bash
# 0.1 Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # includes pytest / ruff / pytest-cov
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8788
# Open http://127.0.0.1:8788 (production frontend is built into dist)

# 0.2 Frontend (second terminal)
cd frontend && npm install && npm run dev     # http://127.0.0.1:5198

# 0.3 Tests & coverage
cd backend && .venv/bin/python -m pytest tests -q --cov=app          # baseline 75%+, 182 tests
cd backend && .venv/bin/python -m ruff check app tests               # lint
```

> No AI key? The app works end to end with deterministic templates. To enable a model, paste any OpenAI-compatible endpoint in Settings.

## 1. Code map (read these 6 first)

| File | Responsibility | Why read it first |
|---|---|---|
| `backend/app/main.py` | FastAPI routes / SSE / auth / static hosting | Entry point of all ~44 endpoints |
| `backend/app/db.py` | SQLite data layer (schema + migrations + all tables) | The only channel to persistence |
| `backend/app/analysis.py` | **Deterministic analysis engine** | The only source of numbers; AI never computes |
| `backend/app/agent_graph.py` | LangGraph orchestration (supervisor + nodes + conditional routes) | The full execution path of Q&A |
| `backend/app/service.py` | Routing classification + one-sentence bookkeeping + event contract | Main pipeline from input to answer |
| `backend/app/tools.py` | 17 function-calling tools (schema + bodies) | Agent tool layer; the read/write boundary |

Helpers: `quotes.py` (3-level quote fallback), `nlparse.py` (bookkeeping rules), `llm.py` (model client), `agent.py` (tool loop), `scheduler.py` (morning report), `backup.py` (encrypted backups).

### Data flow of one question

```
POST /api/ask (SSE)
  → service.run_question
      → agent_graph.supervisor branch:
          action  → deterministic actions (buy/sell/settings/report/backup)  [writes only here]
          memory  → store/query long-term memory                              [writes only here]
          record  → one-sentence bookkeeping (nlparse rules)                  [writes only here]
          general → agent tool loop (model gets read-only tools)
  → finalize → final event back to the frontend
```

**Iron rule**: data writes (bookkeeping / memory / buy-sell / settings / backup) exist **only** in deterministic pre-branches; the model never receives write tools in agent mode. Enforced by `WRITE_EXCLUDED` in `agent.py`.

## 2. Workshop: add an agent tool (6 steps)

Example: `get_watchlist_pnl` — let the model query a P&L ranking of the watchlist.

1. **Body**: add `async def tool_get_watchlist_pnl(args) -> str` in `tools.py`; use `db.list_watchlist()` + `analysis` — never invent numbers.
2. **Schema**: register in `TOOLS` as `{"type":"function","function":{"name":"get_watchlist_pnl","description":"…","parameters":…}}`.
3. **Exposure**: read-only tools go into `READ_TOOLS` automatically. If it writes, do NOT expose it to the model — put it in a deterministic branch (see §3).
4. **Test**: add a case in `tests/test_agent.py` (use the `temp_db` fixture + a mocked LLM), assert the return and tool name.
5. **Prompt**: mention the tool in the agent system prompt if the model should call it proactively.
6. **Regression**: `pytest tests/test_agent.py -q` then full `pytest tests -q`.

## 3. Workshop: add a write action (deterministic)

Writes must go through a deterministic path. Template: `run_action` in `tools.py`:

- Add the trigger word to `ACTION_WORDS` in `service.py` (e.g. `"分红"`)
- Add a branch in `run_action`: parse args → write via `db`/`analysis` → return `{"answer":…, "level":"已执行", "route":"action", …}`
- Add tests for "normal", "missing args", "quotes unreachable".

## 4. Workshop: add a setting

1. **Backend**: add a validation branch in `PUT /api/settings` (`main.py`); add the key to `SETTING_KEYS_ALLOWED` in `tools.py`; sync a line in `docs/CONFIG.md` and the `.en` version.
2. **Frontend**: add the control in `components/SettingsView.tsx`; add copy in `lib/lang/zh.ts` / `en.ts`.
3. **Test**: add "valid value applies / invalid value rejected" cases in `tests/test_api.py`.

## 5. Generic test pattern

```python
# tests/conftest.py provides temp_db (in-memory DB + seed data, per-test isolation)
async def test_xxx(temp_db, monkeypatch):
    # mock external deps (quotes/LLM) — never hit the network
    monkeypatch.setattr(tools, "quote_now", fake_quote)
    out = await tools.run_action("买入 600519 100 股")
    assert out["level"] == "已执行"
    pos = await db.list_positions()
    ...
```

- Network-dependent code (quotes/model) is always mocked: `tests/test_agent.py` uses `httpx.MockTransport`, `tests/test_quotes.py` uses monkeypatch.
- Assert "no misclassification": e.g. "remember…" must go to memory, not bookkeeping — test both routes.
- Secret scan: `tests/test_secrets.py` guarantees no credentials leak into the repo.

## 6. Debugging cheat-sheet

| Symptom | What to check |
|---|---|
| No answer / SSE interrupted | `tail /tmp/xm_run.log`; `curl -N -X POST /api/ask -d '{"thread_id":"t1","question":"…"}'` and watch the event stream |
| Quote timeout in sandbox | Sandbox cannot reach Eastmoney/Sina — environment, not a bug; on a normal network it works. Check the `source` field of `GET /api/dashboard` for snapshot fallback |
| Weird model behavior | Check `ai_*` settings via `GET /api/settings`; confirm the endpoint supports streaming + function calling |
| Wanted to reset data | `rm -rf backend/data` then restart (empty-state onboarding shows) |
| Frontend copy/style | `npm run dev` hot-reload; change both `lib/lang/zh.ts` and `en.ts` |

## 7. Release flow

```bash
# 1) Quality gate
cd backend && .venv/bin/python -m pytest tests -q --cov=app   # all green
cd backend && .venv/bin/python -m ruff check app tests        # 0 errors
cd frontend && npm run build                                   # tsc + vite
# 2) Version
#    bump backend/app/__init__.py __version__; update CHANGELOG.md
# 3) Commit & tag
git add -A && git commit -m "feat: xxx"
git tag v1.0.0 && git push origin main --tags
# 4) Multi-platform release (example)
git push https://<user>:<token>@gitcode.com/<org>/moneyhelper.git main --tags
git push https://<user>:<token>@gitee.com/<org>/moneyhelper.git main --tags
git push https://<user>:<token>@github.com/<org>/moneyhelper.git main --tags
```

## 8. Design constraints (code-review checklist)

- [ ] Numbers come from `analysis.py` or real quotes/inputs — the model never produces numbers
- [ ] Writes only in `action/memory/record` deterministic branches; the agent toolset is read + watchlist only
- [ ] External failure (quotes/LLM) → graceful degradation, service never breaks, never fakes results
- [ ] New setting: backend validation + whitelist + bilingual copy + docs in three places
- [ ] New API: auth-compatible (Bearer when `API_TOKEN` set), Chinese error messages
- [ ] Tests never hit the network, per-test isolation; "no misclassification" paths (bookkeeping vs memory vs action) each have a test
