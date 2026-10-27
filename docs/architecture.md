# Moneyhelper 架构图

> 本页用 Mermaid 绘制，GitHub 原生渲染。配套：[ROADMAP-v3](ROADMAP-v3.md) / [详细计划](PLAN-DETAILED.md)

## 1. 系统总架构（部署形态无关：云 API / 自托管 / 桌面单机共用同一 core）

```mermaid
flowchart TB
    subgraph shells[前端壳（任选，均为薄壳）]
        WEB[Web/PWA<br/>React19+Vite]
        CLI[CLI xm<br/>typer]
        EXE[桌面 EXE<br/>Tauri sidecar]
        AIB[外部 AI<br/>Claude Code/Cursor]
    end
    subgraph server[server 层]
        API[FastAPI<br/>REST+SSE+JWT]
        MCP[MCP Server<br/>20+ 工具全量暴露]
    end
    subgraph core[core 确定性内核（数字只由代码算）]
        AGENTS[LangGraph 多智能体<br/>supervisor→record/market/ledger/risk/finalize]
        FIN[金融计算引擎<br/>净值/收益/健康五维]
        INGEST[导入器<br/>支付宝/微信/CSV]
        SCHED[定时任务<br/>晨报/订阅巡检]
        PROV[Provenance 审计链]
    end
    subgraph data[数据层]
        DB[(SQLite WAL<br/>db/ 域模块包)]
        POOL[读连接池 ro×3<br/>写单连接串行]
        MEM[长期记忆<br/>本地 BM25 检索，零外发]
        OBS[Phoenix OTel]
    end
    WEB --> API
    CLI --> core
    EXE --> API
    AIB --> MCP
    API --> AGENTS
    MCP --> core
    AGENTS --> FIN
    AGENTS --> DB
    FIN --> DB
    INGEST --> DB
    SCHED --> AGENTS
    DB --- POOL
    PROV -.全程审计.-> core
```

## 2. M3 财务部门模式（已上线骨架 v0）

```mermaid
flowchart LR
    BOSS[老板一句话<br/>『把上季度盘一遍』] --> SUP[工单分解<br/>规则规则版/LLM 结构化=迭代2]
    SUP --> O1[工单·会计部]
    SUP --> O2[工单·风控部]
    SUP --> O3[工单·投资部]
    SUP --> O4[工单·记账部]
    O1 -->|并行 gather| D1[确定性工具取数]
    O2 -->|并行| D2[风控信号扫描]
    O3 -->|并行| D3[市场与目标]
    O4 -->|并行| D4[记账质量核对]
    D1 --> SEC[秘书汇总<br/>合并+同口径对账+冲突标红]
    D2 --> SEC
    D3 --> SEC
    D4 --> SEC
    SEC --> RPT[呈批件<br/>含 provenance 证据索引]
    RIT2[迭代2: LLM派工/HITL呈批/SSE实况看板] -.-> SUP
    RIT2 -.-> SEC
```

## 3. 问答执行路径（单轮，agent_graph）

```mermaid
flowchart TB
    Q[用户问题] --> SUP2{supervisor 分类}
    SUP2 -->|记账| REC[record 确定性入账<br/>大额走 HITL 审批]
    SUP2 -->|财务| COL[collect_market+collect_ledger<br/>+risk 并行取数]
    SUP2 -->|闲聊| GEN[general 通用技能包<br/>不带任何财务数据出机]
    COL --> FIN2[finalize<br/>LLM function calling 成文]
    GEN --> FIN2
    FIN2 -->|失败自动降级| TPL[确定性模板成文]
    FIN2 --> SSE[事件流 start/step/agent_step/text/final/done]
    TPL --> SSE
```

## 4. 数据可靠性（M1.3 之后）

```mermaid
flowchart LR
    W[写路径<br/>单连接串行<br/>busy_timeout 5s] --> DBW[(SQLite WAL)]
    R1[读池连接 ro 1] --> DBW
    R2[读池连接 ro 2] --> DBW
    R3[读池连接 ro 3] --> DBW
    note[纪律：fetch_all 物理只读，写必须走 db.execute/域函数并真实提交] -.-> W
```
