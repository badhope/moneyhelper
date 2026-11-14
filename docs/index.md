# Moneyhelper · 能自主干活的 AI 财务部门

> 算清每一笔，攒稳每一步。面向个人与小微企业的 AI 财务部门：一句话记账、企业总账、报销、采购应付、银行对账、持仓风控、财报分析、税负测算 —— 每个数字由确定性引擎算出并可追溯。

## 先读这几篇

| 文档 | 用途 |
|---|---|
| [快速开始](quickstart.md) | 15 分钟跑起全栈 |
| [架构总览](architecture.md) | 分层与数据流（Mermaid 图） |
| [模块地图](module-map.md) | 哪个文件负责什么 |
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
| [MCP 接入](mcp-guide.md) | 把 63 个工具接进 Claude Code / Cursor / Cline |
| [连接中心](connect-hub.md) / [深度接入](connect-hub-deep.md) | 行情、券商、外部数据源 |
| [Agent Studio](studio.md) | 角色 / 技能 / 提示词 / Hook / 权限 |
| [工作流](WORKFLOW.md) / [Workflow (EN)](WORKFLOW.en.md) | 典型任务的操作路径 |
| [可复核性标准](reviewability-standard.md) | 什么叫「这个数字可信」 |

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
