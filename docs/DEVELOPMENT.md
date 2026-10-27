# 开发指南（培训用）

> 目标读者：第一次接触 Moneyhelper 仓库的开发者/实习生。读完本指南，你应该能：**跑起来 → 看懂架构 → 改代码（加工具/加设置/加路由）→ 写测试 → 发版本**。

## 提交前检查

```bash
./scripts/lint.sh                      # ruff（app/tests + moneyhelper 两处，与 CI 一致）
cd backend && .venv/bin/python -m pytest tests -q
cd frontend && npx tsc --noEmit && npx vitest run
```

`scripts/lint.sh` 存在的意义：CI 查两处（`backend/app`+`tests` 与根目录 `moneyhelper/`），
本地只跑一处会漏。历史上漏过一次，CI 才报出来。

## 0. 一次跑通（10 分钟）

```bash
# 0.1 后端
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # 含 pytest / ruff / pytest-cov
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8788
# 浏览器打开 http://127.0.0.1:8788 （生产模式前端已构建进 dist？没有则先 build）

# 0.2 前端（另一个终端）
cd frontend && npm install && npm run dev     # http://127.0.0.1:5198

# 0.3 测试与覆盖率
cd backend && .venv/bin/python -m pytest tests -q --cov=app          # 基线 75%+，182 用例
cd backend && .venv/bin/python -m ruff check app tests               # lint
```

> 不想配 AI 也能完整体验：未配置时问答走内置确定性模板。要配模型，在设置页填任一 OpenAI 兼容端点即可。

## 1. 代码地图（先读这 6 个文件）

| 文件 | 职责 | 为什么先读它 |
|---|---|---|
| `backend/app/main.py` | FastAPI 路由 / SSE / 鉴权 / 静态托管 | 一切 API 的入口，约 44 个端点 |
| `backend/app/db.py` | SQLite 数据层（schema + 迁移 + 全部表读写） | 所有持久化的唯一通道 |
| `backend/app/analysis.py` | **确定性分析内核** | 所有数字的唯一计算源，AI 不算数 |
| `backend/app/agent_graph.py` | LangGraph 编排图（supervisor + 节点 + 条件路由） | 问答的完整执行路径 |
| `backend/app/service.py` | 路由分类 + 一句话记账 + 事件契约 | 对话从输入到输出的主干 |
| `backend/app/tools.py` | 17 个 function calling 工具（schema + 执行体） | agent 工具层，读写边界在这里 |

辅助文件：`quotes.py`（行情三级降级）、`nlparse.py`（一句话记账规则）、`llm.py`（模型接入）、`agent.py`（工具循环）、`scheduler.py`（定时晨报）、`backup.py`（加密备份）。

### 一次问答的数据流

```
POST /api/ask (SSE)
  → service.run_question
      → agent_graph.supervisor 判定分支：
          action  → 确定性动作（买卖/设置/晨报/备份）   [写操作只走这里]
          memory  → 存/查长期记忆                      [写操作只走这里]
          record  → 一句话记账（nlparse 规则）          [写操作只走这里]
          general → agent 工具循环（模型只读）          [模型只拿读类工具]
  → 成文 → final 事件流回前端
```

**铁律**：写数据（记账/记忆/买卖/设置/备份）**只允许**出现在确定性前置分支；agent 模式的模型永远拿不到写类工具。这条规则由 `agent.py` 的 `WRITE_EXCLUDED` 强制。

## 2. 实战：加一个 agent 工具（6 步）

以「查自选盈亏排行」为例——你想让模型能调用 `get_watchlist_pnl`。

1. **执行体**：在 `tools.py` 加 `async def tool_get_watchlist_pnl(args) -> str`，返回可读文本；用 `db.list_watchlist()` + `analysis` 计算，**不要自己造数字**。
2. **schema**：在 `tools.py` 的 `TOOLS` 列表注册 `{"type":"function","function":{"name":"get_watchlist_pnl","description":"…","parameters":…}}`。
3. **暴露范围**：读类工具自动进入 `agent.py` 的 `READ_TOOLS`；若它要写数据，**不要**加进 `WRITE_EXCLUDED` 白名单外，而是放进某个确定性分支（见第 3 节）。
4. **测试**：在 `tests/test_agent.py` 加用例（用 `temp_db` fixture 与 mock LLM），断言返回值与工具名。
5. **提示词**：如需模型主动调用，在 `agent.py` 的 system 提示里提一句该工具用途。
6. **回归**：`pytest tests/test_agent.py -q` + 全量 `pytest tests -q`。

## 3. 实战：加一个写操作（确定性分支）

写操作必须走确定性路径，模板参考 `tools.py` 的 `run_action`：

- 在 `service.py` 的 `ACTION_WORDS` 加触发词（如 `"分红"`）
- 在 `run_action` 加分支：解析参数 → 调 `db`/`analysis` 落库 → 返回 `{"answer":…, "level":"已执行", "route":"action", …}`
- 加测试覆盖「正常」「缺参数」「行情不可达」三种情况

## 4. 实战：加一个设置项

1. **后端**：`main.py` 的 `PUT /api/settings` 加校验分支（枚举/数值/格式）；`tools.py` 的 `SETTING_KEYS_ALLOWED` 加键；`docs/CONFIG.md` 与英文版同步补一行。
2. **前端**：`components/SettingsView.tsx` 加表单控件；`lib/lang/zh.ts` / `en.ts` 加文案。
3. **测试**：`tests/test_api.py` 加「合法值生效/非法值拒绝」用例。

## 5. 写测试的通用模式

```python
# tests/conftest.py 提供 temp_db（内存库 + 种子数据，函数级隔离）
async def test_xxx(temp_db, monkeypatch):
    # mock 外部依赖（行情/LLM）用 monkeypatch，不触网
    monkeypatch.setattr(tools, "quote_now", fake_quote)
    out = await tools.run_action("买入 600519 100 股")
    assert out["level"] == "已执行"
    pos = await db.list_positions()
    ...
```

- 网络类（行情/模型）一律 mock：`tests/test_agent.py` 用 `httpx.MockTransport`，`tests/test_quotes.py` 用 monkeypatch。
- 断言「不误伤」：如「记住…」必须存记忆而非记账——两个路由各测一遍。
- 密钥扫描：`tests/test_secrets.py` 保证仓库无凭据残留。

## 6. 调试技巧

| 现象 | 排查 |
|---|---|
| 问答没反应 / SSE 中断 | `tail /tmp/xm_run.log`；`curl -N -X POST /api/ask -d '{"thread_id":"t1","question":"…"}'` 看事件流 |
| 沙箱行情超时 | 沙箱访问不了东财/新浪是**环境问题非 bug**；本地网络正常。观察 `GET /api/dashboard` 的 `source` 字段是否降级为 snapshot |
| 模型行为异常 | 检查 `GET /api/settings` 的 `ai_*` 配置；确认端点支持流式 + function calling |
| 数据写错想重置 | `rm -rf backend/data` 后重启（空库首启，各页有空态引导） |
| 前端样式/文案 | `npm run dev` 热更新；中英文都改（`lib/lang/zh.ts` + `en.ts`） |

## 7. 发布流程

```bash
# 1) 质量门
cd backend && .venv/bin/python -m pytest tests -q --cov=app   # 全绿
cd backend && .venv/bin/python -m ruff check app tests        # 0 错误
cd frontend && npm run build                                   # tsc + vite
# 2) 版本
#    更新 backend/app/__init__.py 的 __version__；更新 CHANGELOG.md
# 3) 提交与打 tag
git add -A && git commit -m "feat: xxx"
git tag v1.0.0 && git push origin main --tags
# 4) 多平台发布（示例）
git push https://<user>:<token>@gitcode.com/<org>/moneyhelper.git main --tags
git push https://<user>:<token>@gitee.com/<org>/moneyhelper.git main --tags
git push https://<user>:<token>@github.com/<org>/moneyhelper.git main --tags
```

## 8. 设计约束速查（评审代码时对照）

- [ ] 数字来自 `analysis.py` 或真实行情/输入，**模型不产数字**
- [ ] 写操作只出现在 `action/memory/record` 确定性分支；`agent` 模型工具集只含读类 + 自选维护
- [ ] 外部失败（行情/LLM）→ 自动降级，服务不中断、不冒充结果
- [ ] 新设置项：后端校验 + 白名单 + 双语文案 + 文档三处同步
- [ ] 新 API：带鉴权兼容（`API_TOKEN` 时 Bearer）、错误响应有中文提示
- [ ] 测试不触网、函数级隔离；「不误伤」路径（记账 vs 记忆 vs 动作）各有一测
