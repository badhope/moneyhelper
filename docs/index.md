# Moneyhelper · Documentation

[English](index.md) · [简体中文](index.zh.md)

> Bookkeeping in one sentence, an enterprise general ledger, expense claims, procurement and payables, bank reconciliation, portfolio risk, statements and tax — every figure computed by a deterministic engine and traceable back to the code that produced it.

## Start here

| Document | Use it for |
|---|---|
| [Quick start](quickstart.md) | Full stack running in about 15 minutes |
| [Architecture](architecture.md) | Layers and data flow (Mermaid) |
| [Module map](module-map.md) | Which file owns what |
| [Project baseline 4.17.2](BASELINE.md) | Four blocks: current state, delivered, backlog, roadmap; includes tax timeline, attribution, retry/dead-letter |
| [Market positioning 4.17.0 / 4.17.1](POSITIONING-4.17.0.md) | Competitor matrix, personal/enterprise boundary, compliance limits; 4.17.1 capability addendum |
| [Stress test 4.17.0](STRESS-4.17.0.md) | Personal 10M assets, multi-entity ledger, SQLite concurrency |
| [Scheduler resilience 4.17.2](SCHEDULER-4.17.2.md) | Retry boundaries, dead letters, replay, startup month-end catch-up |
| [Progress](PROGRESS.md) | What is done, what is left |
| [Self-check log](SELF-CHECK.md) | Measured evidence per delivery round |

## Install and deploy

| Document | Use it for |
|---|---|
| [Deploy (EN)](DEPLOY.en.md) / [部署（中文）](DEPLOY.md) | Docker / source / desktop |
| [Self-hosting](self-host.md) | Reverse proxy, auth, backup policy |
| [Development (EN)](DEVELOPMENT.en.md) / [开发指南](DEVELOPMENT.md) | Local setup, code map, pre-commit checks |
| [Config (EN)](CONFIG.en.md) / [配置](CONFIG.md) | Environment variables and settings |
| [Release process](RELEASE.md) | Version derivation, tags, GitHub Release |

## Features and use

| Document | Use it for |
|---|---|
| [CLI](cli.md) | Bookkeeping and queries from a terminal |
| [MCP guide](mcp-guide.md) | Drive the ledger from Claude Code / Cursor / Cline |
| [Connect hub](connect-hub.md) / [Deeper integrations](connect-hub-deep.md) | Quotes, brokers, external sources |
| [Agent Studio](studio.md) | Roles, skills, prompts, hooks, permissions |
| [Workflow (EN)](WORKFLOW.en.md) / [工作流](WORKFLOW.md) | How typical tasks are done end to end |
| [Reviewability standard](reviewability-standard.md) | What makes a number trustworthy |
| [Financial identity and monthly review](personal-review.md) | Verifiable identity card, month-end closing review, agent tools |
| [Answer sources and quality feedback](answer-trust.md) | In-message source chips, thumbs up/down, reason tags, tenant-scoped summary |
| [Reference a workbench file in chat](chat-file-reference.md) | `@` mention of an existing attachment, no re-upload, removing a reference never deletes the file |
| [Session project, share, canvas and research](chat-context-tools.md) | Cross-session project library, vision input, read-only share, answer canvas with Word/HTML export, deep research and answer length |
| [Long-task observability 4.16.49](LONG-TASK-OBSERVABILITY-4.16.49.md) | Live tool-stage progress, diff-aware staleness, and a real four-stage research run |
| [Long-task contract and rollback 4.16.48](LONG-TASK-CONTRACT-4.16.48.md) | Stage contracts, downstream staleness, checkpoint rollback, and read-only tool stages with browser evidence |
| [Long-task stage control 4.16.47](LONG-TASK-CONTROL-4.16.47.md) | Single-stage retry, `active` semantics, and stale-running recovery with browser evidence |
| [Function audit 4.16.46](FUNCTION-AUDIT-4.16.46.md) | Every setting key traced to a consumer, seven fake/ineffective behaviours fixed, harness depth re-checked with explicit limits |
| [Roadmap completion report 4.16.45](ROADMAP-COMPLETION-4.16.45.md) | The five audit gaps closed in 4.16.45 with evidence and explicit non-goals |
| [Roadmap completion report 4.16.44](ROADMAP-COMPLETION-4.16.44.md) | The remaining routes closed in 4.16.42–4.16.44, evidence, and explicit non-goals |

## Engineering

| Document | Use it for |
|---|---|
| [Architecture detail](ARCHITECTURE-detail.md) / [v2 design](ARCHITECTURE-v2.md) | Why the layers are split this way |
| [Code style](CODE_STYLE.md) | Naming, layering, comment conventions |
| [Dependency replacement](DEPENDENCY-REPLACEMENT.md) | What was hand-written, what became a library, and why |
| [Hardening log](hardening.md) | Security and stability work |
| [Doc map](doc-map.md) | Short index organised by "what I want to do" |

## Enterprise

| Document | Use it for |
|---|---|
| [Enterprise roadmap](ENTERPRISE-ROADMAP.md) | Slice boundaries, completed items, next steps |
| [Ledger and tenant strategy](LEDGER-TENANT-STRATEGY.md) | Personal vs company ledger, and why dual-write is deferred |

## Review and audit

| Document | Use it for |
|---|---|
| [Review findings](REVIEW-FINDINGS.md) | Historical review issues and their resolution |
| [Internal strict review](REVIEW-内部严格评审.md) | A stricter internal pass |
| [Enterprise deep audit](AUDIT-enterprise-deep-20261007.md) | October 2026 enterprise audit |

Documents marked 中文 are written in Chinese; the rest are English or bilingual.
