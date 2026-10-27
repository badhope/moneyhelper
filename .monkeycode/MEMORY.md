# User Instruction Memory

This file records user instructions, preferences, and teachings for reference in future interactions.

## Format

### User Instruction Entry
User instruction entries should follow this format:

[User Instruction Summary]
- Date: [YYYY-MM-DD]
- Context: [Mentioned scenario or time]
- Instructions:
  - [Content of user teaching or instruction, described line by line]

### Project Knowledge Entry
Entries discovered by the Agent during task execution should follow this format:

[Project Knowledge Summary]
- Date: [YYYY-MM-DD]
- Context: Discovered by Agent while performing [specific task description]
- Category: [Operations & Deployment|Build Methods|Testing Methods|Troubleshooting & Debugging|Workflow & Collaboration|Environment Configuration]
- Instructions:
  - [Specific knowledge points, described line by line]

## Deduplication Strategy
- Before adding a new entry, check for similar or identical instructions.
- If a duplicate is found, skip the new entry or merge it with the existing one.
- When merging, update the context or date information.
- This helps avoid redundant entries and keeps the memory file tidy.

## Entries

[Multi-Platform Git Sync - moneyhelper]
- Date: 2026-10-18
- Context: 用户提供了 5 个代码托管平台凭据，要求克隆 moneyhelper 项目并后续在 5 平台推送
- Category: Workflow & Collaboration
- Instructions:
  - moneyhelper 项目同步在 5 个平台，开发后的推送需覆盖全部远程：
    - gitcode: https://gitcode.com/badhope/moneyhelper.git (账号 badhopel)
    - gitee: https://gitee.com/badhope/moneyhelper.git (账号 badhope)
    - github-morningstar: https://github.com/Morningstar202604/moneyhelper.git
    - github-badhope: https://github.com/badhope/moneyhelper.git
    - github-x33834: https://github.com/X33834/moneyhelper.git
  - 凭据统一由本机凭据库提供（不写入仓库、不打印）
  - 2026-10-18 更新：5 个平台 token 全部有效（x33834/badhope 的 GitHub token 曾因转录错误 401，用户提供正确转写后恢复）
  - 推送避坑（2026-10-18 实测）：
    - 环境注入的 credential helper（/app/agent/bin/agent git-credential-helper）对 GitHub 返回 500，GitHub 推送需显式凭据 URL 或固化到 remote push URL
    - credential store 同域（github.com）多账号会互相干扰：三个 GitHub 远程已用 git remote set-url --push 固化各自账号凭据
    - gitee/gitcode 用远程名正常推送
    - 重新克隆后远程名只有 origin，需重建五个远程（gitee/gitcode/github-morningstar/github-badhope/github-x33834）；scripts/push-all.sh 里的远程名与实际拓扑已不符，勿直接使用
    - 五端拓扑：badhope（Gitee/GitCode/GitHub）为主仓，X33834 与 Morningstar202604 为 GitHub 镜像；X33834 仓库 Actions 已通过 API 关闭（PUT /actions/permissions {"enabled":false}），镜像上不跑 CI，历史五端保持完全一致
  - 2026-10-18 探测时 4 个平台同步在 ad8ce8a，仅 GitHub/X33834 落后在 fb06e72；克隆源为 gitee
  - 项目主目录：/workspace/moneyhelper，推送时用 `git push <remote> main` 逐个推送

[Moneyhelper 项目概况]
- Date: 2026-10-18
- Context: 克隆项目后阅读 README 了解项目定位
- Category: Environment Configuration
- Instructions:
  - Moneyhelper（moneyhelper）：对话式个人财务助手，MIT 协议
  - 技术栈：backend = Python FastAPI + LangGraph 多 Agent（supervisor/bookkeeping/portfolio）+ SQLite 本地存储 + LiteLLM 多模型接入 + MCP Server（fastmcp）；frontend = React 19 + Vite + shadcn/ui + TanStack Table
  - 关键特性：数据 100% 本地、确定性引擎算账（模型只分类不碰数字）、SSE 流式、PWA、Arize Phoenix 可观测、mem0 记忆
  - 文档集中在 docs/（ARCHITECTURE-v2.md、PLAN-DETAILED.md、ROADMAP-v3.md 等）

[进度真源：docs/PROGRESS.md]
- Date: 2026-10-18
- Context: 用户询问"到底还有多少没做"，并要求处理上下文、砍掉多余部分、以后不用再读规划文档
- Category: Workflow & Collaboration
- Instructions:
  - 任何"还剩什么/做到哪了"的问题，只读 `docs/PROGRESS.md`，不要回头读 `docs/PLAN-DETAILED.md` 或 `docs/planning/` 下的规划文档
  - 每完成一个里程碑必须更新 PROGRESS.md 的状态表与变更记录，保持它是唯一进度真源
  - 规划文档只在需要"某一步的具体做法"时查阅，不用于判断进度
  - 重复文档已清理：`docs/planning/10-详细实施计划-步骤版.md` 与 `docs/PLAN-DETAILED.md` 曾逐字重复（仅测试数不同），存档已删除

[环境：磁盘与缓存维护]
- Date: 2026-10-18
- Context: 磁盘 20G 长期处于 91% 占用，多次因 pip/uv 缓存积压触发 No space left on device
- Category: Environment Configuration
- Instructions:
  - 可用空间约 1.9G，装依赖优先用 `backend/.venv/bin/uv pip install --index-url https://pypi.tuna.tsinghua.edu.cn/simple`
  - 定期清理：`.ruff_cache`、`backend/.pytest_cache`、`frontend/test-results`、项目内 `__pycache__`（都不入库，已写进 .gitignore）
  - 全局缓存 `~/.cache/uv`（629M）与 `~/.cache/ms-playwright`（658M）按需保留，不要盲目删——重装成本高
