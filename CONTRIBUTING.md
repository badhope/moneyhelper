# 贡献指南

感谢你对 **Moneyhelper** 的关注！欢迎以任何形式参与贡献：提 Issue、修 Bug、写文档、加功能都可以。

## 快速开始

1. Fork 本仓库到你的账号
2. 从 `main` 创建功能分支：`git checkout -b feat/your-feature`
3. **新手必读 [开发指南](docs/DEVELOPMENT.md)**（代码地图、加工具/加设置/加路由的 6 步教程、调试技巧）
4. 本地跑起来：

   ```bash
   cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   .venv/bin/python -m uvicorn app.main:app --port 8787     # 后端 http://127.0.0.1:8787
   cd frontend && npm install && npm run dev                # 前端 http://127.0.0.1:5199
   ```

5. 提交改动并发起 Pull Request，描述清楚改了什么、为什么改

## 本地开发与测试（提交前必过）

```bash
cd backend
.venv/bin/python -m pytest tests -q --cov=app   # 546 个用例全绿
.venv/bin/python -m ruff check app tests        # 0 错误
cd frontend && npm run build                    # tsc + vite 构建通过
```

- 新功能/修复请**配套测试**（`tests/` 按模块归文件），测试不触网、函数级隔离
- 改设置项/新增配置：后端校验 + `tools.py` 白名单 + 前端双语文案 + `docs/CONFIG.md` 三处同步
- 不要破坏三条铁律：数字只由分析内核算、写操作只走确定性分支、外部失败自动降级

## 提交规范

- 提交信息建议遵循 Conventional Commits：`feat: 新增xx`、`fix: 修复xx`、`docs: 文档`、`chore: 杂务`
- 每个提交聚焦单一改动，便于回溯与回滚
- 不要把密钥、个人数据提交进仓库

## 问题反馈

- 提 Issue 前请先搜索是否已有同类问题
- Bug 请附上复现步骤、预期/实际行为、环境信息
- 功能建议请说明使用场景

## 行为准则

参与贡献即表示同意遵守 [贡献者行为准则](CODE_OF_CONDUCT.md)。

## 发布流程（维护者）

每次对外更新按此清单执行，不跳步：

1. **定版本**：按语义化版本（SemVer）——修 Bug 升补丁位、新功能升次版本、破坏性改动升主版本
2. **同步文档**：改代码的同时更新 README（版本/截图，如界面有变）与依赖清单（requirements / package.json）
3. **本地验证**：跑通测试与构建（与 CI 同款命令），全绿才继续
4. **合并**：以 PR 方式合入 `main`，CI 全绿后合并
5. **打标签**：`git tag -a vX.Y.Z -m "vX.Y.Z"` 并推送（`git push origin vX.Y.Z`）
6. **发布**：基于该 tag 创建 GitHub Release，Release Notes 写清本次变更要点
7. **部署**：确认 GitHub Pages / 站点自动部署完成且可访问

变更记录以 GitHub Releases 与 git log 为准。
