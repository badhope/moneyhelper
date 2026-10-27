# 命令行（CLI）

Moneyhelper 自带一个命令行入口，直连本地数据库，**不需要启动服务、不产生网络请求**。
适合写脚本、做定时任务、或在服务器上快速记账与查询。

## 安装

CLI 随仓库提供，无需单独安装。在仓库根目录：

```bash
# 用项目虚拟环境运行（推荐）
backend/.venv/bin/python -m moneyhelper.cli --help

# 或装成命令（可编辑安装，之后任意目录可用 moneyhelper）
pip install -e .
moneyhelper --help
```

## 常用命令

```bash
# 一句话记账：规则解析，不花 token
moneyhelper add "午饭 35 元"
moneyhelper add "昨天打车 32 元"
moneyhelper add "发工资 12000"

# 看流水（默认最近 20 条）
moneyhelper ls
moneyhelper ls --month 2026-09 --limit 50

# 本月收支概览（含风险提示）
moneyhelper report

# 组合市值与浮动盈亏（默认用本地快照价，离线可用）
moneyhelper balance
moneyhelper balance --live        # 显式拉实时行情

# 走完整问答管线（离线时用确定性模板）
moneyhelper ask "这个月花多了吗"

# 起本地服务
moneyhelper serve --port 8788
```

## 全局参数

| 参数 | 说明 |
|---|---|
| `--db PATH` | 指定数据库文件，默认 `backend/data/wealth.db` |
| `--json` | 输出 JSON，便于 `jq` 等工具处理 |
| `--url URL` | 远程模式：走 HTTP API，不碰本地库 |
| `--token TOKEN` | 远程模式的访问口令 |

远程模式与本地模式是**同一套命令**：

```bash
# 本机直连数据库
moneyhelper ls

# 连接另一台机器上运行的 Moneyhelper
moneyhelper --url http://192.168.1.10:8788 --token "$API_TOKEN" ls
```

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 参数或数据错误 |
| 2 | 记账解析失败（这句话里没找到金额） |

脚本里可以直接判断：

```bash
if moneyhelper add "$TEXT"; then
  echo "已记账"
else
  echo "解析失败，请换个说法"
fi
```

## 设计说明

CLI 直接调用 `moneyhelper.core`，不经过 HTTP 层。这样同一条逻辑（记账解析、账本统计、
风险评估）在 CLI、MCP Server、部门模式里是同一份实现，不会因为入口不同而产生行为差异。

`balance` 默认走快照价的实现见 `app/quotes.py` 的 `snapshot_only()`：它是一个
ContextVar 开关，只在当前调用栈内生效，不会改写用户的持久化偏好设置。
