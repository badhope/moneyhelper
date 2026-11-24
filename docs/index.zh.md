# Moneyhelper · 文档（中文）

[English](index.md) · 简体中文

> 算清每一笔，攒稳每一步。面向个人与小微企业的 AI 财务部门：一句话记账、企业总账、报销、采购应付、银行对账、持仓风控、财报分析、税负测算 —— 每个数字由确定性引擎算出并可追溯。

## 先读这几篇

| 文档 | 用途 |
|---|---|
| [快速开始](quickstart.md) | 15 分钟跑起全栈 |
| [架构总览](architecture.md) | 分层与数据流（Mermaid 图） |
| [模块地图](module-map.md) | 哪个文件负责什么 |
| [项目基线 4.18.0](BASELINE.md) | 当前状态 / 已交付 / 待开发 / 路线图四模块；含财税时序、归因规则、调度重试、死信告警与多主体合并 |
| [行业定位 4.17.0 / 4.17.1](POSITIONING-4.17.0.md) | 竞品矩阵、个人与企业边界、合规硬线；含 4.17.1 能力补充 |
| [平台压测 4.17.0](STRESS-4.17.0.md) | 个人千万资产、多主体总账、SQLite 并发 |
| [调度韧性 4.17.2](SCHEDULER-4.17.2.md) | 重试边界、死信、重放与启动月结补偿 |
| [归因规则 4.17.3](ATTRIBUTION-4.17.3.md) | 自定义规则、批量确认、误判回滚与采纳统计 |
| [多主体合并 4.18.0](CONSOLIDATION-4.18.0.md) | 集团范围、持股折算、抵销分录、合并三表与明确边界 |
| [实施进度](PROGRESS.md) | **唯一进度真源**：做到哪了、还剩什么 |
| [自检记录](SELF-CHECK.md) | 每轮交付的实测证据与遗留问题 |

## 安装与部署

| 文档 | 用途 |
|---|---|
| [部署（中文）](DEPLOY.md) / [Deploy (EN)](DEPLOY.en.md) | Docker / 源码 / 桌面版 |
| [自托管](self-host.md) | 反向代理、鉴权、备份策略 |
| [开发指南](DEVELOPMENT.md) / [Development (EN)](DEVELOPMENT.en.md) | 本地环境、代码地图、提交前检查 |
| [配置](CONFIG.md) / [Config (EN)](CONFIG.en.md) | 环境变量与设置项 |
| [发版流程](RELEASE.md) | 版本推导、tag、GitHub Release |

## 功能与使用

| 文档 | 用途 |
|---|---|
| [CLI](cli.md) | 命令行记账与查询 |
| [MCP 接入](mcp-guide.md) | 把账本工具接进 Claude Code / Cursor / Cline |
| [连接中心](connect-hub.md) / [深度接入](connect-hub-deep.md) | 行情、券商、外部数据源 |
| [Agent Studio](studio.md) | 角色 / 技能 / 提示词 / Hook / 权限 |
| [工作流](WORKFLOW.md) / [Workflow (EN)](WORKFLOW.en.md) | 典型任务的操作路径 |
| [可复核性标准](reviewability-standard.md) | 什么叫「这个数字可信」 |
| [长任务契约与回滚 4.16.48](LONG-TASK-CONTRACT-4.16.48.md) | 阶段交付契约、下游过期、检查点回滚、只读工具阶段与浏览器证据 |
| [长任务运行可见性 4.16.49](LONG-TASK-OBSERVABILITY-4.16.49.md) | 工具阶段运行中进度、差异化过期、投研四阶段真实验收 |

## 架构与工程

| 文档 | 用途 |
|---|---|
| [架构细节](ARCHITECTURE-detail.md) / [v2 设计](ARCHITECTURE-v2.md) | 历史设计与演进理由 |
| [代码风格](CODE_STYLE.md) | 命名、分层、注释约定 |
| [依赖替换记录](DEPENDENCY-REPLACEMENT.md) | 手写代码换成成熟库的清单与理由 |
| [加固记录](hardening.md) | 安全与稳定性加固项 |
| [文档地图](doc-map.md) | 按「我想做什么」的简版索引 |

## 企业化改造

| 文档 | 用途 |
|---|---|
| [企业化路线图](ENTERPRISE-ROADMAP.md) | 切片 1-10 的边界、已完成项与下一步 |
| [账本与租户策略](LEDGER-TENANT-STRATEGY.md) | 个人账本 vs 企业账本、双写为何暂缓 |
| [自检记录](SELF-CHECK.md) | 采购应付、长任务、安全边界的实测证据 |

## 评审与审计

| 文档 | 用途 |
|---|---|
| [评审发现](REVIEW-FINDINGS.md) | 历史评审问题清单与处理结果 |
| [内部严格评审](REVIEW-内部严格评审.md) | 更严格的内部审查记录 |
| [企业深度审计](AUDIT-enterprise-deep-20261007.md) | 2026-10 企业化深度审计 |
| [前端审计](AUDIT-frontend.md) | 前端专项问题 |
| [差异化分析](DIFFERENTIATION.md) | 与同类产品的定位差异 |

## 规划

| 文档 | 用途 |
|---|---|
| [ROADMAP-v3](ROADMAP-v3.md) | 产品路线 |
| [详细计划](PLAN-DETAILED.md) | 里程碑拆分 |
| [实施进度](PROGRESS.md) | 当前状态（以此为准） |
